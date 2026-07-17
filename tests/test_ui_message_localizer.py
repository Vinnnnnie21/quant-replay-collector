from __future__ import annotations

from app_i18n import tr
from services.ui_message_localizer import localize_worker_message


def _translator(language: str):
    return lambda key: tr(key, language)


def test_worker_progress_messages_are_localized_for_chinese_ui():
    translate = _translator("zh_CN")

    assert localize_worker_message("Checking cache.", translate) == "正在检查本地缓存…"
    assert localize_worker_message("Downloaded 120 bars.", translate) == "已下载 120 根 K 线。"
    assert localize_worker_message(
        "Loaded cache BTCUSDT_1m.csv; bars=120; quality=ok.",
        translate,
    ) == "已从本地缓存加载 120 根 K 线。"
    assert localize_worker_message("Preparing export...", translate) == "正在准备导出…"
    assert localize_worker_message(
        "Backing up local database in background... 42%",
        translate,
    ) == "正在后台备份本地数据库… 42%"


def test_worker_progress_messages_are_localized_for_english_ui():
    translate = _translator("en_US")

    assert localize_worker_message("正在安全发布导出结果", translate) == "Publishing export results safely…"
    assert localize_worker_message("导出已完成，旧临时目录稍后清理", translate) == (
        "Export completed; the old temporary directory will be cleaned up later."
    )
    assert localize_worker_message("加载失败：网络请求超时，请检查网络或稍后重试。", translate) == (
        "Market-data loading failed: The network request timed out. Check the connection and try again later."
    )
