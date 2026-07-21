from __future__ import annotations

from pathlib import Path

import pytest

from services.export_service import build_export_task_request


def test_build_export_task_request_normalizes_worker_payload(tmp_path):
    request = build_export_task_request(
        target=tmp_path / "exports",
        session_id="sess_1",
        language="en_US",
        selected_label="fwd_ret_5_side_adj",
    )

    assert request.target == tmp_path / "exports"
    assert request.session_id == "sess_1"
    assert request.language == "en_US"
    assert request.selected_label == "fwd_ret_5_side_adj"


@pytest.mark.parametrize("language", [None, ""])
def test_build_export_task_request_defaults_language(tmp_path, language):
    request = build_export_task_request(
        target=tmp_path,
        session_id="sess_1",
        language=language,
        selected_label="fwd_ret_10_side_adj",
    )

    assert request.language == "zh_CN"


@pytest.mark.parametrize("selected_label", [None, ""])
def test_build_export_task_request_defaults_selected_label(tmp_path, selected_label):
    request = build_export_task_request(
        target=tmp_path,
        session_id="sess_1",
        language="zh_CN",
        selected_label=selected_label,
    )

    assert request.selected_label == "fwd_ret_10_side_adj"


def test_build_export_task_request_requires_session_id(tmp_path):
    with pytest.raises(ValueError, match="session_id"):
        build_export_task_request(
            target=tmp_path,
            session_id="",
            language="zh_CN",
            selected_label="fwd_ret_10_side_adj",
        )


def test_build_export_task_request_accepts_string_target(tmp_path):
    request = build_export_task_request(
        target=str(tmp_path),
        session_id="sess_1",
        language="zh_CN",
        selected_label="fwd_ret_10_side_adj",
    )

    assert isinstance(request.target, Path)
    assert request.target == tmp_path
