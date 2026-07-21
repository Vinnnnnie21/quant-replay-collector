from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_collector_app.app_config import APP_NAME, APP_VERSION
from quant_collector_app.storage import StorageManager
from PySide6.QtCore import qVersion


MANIFEST_NAME = "release-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else "unavailable"


def _git_worktree_dirty() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # A missing/unreadable repository must never be reported as clean.
    return completed.returncode != 0 or bool(completed.stdout.strip())


def write_release_manifest(
    package_root: str | Path,
    entrypoint: str | Path,
    *,
    output_name: str = MANIFEST_NAME,
    native_launch_verified: bool = False,
    native_launch_verified_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError(f"release package root is not a directory: {root}")
    selected = Path(entrypoint)
    executable = (
        selected.resolve() if selected.is_absolute() else (root / selected).resolve()
    )
    try:
        entrypoint_relative = executable.relative_to(root)
    except ValueError as exc:
        raise ValueError("release entrypoint must be inside the package root") from exc
    if not executable.is_file():
        raise ValueError(f"release entrypoint does not exist: {executable}")

    output = root / output_name
    file_rows = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if _is_link_like(path):
            raise ValueError(
                f"release package contains a symbolic link or junction: "
                f"{path.relative_to(root).as_posix()}"
            )
        if not path.is_file() or path.resolve() == output.resolve():
            continue
        file_rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not file_rows:
        raise ValueError("release package contains no files")
    content_bytes = json.dumps(
        file_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    entrypoint_key = entrypoint_relative.as_posix()
    entrypoint_row = next(
        (row for row in file_rows if row["path"] == entrypoint_key),
        None,
    )
    if entrypoint_row is None:
        raise ValueError("release entrypoint was not included in the package manifest")
    manifest = {
        "manifest_version": 1,
        "application_name": APP_NAME,
        "application_version": APP_VERSION,
        "database_schema_version": StorageManager.SCHEMA_VERSION,
        "package_format": "onedir",
        "build_time_utc": datetime.fromtimestamp(
            executable.stat().st_mtime,
            tz=UTC,
        ).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": _git_commit(),
        "git_worktree_dirty": _git_worktree_dirty(),
        "python_version": platform.python_version(),
        "qt_version": qVersion(),
        "native_launch_verified": bool(native_launch_verified),
        "native_launch_verified_at_utc": (
            native_launch_verified_at_utc
            if native_launch_verified
            else None
        ),
        "entrypoint": entrypoint_key,
        "entrypoint_sha256": entrypoint_row["sha256"],
        "release_content_sha256": hashlib.sha256(content_bytes).hexdigest(),
        "files": file_rows,
    }
    payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=root,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output)
    except BaseException:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        finally:
            raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a reproducible manifest for a QRC onedir package.",
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--entrypoint", default="QRC.exe")
    parser.add_argument(
        "--native-launch-verified",
        action="store_true",
        help="Mark the package after its native start/close gate succeeds.",
    )
    args = parser.parse_args(argv)
    verified_at = (
        datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        if args.native_launch_verified
        else None
    )
    manifest = write_release_manifest(
        args.root,
        args.entrypoint,
        native_launch_verified=args.native_launch_verified,
        native_launch_verified_at_utc=verified_at,
    )
    print(
        f"Manifest={Path(args.root).resolve() / MANIFEST_NAME}\n"
        f"Version={manifest['application_version']}\n"
        f"Schema={manifest['database_schema_version']}\n"
        f"ContentSha256={manifest['release_content_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
