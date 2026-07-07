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

Write-Host "Disk image target/heliox-disk.img successfully created and packaged!" -ForegroundColor Green
