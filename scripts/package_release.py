"""Package only reviewed runtime inputs; never include developer environment files."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", "tests", ".DS_Store", ".next/cache"}


def include(path):
    return not any(part in EXCLUDED or part.startswith(".env") for part in path.parts)


def add_tree(archive, source, prefix=""):
    if not source.exists():
        raise SystemExit(f"Missing release input: {source.name}")
    paths = [source] if source.is_file() else sorted(source.rglob("*"))
    for path in paths:
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        if path.is_file() and include(relative):
            archive.write(path, str(Path(prefix) / relative))


def package(part, output):
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{part}.zip"
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        if part == "backend":
            for name in (
                "app",
                "alembic",
                "alembic.ini",
                "requirements.txt",
                "startup.sh",
            ):
                add_tree(
                    archive,
                    ROOT / "backend" / name,
                    name if (ROOT / "backend" / name).is_dir() else "",
                )
        else:
            standalone = ROOT / "frontend/.next/standalone"
            if not (standalone / "server.js").exists():
                raise SystemExit("Run npm run build in frontend before packaging")
            add_tree(archive, standalone)
            add_tree(archive, ROOT / "frontend/.next/static", ".next/static")
            add_tree(archive, ROOT / "frontend/public", "public")
    with ZipFile(target) as archive:
        if any(not include(Path(name)) for name in archive.namelist()):
            raise SystemExit("Private file found in release archive")
        if archive.testzip() is not None:
            raise SystemExit("Release ZIP verification failed")
    return {
        "file": target.name,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "bytes": target.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "part", choices=["backend", "frontend", "all"], default="all", nargs="?"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".release")
    args = parser.parse_args()
    parts = ["backend", "frontend"] if args.part == "all" else [args.part]
    result = [package(part, args.output) for part in parts]
    (args.output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
