<#
.SYNOPSIS
    Downloads the NuGet packages this project builds on and tests against.

.DESCRIPTION
    Neither the C++ library that is wrapped nor the .winmd test data are part
    of this repository. This script installs them with nuget.exe:

        winmd\                                        Microsoft.Windows.WinMD (C++ headers)
        metadata\Microsoft.Windows.SDK.Contract       WinRT contracts (Windows SDK)
        metadata\Microsoft.Windows.SDK.Win32Metadata  Win32 API metadata

    nuget.exe is taken from PATH; if it is not installed it is downloaded to
    .tools\nuget.exe.

.PARAMETER Kind
    'library' fetches only the C++ headers needed to build, 'metadata' only the
    .winmd files needed by the tests and examples. Defaults to both.

.PARAMETER Force
    Re-copy the files even when the target directory is already populated.

.EXAMPLE
    .\fetch-packages.ps1
    .\.venv\Scripts\Activate.ps1
    python tests\test_winmd.py
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'library', 'metadata')]
    [string]$Kind = 'all',
    [string]$PackageDirectory = '.packages',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# The target directory names are kept as they are; the package ids differ
# slightly (Contract vs Contracts).
$packages = @(
    [pscustomobject]@{
        Kind       = 'library'
        Id         = 'Microsoft.Windows.WinMD'
        Version    = $null              # latest stable
        Prerelease = $false
        Source     = '.'
        Target     = 'winmd'
        Recurse    = $true              # the whole header tree
        Include    = '*'
        Exclude    = @('*.nupkg', '.signature.p7s')
        Marker     = 'winmd_reader.h'
    }
    [pscustomobject]@{
        Kind       = 'metadata'
        Id         = 'Microsoft.Windows.SDK.Contracts'
        Version    = $null
        Prerelease = $false
        Source     = 'ref\netstandard2.0'
        Target     = 'metadata\Microsoft.Windows.SDK.Contract'
        Recurse    = $false
        Include    = '*.winmd'
        Exclude    = @()
        Marker     = 'Windows.Foundation.FoundationContract.winmd'
    }
    [pscustomobject]@{
        Kind       = 'metadata'
        Id         = 'Microsoft.Windows.SDK.Win32Metadata'
        Version    = $null
        Prerelease = $true              # only published as a preview package
        Source     = '.'
        Target     = 'metadata\Microsoft.Windows.SDK.Win32Metadata'
        Recurse    = $false
        Include    = '*.winmd'
        Exclude    = @()
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
    if ($Kind -ne 'all' -and $Kind -ne $package.Kind) {
        continue
    }

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

    if ($package.Recurse) {
        Copy-Item -Path (Join-Path $source '*') -Destination $package.Target -Recurse -Force `
            -Exclude $package.Exclude
        $count = (Get-ChildItem $package.Target -Recurse -File).Count
    }
    else {
        $files = Get-ChildItem $source -Filter $package.Include -File
        if (-not $files) {
            throw "no $($package.Include) files found in $source"
        }
        $files | Copy-Item -Destination $package.Target -Force
        $count = $files.Count
    }

    if (-not (Test-Path (Join-Path $package.Target $package.Marker))) {
        throw "$($package.Marker) is missing from $($package.Target)"
    }
    Write-Host ("    {0} files -> {1}" -f $count, $package.Target)
}

Write-Host ''
if ($Kind -ne 'metadata') {
    Write-Host ("winmd headers: {0}" -f (Test-Path 'winmd\winmd_reader.h')) -ForegroundColor Green
}
if ($Kind -ne 'library') {
    $total = (Get-ChildItem metadata -Recurse -Filter *.winmd -ErrorAction SilentlyContinue).Count
    Write-Host "$total .winmd files in metadata" -ForegroundColor Green
}
