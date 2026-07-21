"""Release names and Windows metadata derived from the canonical version."""

from __future__ import annotations

from .version import __version__


def _windows_file_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Windows release requires a three-part numeric version: {version}")
    return ".".join((*parts, "0"))


WINDOWS_FILE_VERSION = _windows_file_version(__version__)
WINDOWS_PACKAGE_BASENAME = f"QRC-v{__version__}-Windows-x64"


__all__ = ["WINDOWS_FILE_VERSION", "WINDOWS_PACKAGE_BASENAME"]
