from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_collector_app.release_metadata import (
    WINDOWS_FILE_VERSION,
    WINDOWS_PACKAGE_BASENAME,
)
from quant_collector_app.version import __version__


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _version_tuple() -> tuple[int, int, int, int]:
    return tuple(int(part) for part in WINDOWS_FILE_VERSION.split("."))  # type: ignore[return-value]


def render_version_file() -> str:
    version_tuple = _version_tuple()
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Quant Replay Collector'),
        StringStruct('FileDescription', 'Quant Replay Collector'),
        StringStruct('FileVersion', '{WINDOWS_FILE_VERSION}'),
        StringStruct('InternalName', 'QRC'),
        StringStruct('OriginalFilename', 'QRC.exe'),
        StringStruct('ProductName', 'Quant Replay Collector'),
        StringStruct('ProductVersion', '{__version__}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def render_batch_environment() -> str:
    return (
        f'@set "QRC_VERSION={__version__}"\n'
        f'@set "QRC_WINDOWS_FILE_VERSION={WINDOWS_FILE_VERSION}"\n'
        f'@set "QRC_PACKAGE_NAME={WINDOWS_PACKAGE_BASENAME}"\n'
    )


def write_windows_build_metadata(*, version_file: Path, batch_file: Path) -> None:
    _atomic_write_text(version_file, render_version_file())
    _atomic_write_text(batch_file, render_batch_environment())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Windows file-version and batch release metadata.",
    )
    parser.add_argument("--version-file", required=True, type=Path)
    parser.add_argument("--batch-file", required=True, type=Path)
    args = parser.parse_args(argv)
    write_windows_build_metadata(
        version_file=args.version_file.resolve(),
        batch_file=args.batch_file.resolve(),
    )
    print(f"Version={__version__}")
    print(f"WindowsFileVersion={WINDOWS_FILE_VERSION}")
    print(f"PackageName={WINDOWS_PACKAGE_BASENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
