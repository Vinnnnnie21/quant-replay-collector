from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PRUNED_RELATIVE_PATHS = (
    Path("_internal/pyarrow/tests"),
    Path("_internal/sklearn/datasets"),
)


def _is_link_like(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def prune_windows_package(package_root: str | Path) -> tuple[str, ...]:
    """Remove only dependency-owned tests and sample datasets from an onedir."""

    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError("Windows package root does not exist")
    removed: list[str] = []
    for relative in PRUNED_RELATIVE_PATHS:
        target = root / relative
        if not target.exists():
            continue
        if _is_link_like(target):
            raise ValueError(
                f"refusing to follow package symbolic link or junction: "
                f"{relative.as_posix()}"
            )
        resolved = target.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"package prune path escapes root: {relative.as_posix()}") from exc
        if not target.is_dir():
            raise ValueError(f"package prune target is not a directory: {relative.as_posix()}")
        shutil.rmtree(target)
        removed.append(relative.as_posix())
    return tuple(removed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove known dependency tests and sample data from a QRC onedir.",
    )
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    removed = prune_windows_package(args.root)
    for relative in removed:
        print(f"Pruned={relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
