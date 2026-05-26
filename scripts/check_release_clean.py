from __future__ import annotations

import argparse
from pathlib import Path


EXCLUDED_DIRECTORY_NAMES = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".codex_pytest_tmp",
    "Backup",
    ".codex-backups",
    "backup_old",
    "performance_reports",
    "dist",
}
EXCLUDED_DIRECTORY_NAMES_CASEFOLDED = {name.casefold() for name in EXCLUDED_DIRECTORY_NAMES}


def contamination_reason(relative_path: Path) -> str | None:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if any(part in EXCLUDED_DIRECTORY_NAMES_CASEFOLDED for part in parts):
        return "excluded runtime, backup, or nested distribution directory"
    if any(parts[index : index + 2] == ("data", "cache") for index in range(len(parts) - 1)):
        return "runtime data cache directory"
    if any(parts[index : index + 2] == ("data", "exports") for index in range(len(parts) - 1)):
        return "local export directory"
    if "cache" in parts:
        return "cache directory"
    posix = relative_path.as_posix().casefold()
    if posix in {
        "quant_collector_app/data/theme_settings.json",
        "quant_collector_app/data/app_settings.json",
    }:
        return "local settings file"
    name = relative_path.name.casefold()
    if name.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite-shm")):
        return "local SQLite database"
    if name.endswith((".pyc", ".pyo")):
        return "compiled Python file"
    if name.endswith(".zip"):
        return "archive file"
    if name.endswith(".log"):
        return "runtime log file"
    if "logs" in parts:
        return "runtime log directory"
    return None


def inspect_release(directory: Path) -> list[tuple[str, str]]:
    root = Path(directory)
    if not root.is_dir():
        return [(str(root), "release directory does not exist")]
    contamination: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        reason = contamination_reason(relative_path)
        if reason:
            contamination.append((relative_path.as_posix(), reason))
    return contamination


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject a Quant Replay Collector release containing local runtime data.")
    parser.add_argument("directory", type=Path, help="Release directory to inspect.")
    args = parser.parse_args()
    contamination = inspect_release(args.directory)
    if contamination:
        print("Release clean check failed.")
        for path, reason in contamination:
            print(f"- {path}: {reason}")
        return 1
    print("Release clean check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
