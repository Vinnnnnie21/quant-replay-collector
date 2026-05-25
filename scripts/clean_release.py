from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "QuantReplayCollector-v1.2"
ROOT_CONTENT = (
    "README.md",
    "LICENSE",
    "docs",
    "quant_collector_app",
    "tests",
    "requirements.txt",
    "start.bat",
    "run_app.py",
)
EXCLUDED_DIR_NAMES = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".codex-backups",
    "Backup",
    "backup_old",
    "build",
    "dist",
    "performance_reports",
    "venv",
}


def excluded_reason(relative_path: Path) -> str | None:
    parts = relative_path.parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return "temporary or backup directory"
    if len(parts) >= 3 and parts[:3] in {
        ("quant_collector_app", "data", "cache"),
        ("quant_collector_app", "data", "exports"),
    }:
        return "runtime data directory"
    if len(parts) >= 3 and parts[:2] == ("quant_collector_app", "data"):
        name = parts[-1]
        if name.endswith((".db", ".db-wal", ".db-shm")):
            return "local database"
        if name in {"theme_settings.json", "app_settings.json"}:
            return "local settings"
    if len(parts) >= 3 and parts[:2] == ("quant_collector_app", "logs"):
        return "runtime log directory"
    if relative_path.suffix in {".pyc", ".pyo"}:
        return "compiled Python file"
    return None


def build_release(output_dir: Path, source_root: Path = REPO_ROOT) -> dict:
    output_dir = output_dir.resolve()
    source_root = source_root.resolve()
    if output_dir == source_root or output_dir in source_root.parents:
        raise ValueError("Output directory must not replace or contain the source repository.")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    copied: list[str] = []
    skipped: list[dict[str, str]] = []
    missing: list[str] = []
    for item_name in ROOT_CONTENT:
        source = source_root / item_name
        if not source.exists():
            missing.append(item_name)
            continue
        candidates = [source] if source.is_file() else [p for p in source.rglob("*") if p.is_file()]
        for candidate in candidates:
            relative_path = candidate.relative_to(source_root)
            reason = excluded_reason(relative_path)
            if reason:
                skipped.append({"path": str(relative_path), "reason": reason})
                continue
            target = output_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
            copied.append(str(relative_path))

    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "included_roots": list(ROOT_CONTENT),
        "excluded_directory_names": sorted(EXCLUDED_DIR_NAMES),
        "copied_file_count": len(copied),
        "skipped_file_count": len(skipped),
        "copied_files": sorted(copied),
        "skipped_files": sorted(skipped, key=lambda row: row["path"]),
        "missing_optional_root_items": missing,
    }
    (output_dir / "clean_release_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_lines = [
        "# Clean Release Report",
        "",
        f"- Created at: `{report['created_at']}`",
        f"- Source: `{report['source_root']}`",
        f"- Output: `{report['output_dir']}`",
        f"- Copied files: {report['copied_file_count']}",
        f"- Skipped runtime/local files: {report['skipped_file_count']}",
        "",
        "## Excluded Directory Names",
        "",
        *[f"- `{name}`" for name in report["excluded_directory_names"]],
        "",
        "## Skipped Files",
        "",
    ]
    report_lines.extend(
        f"- `{row['path']}`: {row['reason']}" for row in report["skipped_files"]
    )
    if not report["skipped_files"]:
        report_lines.append("- None found in copied source roots.")
    (output_dir / "clean_release_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean Quant Replay Collector release directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory.")
    args = parser.parse_args()
    report = build_release(args.output)
    print(f"Clean release written to: {report['output_dir']}")
    print(f"Copied files: {report['copied_file_count']}")
    print(f"Skipped local/runtime files: {report['skipped_file_count']}")
    print("Reports: clean_release_report.json, clean_release_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
