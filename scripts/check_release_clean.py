from __future__ import annotations

import argparse
import re
from pathlib import Path


EXCLUDED_DIRECTORY_NAMES = {
    ".agents",
    ".scratch",
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
PUBLIC_REPORT_NAMES = {"clean_release_report.json", "clean_release_report.md"}
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]"),
    re.compile(r"(?i)(?:^|[\s\"'])/(?:mnt/data|home|Users)/"),
)


def contamination_reason(relative_path: Path) -> str | None:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if parts[:2] == ("docs", "agents"):
        return "local agent workflow directory"
    if any(part in EXCLUDED_DIRECTORY_NAMES_CASEFOLDED for part in parts):
        return "excluded runtime, backup, or nested distribution directory"
    if any(part.startswith(".pytest_tmp") for part in parts):
        return "pytest temporary directory"
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
    if name == ".env" or (name.startswith(".env.") and name not in {".env.example", ".env.template"}):
        return "private environment configuration"
    if name in {"theme_settings.json", "app_settings.json"}:
        return "local settings file"
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


def public_report_content_reason(path: Path) -> str | None:
    if path.name.casefold() not in PUBLIC_REPORT_NAMES:
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "public clean release report is not readable UTF-8 text"
    if any(pattern.search(content) for pattern in ABSOLUTE_PATH_PATTERNS):
        return "public clean release report contains an absolute path"
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
            continue
        if path.is_file():
            report_reason = public_report_content_reason(path)
            if report_reason:
                contamination.append((relative_path.as_posix(), report_reason))
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
