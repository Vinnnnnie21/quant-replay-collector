from __future__ import annotations

from scripts.verify_frozen_archive import missing_required_modules


def test_frozen_archive_requires_local_application_modules():
    contents = {
        "app_icon",
        "app_config",
        "app_i18n",
        "research.entry_behavior_codec",
        "research.entry_behavior_model",
        "research.entry_behavior_training",
        "research.entry_behavior_validation",
        "services.entry_behavior_training",
        "sklearn",
        "storage",
        "views.main_window_layout",
    }

    assert missing_required_modules(contents) == ()
    assert missing_required_modules(contents - {"app_icon"}) == ("app_icon",)
    assert missing_required_modules(contents - {"sklearn"}) == ("sklearn",)
    assert missing_required_modules(
        contents - {"research.entry_behavior_model"}
    ) == ("research.entry_behavior_model",)
    assert missing_required_modules(
        contents - {"research.entry_behavior_training"}
    ) == ("research.entry_behavior_training",)
    assert missing_required_modules(
        contents - {"research.entry_behavior_validation"}
    ) == ("research.entry_behavior_validation",)
