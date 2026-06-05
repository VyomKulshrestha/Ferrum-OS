# FerrumOS Build Helper Script
# Usage: .\build.ps1 [build|run|clean|check]

param(
    [string]$Action = "build"
)

# Ensure the nightly rustup toolchain takes priority over standalone Rust
# installations. This machine also has a stable Rust install in Program Files;
# putting the nightly toolchain bin first keeps cargo's child rustc invocations
# on the same toolchain that owns the x86_64-unknown-none target.
$NightlyBin = "$env:USERPROFILE\.rustup\toolchains\nightly-x86_64-pc-windows-msvc\bin"
$CargoBin = "$env:USERPROFILE\.cargo\bin"
$env:Path = "$NightlyBin;$CargoBin;" + [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

switch ($Action) {
    "build" {
        Write-Host "Building FerrumOS..." -ForegroundColor Cyan
        cargo build 2>&1 | ForEach-Object { $_.ToString() }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "`nKernel build failed." -ForegroundColor Red
            exit $LASTEXITCODE
        }

        if (Test-Path "target\x86_64-unknown-none\debug\FerrumOS") {
            Write-Host "`nBuild successful!" -ForegroundColor Green
            cargo bootimage 2>&1 | ForEach-Object { $_.ToString() }
            if ($LASTEXITCODE -ne 0) {
                Write-Host "Boot image creation failed." -ForegroundColor Red
                exit $LASTEXITCODE
            }
            $img = "target\x86_64-unknown-none\debug\bootimage-ferrumos.bin"
            if (Test-Path $img) {
                $size = (Get-Item $img).Length
                Write-Host "Boot image: $img ($([math]::Round($size/1KB)) KB)" -ForegroundColor Green
            }
        }
    }
    "run" {
        Write-Host "Building and running FerrumOS in QEMU..." -ForegroundColor Cyan
        cargo bootimage 2>&1 | ForEach-Object { $_.ToString() }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Boot image creation failed." -ForegroundColor Red
            exit $LASTEXITCODE
        }
        $img = "target\x86_64-unknown-none\debug\bootimage-ferrumos.bin"
        if (Test-Path $img) {
            $qemu = (Get-Command qemu-system-x86_64 -ErrorAction SilentlyContinue).Source
            if (-not $qemu -and (Test-Path "C:\Program Files\GNS3\qemu-3.1.0\qemu-system-x86_64.exe")) {
                $qemu = "C:\Program Files\GNS3\qemu-3.1.0\qemu-system-x86_64.exe"
            }
            if (-not $qemu) {
                Write-Host "qemu-system-x86_64 not found. Install QEMU or add it to PATH." -ForegroundColor Red
                exit 1
            }
            & $qemu -drive format=raw,file=$img -serial stdio -vga std -netdev user,id=net0,hostfwd=tcp::8785-:8785 -device rtl8139,netdev=net0 -device intel-hda -device hda-duplex
        } else {
            Write-Host "Boot image not found. Build first." -ForegroundColor Red
            exit 1
        }
    }
    "clean" {
        Write-Host "Cleaning build artifacts..." -ForegroundColor Yellow
        cargo clean 2>&1 | ForEach-Object { $_.ToString() }
        Write-Host "Clean complete." -ForegroundColor Green
    }
    "check" {
        Write-Host "Checking FerrumOS for errors..." -ForegroundColor Cyan
        cargo check 2>&1 | ForEach-Object { $_.ToString() }
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    default {
        Write-Host "Usage: .\build.ps1 [build|run|clean|check]" -ForegroundColor Yellow
    }
}
