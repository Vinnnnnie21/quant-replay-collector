from __future__ import annotations

import logging

from error_boundary import run_user_action
from errors import DataLoadError


def test_error_boundary_preserves_user_message(caplog):
    with caplog.at_level(logging.WARNING):
        result, message = run_user_action(
            lambda: (_ for _ in ()).throw(DataLoadError("Cache is unreadable.")),
            logger=logging.getLogger("test.error_boundary"),
            fallback_message="Load failed.",
        )

    assert result is None
    assert message == "Cache is unreadable."
    assert "Cache is unreadable." in caplog.text


def test_error_boundary_hides_internal_exception_details(caplog):
    with caplog.at_level(logging.ERROR):
        result, message = run_user_action(
            lambda: (_ for _ in ()).throw(ValueError("private detail")),
            logger=logging.getLogger("test.error_boundary"),
            fallback_message="Operation failed.",
        )

    assert result is None
    assert message == "Operation failed."
    assert "private detail" in caplog.text
