from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import NamedTuple


ARTIFACT_DIRECTORY = ".test-artifacts"
KNOWN_CHILDREN = ("pytest-cache", "pytest-tmp", "v1.6.0")
KNOWN_CHILD_PREFIXES = ("pytest-tmp-run-",)


class CleanupReport(NamedTuple):
    planned: tuple[Path, ...]
    removed: tuple[Path, ...]
    failures: tuple[tuple[Path, str], ...]


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def cleanup_test_artifacts(
    workspace: str | Path,
    *,
    apply: bool = False,
) -> CleanupReport:
    """Plan or remove only children of the repository test-artifact root."""
    workspace_root = Path(workspace).resolve()
    artifact_root = workspace_root / ARTIFACT_DIRECTORY
    if artifact_root.parent != workspace_root:
        raise ValueError("test artifact root must be a direct workspace child")
    if not artifact_root.exists():
        return CleanupReport((), (), ())
    if not artifact_root.is_dir() or _is_link_like(artifact_root):
        raise ValueError("test artifact root must be a real directory")

    known = {artifact_root / name for name in KNOWN_CHILDREN}
    known.update(
        child
        for child in artifact_root.iterdir()
        if any(child.name.startswith(prefix) for prefix in KNOWN_CHILD_PREFIXES)
    )
    children = tuple(
        sorted(
            (path for path in known if path.exists()),
            key=lambda path: path.name,
        )
    )
    planned = tuple(path.relative_to(artifact_root) for path in children)
    if not apply:
        return CleanupReport(planned, (), ())

    resolved_root = artifact_root.resolve()
    removed: list[Path] = []
    failures: list[tuple[Path, str]] = []
    for child in children:
        relative = child.relative_to(artifact_root)
        if _is_link_like(child):
            failures.append(
                (relative, "symbolic links and junctions are not followed")
            )
            continue
        resolved_child = child.resolve()
        try:
            resolved_child.relative_to(resolved_root)
        except ValueError:
            failures.append((relative, "path escapes the artifact root"))
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError as exc:
            failures.append((relative, f"{type(exc).__name__}: {exc}"))
            continue
        removed.append(relative)
    return CleanupReport(planned, tuple(removed), tuple(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview or clean the repository-local pytest artifacts.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Repository root; defaults to the current directory.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the listed .test-artifacts children.",
    )
    args = parser.parse_args(argv)
    report = cleanup_test_artifacts(args.workspace, apply=args.apply)
    if not report.planned:
        print("No test artifacts found.")
        return 0
    if args.apply:
        for path in report.removed:
            print(f"removed: {ARTIFACT_DIRECTORY}/{path.as_posix()}")
        for path, error in report.failures:
            print(f"failed: {ARTIFACT_DIRECTORY}/{path.as_posix()}: {error}")
    else:
        for path in report.planned:
            print(f"would remove: {ARTIFACT_DIRECTORY}/{path.as_posix()}")
        print("Dry run only. Pass --apply to remove these paths.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
