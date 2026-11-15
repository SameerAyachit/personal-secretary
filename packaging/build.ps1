<#
.SYNOPSIS
  Build the Secretary one-folder app and prove the result starts.

.DESCRIPTION
  1. Stops a running secretary.exe from the build folder (it would lock the file).
     Other copies, such as your installed app, are left alone.
  2. Runs PyInstaller with packaging\secretary.spec.
  3. Runs `secretary.exe --diagnose` on the frozen build and fails unless it exits 0.
  4. Optionally builds the installer (-Installer) when Inno Setup's iscc is on PATH.

  Any failing step stops the script with a non-zero exit code.

.EXAMPLE
  powershell -File packaging\build.ps1
  powershell -File packaging\build.ps1 -Installer
#>
param(
    [switch]$Installer,
    [string]$Version = "",
    [string]$DistPath = "dist",
    [string]$WorkPath = "build"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Fail([string]$message) {
    Write-Host "BUILD FAILED: $message" -ForegroundColor Red
    exit 1
}

# 1. Stop a running copy so the exe is not locked.
$target = [System.IO.Path]::GetFullPath((Join-Path $DistPath "secretary\secretary.exe"))
$running = Get-Process -Name secretary -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $target }   # only the copy this build would overwrite
if ($running) {
    Write-Host "Stopping running secretary.exe ($($running.Count) process)..."
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# 2. Build.
Write-Host "Running PyInstaller..."
python -m PyInstaller packaging\secretary.spec --noconfirm --distpath $DistPath --workpath $WorkPath
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller exited with $LASTEXITCODE" }

$exe = Join-Path $DistPath "secretary\secretary.exe"
if (-not (Test-Path $exe)) { Fail "$exe was not produced" }

# 3. The frozen app must pass its own diagnostics. It is a windowed exe, so
#    capture output through redirected files.
Write-Host "Running --diagnose on the frozen build..."
$out = Join-Path $env:TEMP "secretary_diagnose_out.txt"
$err = Join-Path $env:TEMP "secretary_diagnose_err.txt"
$proc = Start-Process -FilePath $exe -ArgumentList "--diagnose" -Wait -PassThru `
    -RedirectStandardOutput $out -RedirectStandardError $err
Get-Content $out -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
if ($proc.ExitCode -ne 0) {
    Get-Content $err -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
    Fail "--diagnose exited with $($proc.ExitCode)"
}

# 4. Installer (optional).
if ($Installer) {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) { Fail "iscc (Inno Setup) is not on PATH; install Inno Setup 6 or omit -Installer" }
    Write-Host "Building installer..."
    $isccArgs = @("packaging\installer.iss")
    if ($Version) { $isccArgs = @("/DMyAppVersion=$Version") + $isccArgs }
    & iscc.exe @isccArgs
    if ($LASTEXITCODE -ne 0) { Fail "iscc exited with $LASTEXITCODE" }
}

Write-Host "BUILD OK: $exe" -ForegroundColor Green
exit 0
