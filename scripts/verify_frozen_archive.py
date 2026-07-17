from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path


REQUIRED_MODULES = (
    "app_icon",
    "app_config",
    "app_i18n",
    "storage",
    "views.main_window_layout",
)


def missing_required_modules(
    contents: Iterable[str],
    required: Sequence[str] = REQUIRED_MODULES,
) -> tuple[str, ...]:
    available = set(contents)
    return tuple(module for module in required if module not in available)


def verify_frozen_archive(archive_path: Path) -> tuple[str, ...]:
    from PyInstaller.archive.readers import pkg_archive_contents

    return missing_required_modules(pkg_archive_contents(str(archive_path)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify that a PyInstaller executable contains QRC modules."
    )
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)

    archive_path = args.archive.resolve()
    if not archive_path.is_file():
        parser.error(f"archive does not exist: {archive_path}")

    missing = verify_frozen_archive(archive_path)
    if missing:
        print(f"Frozen archive is missing required modules: {', '.join(missing)}")
        return 1

    print(f"Frozen archive verification passed: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
