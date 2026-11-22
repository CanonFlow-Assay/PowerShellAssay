"""Build an independent, deterministic zipapp from the versioned producer files."""

import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package():
    package_dir, = (path for path in (ROOT / "src").iterdir() if path.is_dir() and path.name != "__pycache__")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    archive = artifacts / f"{package_dir.name}.pyz"
    manifest = {
        path.relative_to(ROOT / "src").as_posix(): path.read_bytes()
        for path in package_dir.iterdir() if path.suffix in {".py", ".json", ".ps1"}
    }
    manifest["__main__.py"] = (
        f"from {package_dir.name}.engine import main\nraise SystemExit(main())\n".encode()
    )
    for name in ("LICENSE", "NOTICE"):
        manifest[name] = (ROOT / name).read_bytes()

    with zipfile.ZipFile(archive, "w") as output:
        for name, data in sorted(manifest.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 22, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(entry, data)

    return archive


if __name__ == "__main__":
    result = package()
    print(result)
    print(hashlib.sha256(result.read_bytes()).hexdigest())
