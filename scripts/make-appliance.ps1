# scripts/make-appliance.ps1
# Build the OS, generate model fixtures, create the model disk image, and write it to disk.

# 1. Build boot image and daemon
Write-Host "Building FerrumOS and userspace binaries..." -ForegroundColor Cyan
& .\build.ps1 build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

# 2. Verify the real model assets are present. These are checked into
# appliance/models/ (see appliance/models/README.md for provenance and how
# to regenerate/upgrade them) - deliberately NOT scripts/generate_mock_model.mjs's
# synthetic fixture, which exists only for the automated verify scripts'
# byte-exact-determinism tests and would ship a gibberish "brain" if used here.
Write-Host "Checking for real model assets..." -ForegroundColor Cyan
$modelSrc = "appliance/models/stories15M-q8.bin"
$tokenizerSrc = "appliance/models/tokenizer.bin"
if (-not (Test-Path $modelSrc) -or -not (Test-Path $tokenizerSrc)) {
    Write-Host "Missing $modelSrc or $tokenizerSrc - see appliance/models/README.md to generate them." -ForegroundColor Red
    exit 1
}

# 3. Create the ext2 disk image
Write-Host "Creating ext2 raw disk image..." -ForegroundColor Cyan
if (Test-Path "target\heliox-disk.img") {
    Remove-Item "target\heliox-disk.img" -Force
}

# Use dd to create a 32MB zero-filled file
wsl dd if=/dev/zero of=target/heliox-disk.img bs=1M count=32
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create target/heliox-disk.img via dd!" -ForegroundColor Red
    exit 1
}

# Format the image as ext2
wsl mke2fs -F target/heliox-disk.img
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to format target/heliox-disk.img via mke2fs!" -ForegroundColor Red
    exit 1
}

# 4. Inject model files using debugfs
Write-Host "Injecting model and tokenizer into the disk image..." -ForegroundColor Cyan

# Create directories step by step
wsl debugfs -w -R "mkdir /heliox" target/heliox-disk.img
wsl debugfs -w -R "mkdir /heliox/models" target/heliox-disk.img

# Write files (the real model - see appliance/models/README.md)
wsl debugfs -w -R "write $modelSrc /heliox/models/stories15M-q8.bin" target/heliox-disk.img
wsl debugfs -w -R "write $tokenizerSrc /heliox/tokenizer.bin" target/heliox-disk.img

# 5. Stage ferrumpkg's local package cache. Packages are never written by
# the kernel's own ext2 create_file at runtime - it only supports direct
# blocks (12 max), far too small for a compiled ELF - so every package
# binary is injected here, at build time, via debugfs (an independent,
# unconstrained ext2 implementation) exactly like the model checkpoint
# above. `pkg install` only ever toggles a small runtime registry file;
# see src/pkg/mod.rs for the full rationale.
Write-Host "Staging ferrumpkg packages onto the disk image..." -ForegroundColor Cyan
$notesElf = "userland/notes/target/x86_64-unknown-none/release/notes"
if (-not (Test-Path $notesElf)) {
    Write-Host "Missing $notesElf - did the userland build succeed?" -ForegroundColor Red
    exit 1
}

# Written under target/ (repo-relative), not the system temp directory -
# `wsl debugfs` resolves relative paths against the repo the same way
# $modelSrc/$notesElf already do above, but can't see a Windows temp path
# like C:\Users\...\AppData\Local\Temp\... since that's outside the WSL
# mount it operates from.
$notesManifest = "target/notes-manifest.txt"
@"
name=notes
version=1.0.0
description=A simple persistent scratchpad, installed on demand
capabilities=cap:gui:window,cap:fs:read,cap:fs:write
"@ | Set-Content -Path $notesManifest -NoNewline -Encoding ascii

wsl debugfs -w -R "mkdir /pkgs-available" target/heliox-disk.img
wsl debugfs -w -R "mkdir /pkgs-available/notes" target/heliox-disk.img
wsl debugfs -w -R "mkdir /pkgs" target/heliox-disk.img
wsl debugfs -w -R "write $notesManifest /pkgs-available/notes/manifest.txt" target/heliox-disk.img
wsl debugfs -w -R "write $notesElf /pkgs-available/notes/bin" target/heliox-disk.img
Remove-Item $notesManifest -Force

# 6. Stage the world model's Phase 2 learned transition weights, if
# trained (scripts/train_world_model.py). Entirely optional - a missing
# file here just means heliox-daemon keeps using Phase 1's rule table
# (cognitive/world_model/learned.rs's try_load() no-ops on a missing
# file), so this never blocks appliance packaging the way the real LLM
# checkpoint above does.
$learnedWeights = "target/world_model_learned.bin"
if (Test-Path $learnedWeights) {
    Write-Host "Staging learned world-model weights onto the disk image..." -ForegroundColor Cyan
    wsl debugfs -w -R "mkdir /heliox/world" target/heliox-disk.img
    wsl debugfs -w -R "write $learnedWeights /heliox/world/model_learned.bin" target/heliox-disk.img
} else {
    Write-Host "No trained world-model weights found at $learnedWeights - heliox-daemon will use the Phase 1 rule table (run scripts/collect_world_model_dataset.mjs + scripts/train_world_model.py to train one)." -ForegroundColor Yellow
}

# 7. Stage the world model's learned encoder weights, if trained
# (scripts/train_world_model_encoder.py). Same optional pattern as the
# transition weights above - a missing file just leaves the embedding's
# tail slots at zero (encoder_learned.rs's try_load() no-ops).
$encoderWeights = "target/world_model_encoder.bin"
if (Test-Path $encoderWeights) {
    Write-Host "Staging learned world-model encoder onto the disk image..." -ForegroundColor Cyan
    wsl debugfs -w -R "mkdir /heliox/world" target/heliox-disk.img
    wsl debugfs -w -R "write $encoderWeights /heliox/world/model_encoder.bin" target/heliox-disk.img
} else {
    Write-Host "No trained world-model encoder found at $encoderWeights - heliox-daemon will leave the embedding's latent slots at zero (run scripts/train_world_model_encoder.py to train one)." -ForegroundColor Yellow
}

Write-Host "Disk image target/heliox-disk.img successfully created and packaged!" -ForegroundColor Green
