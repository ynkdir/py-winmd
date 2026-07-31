#!/usr/bin/env python3
"""Downloads the .winmd files the tests and the examples read.

The metadata is not part of this repository; it is published on nuget.org:

    metadata/Microsoft.Windows.SDK.Contract       WinRT contracts (Windows SDK)
    metadata/Microsoft.Windows.SDK.Win32Metadata  Win32 API metadata

A NuGet package is a zip, so nothing but the standard library is needed: the
version is read from the flat container index, the package is downloaded to a
temporary file and the .winmd files are taken out of it. Nothing else is kept.

`--headers` fetches one more thing, which only the tests want: the C++ reader
this library was written from and is checked against, Microsoft.Windows.WinMD,
into .winmd-headers/. Nothing else needs a compiler.

    python fetch-metadata.py
    python fetch-metadata.py --headers          # and the C++ reader, for tests
    python fetch-metadata.py --force            # refresh what is already there
    python fetch-metadata.py --directory other  # somewhere else than metadata/
"""

import argparse
import json
import posixpath
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple

FLAT_CONTAINER = "https://api.nuget.org/v3-flatcontainer"


class Package(NamedTuple):
    id: str
    prerelease: bool  # whether the package is only published as a preview
    source: str       # the directory inside the package the .winmd files are in
    target: str       # the directory below --directory they are copied to
    marker: str       # one file that has to be there afterwards


PACKAGES = [
    Package(
        id="Microsoft.Windows.SDK.Contracts",
        prerelease=False,
        source="ref/netstandard2.0",
        target="Microsoft.Windows.SDK.Contract",
        marker="Windows.Foundation.FoundationContract.winmd",
    ),
    Package(
        id="Microsoft.Windows.SDK.Win32Metadata",
        prerelease=True,
        source="",
        target="Microsoft.Windows.SDK.Win32Metadata",
        marker="Windows.Win32.winmd",
    ),
]


def version_key(version):
    """Orders versions the way NuGet does: 1.0.10 after 1.0.9, previews first."""
    release, _, preview = version.partition("-")
    numbers = tuple(int(part) if part.isdigit() else 0 for part in release.split("."))
    return (numbers, bool(not preview), preview)


def latest_version(package):
    """The newest version of the package, from the flat container index."""
    url = f"{FLAT_CONTAINER}/{package.id.lower()}/index.json"
    with urllib.request.urlopen(url) as response:
        versions = json.load(response)["versions"]
    if not package.prerelease:
        versions = [version for version in versions if "-" not in version]
    if not versions:
        raise SystemExit(f"no version of {package.id} found at {url}")
    return max(versions, key=version_key)


def download(url, path):
    with urllib.request.urlopen(url) as response, open(path, "wb") as file:
        shutil.copyfileobj(response, file)


def extract(archive_path, package, target):
    """Copies the .winmd files out of the package, and says how many."""
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".winmd"):
                continue
            if posixpath.dirname(name) != package.source:
                continue
            with archive.open(name) as source, open(target / posixpath.basename(name), "wb") as file:
                shutil.copyfileobj(source, file)
            count += 1
    return count


def fetch(package, directory, force):
    target = directory / package.target
    if not force and (target / package.marker).exists():
        print(f"==> {target} already present, skipping (use --force to refresh)")
        return

    version = latest_version(package)
    name = f"{package.id.lower()}.{version}.nupkg"
    print(f"==> installing {package.id} {version}")

    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir, name)
        download(f"{FLAT_CONTAINER}/{package.id.lower()}/{version}/{name}", archive)
        count = extract(archive, package, target)

    if not (target / package.marker).exists():
        raise SystemExit(f"{package.marker} is missing from {target}")
    print(f"    {count} files -> {target}")


def fetch_headers(directory, force):
    """The C++ reader, which tests/test_reference.py builds and compares against."""
    if not force and (directory / "winmd_reader.h").exists():
        print(f"==> {directory} already present, skipping (use --force to refresh)")
        return

    package = "Microsoft.Windows.WinMD"
    version = latest_version(Package(package, False, "", "", ""))
    name = f"{package.lower()}.{version}.nupkg"
    print(f"==> installing {package} {version}")

    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        archive = Path(workdir, name)
        download(f"{FLAT_CONTAINER}/{package.lower()}/{version}/{name}", archive)
        count = 0
        with zipfile.ZipFile(archive) as zip:
            for member in zip.namelist():
                if not member.endswith(".h"):
                    continue
                target = directory / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip.open(member) as source, open(target, "wb") as file:
                    shutil.copyfileobj(source, file)
                count += 1

    if not (directory / "winmd_reader.h").exists():
        raise SystemExit(f"winmd_reader.h is missing from {directory}")
    print(f"    {count} headers -> {directory}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", default="metadata", type=Path,
                        help="where the .winmd files go (default: metadata)")
    parser.add_argument("--headers", action="store_true",
                        help="also fetch the C++ reader the tests check against")
    parser.add_argument("--header-directory", default=".winmd-headers", type=Path,
                        help="where those headers go (default: .winmd-headers)")
    parser.add_argument("--force", action="store_true",
                        help="download again even when the files are already there")
    arguments = parser.parse_args(argv)

    for package in PACKAGES:
        fetch(package, arguments.directory, arguments.force)

    if arguments.headers:
        fetch_headers(arguments.header_directory, arguments.force)

    # Windows.WinMD is spelled with a capital MD, so this cannot be a glob.
    total = sum(1 for path in arguments.directory.rglob("*") if path.suffix.lower() == ".winmd")
    print(f"\n{total} .winmd files in {arguments.directory}")


if __name__ == "__main__":
    sys.exit(main())
