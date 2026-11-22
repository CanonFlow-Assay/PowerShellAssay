"""Install the pinned native archive into an ignored Linux x86-64 tool directory."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def verified(path, release):
    if not path.is_file() or path.stat().st_size != release["size"]:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == release["sha256"]


def install(output, archives, release):
    filename = release["archive"]
    archive = archives / filename
    if not archive.exists():
        with tempfile.TemporaryDirectory(dir=archives, prefix="download-") as directory:
            fetched = Path(directory) / filename
            with urllib.request.urlopen(release["url"], timeout=30) as response, fetched.open("wb") as stream:
                # Read only the declared size plus one detection byte.
                remaining = release["size"] + 1
                while remaining:
                    chunk = response.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    stream.write(chunk)
                    remaining -= len(chunk)
            if not verified(fetched, release):
                raise ValueError(f"{filename}: download identity mismatch")
            fetched.replace(archive)
    if not verified(archive, release):
        raise ValueError(f"{filename}: cached archive identity mismatch")

    target = output / release["sha256"][:16]
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=output, prefix="extract-") as directory:
            expanded = Path(directory) / "asset"
            expanded.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(expanded, filter="data")
            entry = expanded / release["binary"]
            entry.chmod(entry.stat().st_mode | 0o100)
            expanded.replace(target)

    binaries = output / "bin"
    binaries.mkdir(exist_ok=True)
    command = binaries / release["command"]
    entry = target / release["binary"]
    if not command.is_symlink():
        command.symlink_to(Path("..") / entry.relative_to(output))
    if command.resolve() != entry.resolve() or not entry.is_file():
        raise ValueError(f"{command.name}: native tool path mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, help="optional directory of pinned upstream archives")
    options = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("bootstrap is qualified on Linux x86-64")
    output = ROOT / "artifacts" / "toolchain"
    output.mkdir(parents=True, exist_ok=True)
    archives = options.archives or output / "archives"
    archives.mkdir(parents=True, exist_ok=True)
    for release in json.loads((ROOT / "toolchain.json").read_text())["assets"]:
        install(output, archives, release)
    print(output / "bin")


if __name__ == "__main__":
    main()
