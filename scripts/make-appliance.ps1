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
$notesElf = "appliance/packages/notes/bin"
if (-not (Test-Path $notesElf)) {
    Write-Host "Missing immutable signed package binary $notesElf." -ForegroundColor Red
    exit 1
}

# Written under target/ (repo-relative), not the system temp directory -
# `wsl debugfs` resolves relative paths against the repo the same way
# $modelSrc/$notesElf already do above, but can't see a Windows temp path
# like C:\Users\...\AppData\Local\Temp\... since that's outside the WSL
# mount it operates from.
$notesManifest = "appliance/packages/notes/manifest.txt"
$notesSignature = "appliance/packages/notes/manifest.sig"
if (-not (Test-Path $notesManifest) -or -not (Test-Path $notesSignature)) {
    Write-Host "Missing signed notes package metadata." -ForegroundColor Red
    exit 1
}
$manifestHashLine = Select-String -Path $notesManifest -Pattern '^binary_sha256=([0-9a-f]{64})$'
if (-not $manifestHashLine) {
    Write-Host "Signed notes manifest has no valid binary_sha256." -ForegroundColor Red
    exit 1
}
$expectedNotesHash = $manifestHashLine.Matches[0].Groups[1].Value
$actualNotesHash = (Get-FileHash -Algorithm SHA256 $notesElf).Hash.ToLowerInvariant()
if ($actualNotesHash -ne $expectedNotesHash) {
    Write-Host "Notes ELF digest changed; refusing to package it under the existing signature." -ForegroundColor Red
    Write-Host "Expected: $expectedNotesHash" -ForegroundColor Red
    Write-Host "Actual:   $actualNotesHash" -ForegroundColor Red
    exit 1
}

wsl debugfs -w -R "mkdir /pkgs-available" target/heliox-disk.img
wsl debugfs -w -R "mkdir /pkgs-available/notes" target/heliox-disk.img
wsl debugfs -w -R "mkdir /pkgs" target/heliox-disk.img
wsl debugfs -w -R "write $notesManifest /pkgs-available/notes/manifest.txt" target/heliox-disk.img
wsl debugfs -w -R "write $notesSignature /pkgs-available/notes/manifest.sig" target/heliox-disk.img
wsl debugfs -w -R "write $notesElf /pkgs-available/notes/bin" target/heliox-disk.img

# 6. Stage a matched world-model pair. A locally trained target/ pair is an
# explicit development override; clean checkouts use the versioned release
# assets. Never mix one local component with one release component because
# their latent coordinate systems must match exactly.
$targetLearnedWeights = "target/world_model_learned.bin"
$targetEncoderWeights = "target/world_model_encoder.bin"
$releaseWorldModelDir = "appliance/world-model"
$releaseManifestPath = Join-Path $releaseWorldModelDir "manifest.json"
$hasTargetLearned = Test-Path $targetLearnedWeights
$hasTargetEncoder = Test-Path $targetEncoderWeights
if ($hasTargetLearned -xor $hasTargetEncoder) {
    Write-Host "Refusing to package a partial target/ world-model pair." -ForegroundColor Red
    exit 1
}

if ($hasTargetLearned) {
    $learnedWeights = $targetLearnedWeights
    $encoderWeights = $targetEncoderWeights
    Write-Host "Using matched locally trained world-model override from target/." -ForegroundColor Cyan
} else {
    if (-not (Test-Path $releaseManifestPath)) {
        Write-Host "Versioned world-model manifest is missing: $releaseManifestPath" -ForegroundColor Red
        exit 1
    }
    $releaseManifest = Get-Content -Raw $releaseManifestPath | ConvertFrom-Json
    # debugfs runs inside WSL and requires slash-separated paths even though
    # the manifest is resolved by PowerShell on Windows.
    $learnedWeights = (Join-Path $releaseWorldModelDir $releaseManifest.files.transition.path) -replace '\\', '/'
    $encoderWeights = (Join-Path $releaseWorldModelDir $releaseManifest.files.encoder.path) -replace '\\', '/'
    foreach ($asset in @(
        @{ Path = $learnedWeights; Hash = $releaseManifest.files.transition.sha256 },
        @{ Path = $encoderWeights; Hash = $releaseManifest.files.encoder.sha256 }
    )) {
        if (-not (Test-Path $asset.Path)) {
            Write-Host "Versioned world-model asset is missing: $($asset.Path)" -ForegroundColor Red
            exit 1
        }
        $actualHash = (Get-FileHash -Algorithm SHA256 $asset.Path).Hash.ToLowerInvariant()
        if ($actualHash -ne $asset.Hash) {
            Write-Host "World-model asset digest mismatch: $($asset.Path)" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Using verified versioned JEPA world-model release assets." -ForegroundColor Cyan
}

wsl debugfs -w -R "mkdir /heliox/world" target/heliox-disk.img
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to create /heliox/world in the appliance image." -ForegroundColor Red
    exit 1
}

Write-Host "Staging learned world-model weights onto the disk image..." -ForegroundColor Cyan
wsl debugfs -w -R "write $learnedWeights /heliox/world/model_learned.bin" target/heliox-disk.img
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to stage learned world-model weights." -ForegroundColor Red
    exit 1
}

# 7. Stage the world model's learned encoder weights, if trained
# (scripts/train_world_model_encoder.py). Same optional pattern as the
# transition weights above - a missing file just leaves the embedding's
# tail slots at zero (encoder_learned.rs's try_load() no-ops).
Write-Host "Staging learned world-model encoder onto the disk image..." -ForegroundColor Cyan
wsl debugfs -w -R "write $encoderWeights /heliox/world/model_encoder.bin" target/heliox-disk.img
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to stage learned world-model encoder." -ForegroundColor Red
    exit 1
}

Write-Host "Disk image target/heliox-disk.img successfully created and packaged!" -ForegroundColor Green
