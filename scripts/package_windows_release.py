from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_collector_app.release_metadata import WINDOWS_PACKAGE_BASENAME
from quant_collector_app.version import __version__


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _reject_link_like_entries(root: Path) -> None:
    for path in root.rglob("*"):
        if _is_link_like(path):
            raise ValueError(
                f"release package contains a symbolic link or junction: "
                f"{path.relative_to(root).as_posix()}"
            )


def _validated_manifest(package_root: Path) -> dict:
    _reject_link_like_entries(package_root)
    manifest_path = package_root / "release-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("release manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("application_version") != __version__:
        raise ValueError("release manifest application version does not match")
    if manifest.get("package_format") != "onedir":
        raise ValueError("Windows release package must use onedir format")
    if manifest.get("native_launch_verified") is not True:
        raise ValueError("native launch verification has not passed")
    entrypoint = (package_root / str(manifest.get("entrypoint", ""))).resolve()
    try:
        entrypoint.relative_to(package_root)
    except ValueError as exc:
        raise ValueError("release entrypoint escapes the package root") from exc
    if not entrypoint.is_file():
        raise ValueError("release entrypoint is missing")
    if _sha256(entrypoint) != str(manifest.get("entrypoint_sha256", "")):
        raise ValueError("release entrypoint hash does not match the manifest")
    return manifest


def package_windows_release(
    package_root: str | Path,
    output_dir: str | Path,
) -> Path:
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError("Windows onedir package root does not exist")
    _validated_manifest(root)

    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{WINDOWS_PACKAGE_BASENAME}.zip"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp.zip",
        dir=output_root,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                archive.write(
                    path,
                    arcname=f"{WINDOWS_PACKAGE_BASENAME}/{relative}",
                )
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and atomically package the formal QRC Windows release.",
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    archive = package_windows_release(args.root, args.output_dir)
    print(f"Archive={archive}")
    print(f"SizeBytes={archive.stat().st_size}")
    print(f"Sha256={_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
