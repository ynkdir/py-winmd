<#
.SYNOPSIS
    Downloads the .winmd files used by the tests and examples with nuget.exe.

.DESCRIPTION
    The metadata is not part of this repository. This script installs the
    NuGet packages that ship the .winmd files and copies them into metadata/:

        metadata\Microsoft.Windows.SDK.Contract       WinRT contracts (Windows SDK)
        metadata\Microsoft.Windows.SDK.Win32Metadata  Win32 API metadata
        metadata\Microsoft.WindowsAppSDK.WinUI        WinUI 3 metadata

    nuget.exe is taken from PATH; if it is not installed it is downloaded to
    .tools\nuget.exe.

.PARAMETER Force
    Re-copy the .winmd files even when metadata/ is already populated.

.EXAMPLE
    .\fetch-metadata.ps1
    .\.venv\Scripts\Activate.ps1
    python tests\test_winmd.py
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = 'metadata',
    [string]$PackageDirectory = '.packages',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# The directory names are kept as they are, the package ids differ slightly.
$packages = @(
    [pscustomobject]@{
        Id         = 'Microsoft.Windows.SDK.Contracts'
        Version    = $null              # latest stable
        Prerelease = $false
        Source     = 'ref\netstandard2.0'
        Target     = 'Microsoft.Windows.SDK.Contract'
    }
    [pscustomobject]@{
        Id         = 'Microsoft.Windows.SDK.Win32Metadata'
        Version    = $null
        Prerelease = $true              # only published as a preview package
        Source     = '.'
        Target     = 'Microsoft.Windows.SDK.Win32Metadata'
    }
    [pscustomobject]@{
        Id         = 'Microsoft.WindowsAppSDK.WinUI'
        Version    = $null
        Prerelease = $false
        Source     = 'metadata'
        Target     = 'Microsoft.WindowsAppSDK.WinUI'
    }
)

# --- nuget.exe ---------------------------------------------------------------
$nuget = (Get-Command nuget.exe -ErrorAction SilentlyContinue).Source
if (-not $nuget) {
    $nuget = Join-Path $PSScriptRoot '.tools\nuget.exe'
    if (-not (Test-Path $nuget)) {
        Write-Host '==> downloading nuget.exe' -ForegroundColor Cyan
        New-Item -ItemType Directory -Force (Split-Path $nuget) | Out-Null
        Invoke-WebRequest -Uri 'https://dist.nuget.org/win-x86-commandline/latest/nuget.exe' `
            -OutFile $nuget
    }
}
Write-Host "==> using $nuget"

# --- packages ----------------------------------------------------------------
foreach ($package in $packages) {
    $target = Join-Path $OutputDirectory $package.Target

    if ((Test-Path $target) -and -not $Force -and
        (Get-ChildItem $target -Filter *.winmd -ErrorAction SilentlyContinue)) {
        Write-Host "==> $($package.Target) already present, skipping (use -Force to refresh)"
        continue
    }

    Write-Host "==> installing $($package.Id)" -ForegroundColor Cyan
    $arguments = @(
        'install', $package.Id
        '-OutputDirectory', $PackageDirectory
        '-ExcludeVersion'
        '-NonInteractive'
    )
    if ($package.Version) { $arguments += @('-Version', $package.Version) }
    if ($package.Prerelease) { $arguments += '-Prerelease' }

    & $nuget @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "nuget install $($package.Id) failed with exit code $LASTEXITCODE"
    }

    $source = Join-Path (Join-Path $PackageDirectory $package.Id) $package.Source
    $files = Get-ChildItem $source -Filter *.winmd -File
    if (-not $files) {
        throw "no .winmd files found in $source"
    }

    New-Item -ItemType Directory -Force $target | Out-Null
    $files | Copy-Item -Destination $target -Force
    Write-Host ("    {0} -> {1}" -f "$($files.Count) .winmd", $target)
}

$total = (Get-ChildItem $OutputDirectory -Recurse -Filter *.winmd).Count
Write-Host ''
Write-Host "$total .winmd files in $OutputDirectory" -ForegroundColor Green
