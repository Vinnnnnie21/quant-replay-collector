from __future__ import annotations

import json

import pytest

from scripts.check_release_clean import inspect_release


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/agents/domain.md",
        ".scratch/task.md",
        ".agents/skills/local/SKILL.md",
    ],
)
def test_release_checker_rejects_local_agent_workflow_files(tmp_path, relative_path):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("local workflow\n", encoding="utf-8")

    findings = inspect_release(tmp_path)

    assert any(found_path == relative_path for found_path, _reason in findings)


@pytest.mark.parametrize("private_path", [r"D:\Trading", r"C:\Users\person\repo", "/mnt/data/repo", "/home/user/repo", "/Users/name/repo"])
def test_release_checker_rejects_absolute_paths_in_public_report(tmp_path, private_path):
    report_path = tmp_path / "clean_release_report.json"
    report_path.write_text(json.dumps({"source_root": private_path}), encoding="utf-8")

    findings = inspect_release(tmp_path)

    assert any(path == "clean_release_report.json" and "absolute path" in reason for path, reason in findings)
