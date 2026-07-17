from __future__ import annotations

from scripts.verify_frozen_archive import missing_required_modules


def test_frozen_archive_requires_local_application_modules():
    contents = {
        "app_icon",
        "app_config",
        "app_i18n",
        "storage",
        "views.main_window_layout",
    }

    assert missing_required_modules(contents) == ()
    assert missing_required_modules(contents - {"app_icon"}) == ("app_icon",)
