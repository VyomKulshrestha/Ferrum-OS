# Helper script to build heliox-bridge using the correct nightly toolchain
# This bypasses the standalone stable Rust installation on this machine

$NightlyBin = "$env:USERPROFILE\.rustup\toolchains\nightly-x86_64-pc-windows-msvc\bin"
$CargoBin = "$env:USERPROFILE\.cargo\bin"
$env:Path = "$NightlyBin;$CargoBin;" + [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "Building heliox-bridge..." -ForegroundColor Cyan
cargo build --release --target x86_64-unknown-none
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Build successful!" -ForegroundColor Green
