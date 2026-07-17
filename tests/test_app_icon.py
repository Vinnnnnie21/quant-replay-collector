from __future__ import annotations

import struct
from pathlib import Path

import pytest


QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app_icon import application_icon_path, application_logo_path, apply_application_icon
from scripts.generate_app_icon import WINDOWS_ICON_SIZES, build_windows_icon


APP_DIR = Path(__file__).resolve().parents[1] / "quant_collector_app"
SOURCE_LOGO = APP_DIR / "assets" / "app_logo.png"
LIGHT_LOGO = APP_DIR / "assets" / "app_logo_light.png"
WINDOWS_ICON = APP_DIR / "assets" / "app_icon.ico"


def test_logo_assets_are_readable_and_icon_contains_windows_sizes():
    assert SOURCE_LOGO.is_file()
    assert LIGHT_LOGO.is_file()
    assert WINDOWS_ICON.is_file()
    source = QtGui.QImage(str(SOURCE_LOGO))
    light_source = QtGui.QImage(str(LIGHT_LOGO))
    icon = QtGui.QIcon(str(WINDOWS_ICON))

    assert (source.width(), source.height()) == (697, 697)
    assert source.pixelColor(0, 0).alpha() == 255
    assert source.pixelColor(0, 0).lightness() < 16
    assert (light_source.width(), light_source.height()) == (692, 696)
    assert light_source.pixelColor(0, 0).alpha() == 0
    assert not icon.isNull()
    sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes

    header = WINDOWS_ICON.read_bytes()[:6]
    reserved, image_type, image_count = struct.unpack("<HHH", header)
    assert (reserved, image_type) == (0, 1)
    assert image_count >= 7


def test_application_uses_the_stable_icon_asset():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    previous = app.windowIcon()

    try:
        assert application_icon_path() == WINDOWS_ICON
        assert apply_application_icon(app) is True
        assert not app.windowIcon().isNull()
    finally:
        app.setWindowIcon(previous)


def test_application_logo_follows_light_and_dark_theme():
    assert application_logo_path({"bg_primary": "#060606"}) == SOURCE_LOGO
    assert application_logo_path({"bg_primary": "#FFFFFF"}) == LIGHT_LOGO


def test_app_and_window_icon_switch_with_the_theme():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    previous = app.windowIcon()

    try:
        assert apply_application_icon(app, {"bg_primary": "#060606"}, window) is True
        dark_image = window.windowIcon().pixmap(64, 64).toImage()
        assert dark_image.pixelColor(0, 0).alpha() == 255
        assert dark_image.pixelColor(0, 0).lightness() < 16

        assert apply_application_icon(app, {"bg_primary": "#FFFFFF"}, window) is True
        light_image = window.windowIcon().pixmap(64, 64).toImage()
        assert light_image.pixelColor(0, 0).alpha() == 0
        assert app.windowIcon().cacheKey() == window.windowIcon().cacheKey()
    finally:
        window.close()
        app.setWindowIcon(previous)


def test_icon_generator_rebuilds_all_supported_sizes(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    output = build_windows_icon(SOURCE_LOGO, tmp_path / "app_icon.ico")
    icon = QtGui.QIcon(str(output))

    assert not icon.isNull()
    assert {(size.width(), size.height()) for size in icon.availableSizes()} == {
        (size, size) for size in WINDOWS_ICON_SIZES
    }
    app.processEvents()


def test_windows_build_bundles_runtime_icon_resource():
    source = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")

    assert '--paths "%CD%"' in source
    assert "--icon=assets\\app_icon.ico" in source
    assert "--add-data=assets\\app_icon.ico;assets" in source
    assert "--add-data=assets\\app_logo.png;assets" in source
    assert "--add-data=assets\\app_logo_light.png;assets" in source
    assert "verify_frozen_archive.py" in source


def test_icon_generator_is_included_in_the_clean_release():
    from scripts.clean_release import ROOT_CONTENT

    assert "scripts/generate_app_icon.py" in ROOT_CONTENT
    assert "scripts/verify_frozen_archive.py" in ROOT_CONTENT
