<#
.SYNOPSIS
    Downloads the .winmd files the tests and examples read.

.DESCRIPTION
    The metadata is not part of this repository. This script installs it with
    nuget.exe:

        metadata\Microsoft.Windows.SDK.Contract       WinRT contracts (Windows SDK)
        metadata\Microsoft.Windows.SDK.Win32Metadata  Win32 API metadata

    nuget.exe is taken from PATH; if it is not installed it is downloaded to
    .tools\nuget.exe.

    Building needs none of this: the C++ library that is wrapped is a Meson
    subproject (subprojects/winmd-headers.wrap) and is downloaded by the build.

.PARAMETER Force
    Re-copy the files even when the target directory is already populated.

.EXAMPLE
    .\fetch-packages.ps1
    $env:WINMD_METADATA = "$PWD\metadata"
    python tests\test_winmd.py
#>
[CmdletBinding()]
param(
    [string]$PackageDirectory = '.packages',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# The target directory names are kept as they are; the package ids differ
# slightly (Contract vs Contracts).
$packages = @(
    [pscustomobject]@{
        Id         = 'Microsoft.Windows.SDK.Contracts'
        Version    = $null
        Prerelease = $false
        Source     = 'ref\netstandard2.0'
        Target     = 'metadata\Microsoft.Windows.SDK.Contract'
        Marker     = 'Windows.Foundation.FoundationContract.winmd'
    }
    [pscustomobject]@{
        Id         = 'Microsoft.Windows.SDK.Win32Metadata'
        Version    = $null
        Prerelease = $true              # only published as a preview package
        Source     = '.'
        Target     = 'metadata\Microsoft.Windows.SDK.Win32Metadata'
        Marker     = 'Windows.Win32.winmd'
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
    if (-not $Force -and (Test-Path (Join-Path $package.Target $package.Marker))) {
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
    New-Item -ItemType Directory -Force $package.Target | Out-Null

    $files = Get-ChildItem $source -Filter '*.winmd' -File
    if (-not $files) {
        throw "no .winmd files found in $source"
    }
    $files | Copy-Item -Destination $package.Target -Force

    if (-not (Test-Path (Join-Path $package.Target $package.Marker))) {
        throw "$($package.Marker) is missing from $($package.Target)"
    }
    Write-Host ("    {0} files -> {1}" -f $files.Count, $package.Target)
}

Write-Host ''
$total = (Get-ChildItem metadata -Recurse -Filter *.winmd -ErrorAction SilentlyContinue).Count
Write-Host "$total .winmd files in metadata" -ForegroundColor Green
