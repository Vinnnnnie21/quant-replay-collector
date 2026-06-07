from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "QuantReplayCollector-v1.4.1-Clean"
PROJECT_NAME = "Quant Replay Collector"
RELEASE_VERSION = "v1.4.1"
ROOT_CONTENT = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "pytest.ini",
    "docs",
    "quant_collector_app",
    "tests",
    "requirements.txt",
    "start.bat",
    "run_app.py",
)
EXCLUDED_DIR_NAMES = {
    ".agents",
    ".scratch",
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
LOCAL_AGENT_PREFIXES = {
    (".agents",),
    (".scratch",),
    ("docs", "agents"),
}


def excluded_reason(relative_path: Path) -> str | None:
    parts = tuple(part.casefold() for part in relative_path.parts)
    name = relative_path.name.casefold()
    suffix = relative_path.suffix.casefold()
    if any(parts[: len(prefix)] == prefix for prefix in LOCAL_AGENT_PREFIXES):
        return "local_agent_files"
    if any(part in {".venv", "venv"} for part in parts):
        return "private_environment"
    if "__pycache__" in parts or suffix in {".pyc", ".pyo"}:
        return "python_cache"
    if ".pytest_cache" in parts:
        return "cache"
    if any(
        part in {".codex-backups", "backup", "backup_old", "build", "dist", "performance_reports"}
        for part in parts
    ):
        return "build_artifacts"
    if len(parts) >= 3 and parts[:3] in {
        ("quant_collector_app", "data", "cache"),
        ("quant_collector_app", "data", "exports"),
    }:
        return "runtime_data"
    if len(parts) >= 3 and parts[:2] == ("quant_collector_app", "data"):
        if name.endswith((".db", ".db-wal", ".db-shm")):
            return "local_database"
        if name in {"theme_settings.json", "app_settings.json"}:
            return "local_settings"
    if len(parts) >= 3 and parts[:2] == ("quant_collector_app", "logs"):
        return "logs"
    if name == ".env" or (name.startswith(".env.") and name not in {".env.example", ".env.template"}):
        return "private_environment"
    if name in {"theme_settings.json", "app_settings.json"}:
        return "local_settings"
    if name.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal", ".sqlite-shm")):
        return "local_database"
    if suffix == ".log":
        return "logs"
    if suffix == ".zip":
        return "build_artifacts"
    return None


def build_release(
    output_dir: Path,
    source_root: Path = REPO_ROOT,
    *,
    include_private_report: bool = False,
) -> dict:
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

    skipped_count_by_reason = dict(sorted(Counter(row["reason"] for row in skipped).items()))
    report = {
        "project": PROJECT_NAME,
        "version": RELEASE_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "included_roots": list(ROOT_CONTENT),
        "excluded_directory_names": sorted(EXCLUDED_DIR_NAMES),
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "copied_file_count": len(copied),
        "skipped_file_count": len(skipped),
        "skipped_count_by_reason": skipped_count_by_reason,
        "public_report": not include_private_report,
        "notes": [
            "Local absolute paths and skipped file names are omitted from the public report.",
            "Runtime data, caches, logs, databases and local agent files are excluded.",
        ],
        "missing_optional_root_items": missing,
    }
    if include_private_report:
        report.update(
            {
                "source_root": str(source_root),
                "output_dir": str(output_dir),
                "copied_files": sorted(copied),
                "skipped_files": sorted(skipped, key=lambda row: row["path"]),
            }
        )
    (output_dir / "clean_release_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_lines = [
        "# Clean Release Report",
        "",
        f"- Created at: `{report['created_at']}`",
        f"- Project: {report['project']}",
        f"- Version: `{report['version']}`",
        f"- Public report: `{report['public_report']}`",
        f"- Copied files: {report['copied_file_count']}",
        f"- Skipped runtime/local files: {report['skipped_file_count']}",
        "",
        "Local absolute paths and skipped file names are omitted from the public report.",
        "",
        "## Skipped Counts By Reason",
        "",
    ]
    report_lines.extend(
        f"- `{reason}`: {count}" for reason, count in report["skipped_count_by_reason"].items()
    )
    if not report["skipped_count_by_reason"]:
        report_lines.append("- None found in copied source roots.")
    if include_private_report:
        report_lines.extend(
            [
                "",
                "## Private Build Details",
                "",
                f"- Source: `{report['source_root']}`",
                f"- Output: `{report['output_dir']}`",
                "",
                "### Skipped Files",
                "",
            ]
        )
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
    parser.add_argument(
        "--include-private-report",
        action="store_true",
        help="Include local absolute paths and per-file details. Do not publish this report.",
    )
    args = parser.parse_args()
    report = build_release(args.output, include_private_report=args.include_private_report)
    print(f"Clean release written to: {args.output.resolve()}")
    print(f"Copied files: {report['copied_file_count']}")
    print(f"Skipped local/runtime files: {report['skipped_file_count']}")
    print("Reports: clean_release_report.json, clean_release_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
