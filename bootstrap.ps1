<#
.SYNOPSIS
    Sets up the .venv build environment and builds winmd with Meson.

.DESCRIPTION
    Fetches the Microsoft.Windows.WinMD headers with NuGet, creates .venv,
    installs the build dependencies (meson-python, meson, ninja, nanobind),
    fetches the nanobind / robin-map Meson wraps and performs an editable
    install of the extension using the MSVC toolchain.

    The .winmd test data is fetched separately with fetch-packages.ps1.

.PARAMETER Wheel
    Build a redistributable wheel into dist/ instead of installing in editable
    mode.

.EXAMPLE
    .\bootstrap.ps1
    .\.venv\Scripts\Activate.ps1
    python tests\test_winmd.py
#>
[CmdletBinding()]
param(
    [switch]$Wheel
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# --- C++ headers that are wrapped (Microsoft.Windows.WinMD) ------------------
& (Join-Path $PSScriptRoot 'fetch-packages.ps1') -Kind library

# --- Python environment ------------------------------------------------------
if (-not (Test-Path .venv)) {
    Write-Host '==> creating .venv' -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host '==> installing build dependencies' -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install --upgrade meson-python meson ninja nanobind

# --- Meson subprojects (nanobind + robin-map) --------------------------------
New-Item -ItemType Directory -Force subprojects | Out-Null
if (-not (Test-Path subprojects\nanobind.wrap)) {
    Write-Host '==> installing meson wraps' -ForegroundColor Cyan
    & .\.venv\Scripts\meson.exe wrap install robin-map
    & .\.venv\Scripts\meson.exe wrap install nanobind
}

# --- MSVC toolchain ----------------------------------------------------------
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe not found - Visual Studio (with the C++ workload) is required."
}
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) {
    throw "No Visual Studio installation with the C++ tools was found."
}
$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'

# meson/ninja live in .venv\Scripts and vcvars64.bat needs the VS installer
# directory on PATH for vswhere.
$paths = @(
    (Resolve-Path .\.venv\Scripts).Path
    (Split-Path $vswhere)
) -join ';'

if ($Wheel) {
    $command = 'python -m pip wheel --no-build-isolation --no-deps -w dist .'
    Write-Host '==> building wheel' -ForegroundColor Cyan
}
else {
    $command = 'python -m pip install --no-build-isolation -e .'
    Write-Host '==> building (editable install)' -ForegroundColor Cyan
}

cmd /c "set `"PATH=$paths;%PATH%`" && call `"$vcvars`" >nul && $command"
if ($LASTEXITCODE -ne 0) {
    throw "build failed with exit code $LASTEXITCODE"
}

Write-Host ''
Write-Host 'Done. Activate the environment before using or rebuilding winmd:' -ForegroundColor Green
Write-Host '    .\.venv\Scripts\Activate.ps1'
Write-Host '    python tests\test_winmd.py'
