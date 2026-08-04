from PySide6.QtWidgets import QWidget
from qfluentwidgets import Theme, setTheme

from ui.theme import (
    BRAND_ACCENT,
    BRAND_DARK_BG,
    BRAND_LIGHT_BG,
    MAIN_DARK_QSS,
    MAIN_LIGHT_QSS,
    PBO_DARK_QSS,
    PBO_LIGHT_QSS,
    apply_pbo_style,
)


def test_main_and_pbo_builder_share_raizo_palette() -> None:
    styles = (MAIN_LIGHT_QSS, MAIN_DARK_QSS, PBO_LIGHT_QSS, PBO_DARK_QSS)

    assert all(BRAND_ACCENT in style for style in styles)
    assert all("#d0752b" not in style.lower() for style in styles)
    assert all("#ff9300" not in style.lower() for style in styles)


def test_pbo_builder_has_light_and_dark_surfaces() -> None:
    assert "#ffffff" in PBO_LIGHT_QSS.lower()
    assert "#182230" in PBO_DARK_QSS.lower()


def test_pbo_palette_switches_with_application_theme(qtbot) -> None:
    widget = QWidget()
    qtbot.addWidget(widget)

    try:
        setTheme(Theme.DARK)
        apply_pbo_style(widget)
        assert BRAND_DARK_BG in widget.styleSheet()

        setTheme(Theme.LIGHT)
        assert BRAND_LIGHT_BG in widget.styleSheet()
    finally:
        setTheme(Theme.AUTO)
