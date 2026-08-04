"""Общая тёмная/светлая тема для самописных диалогов.

qfluentwidgets красит под текущую Theme только свои собственные окна
(MessageBox/MessageBoxBase вызывают FluentStyleSheet.DIALOG.apply() у себя
в __init__) — обычный QDialog остаётся с системным (светлым) фоном даже при
включённой тёмной теме, а дочерние BodyLabel/CaptionLabel всё равно красятся
в светлый текст глобальной таблицей стилей — получается светлый текст на
светлом фоне, нечитаемо. Все свои диалоги в приложении наследуются от
ThemedDialog вместо голого QDialog, чтобы получать тот же фон/цвет текста,
что и у MessageBox.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QWidget, QWizard
from qfluentwidgets import FluentStyleSheet, isDarkTheme, qconfig, setCustomStyleSheet

from core.settings import RES_DIR

# RaiZo Tools intentionally uses its own cold graphite/cyan palette instead of
# the olive/orange styling of the project the first UI prototype was based on.
BRAND_ACCENT = "#2BB7C9"
BRAND_ACCENT_HOVER = "#43C6D5"
BRAND_ACCENT_PRESSED = "#16899A"

BRAND_LIGHT_BG = "#EFF5F7"
BRAND_LIGHT_NAV = "#E4EEF1"
BRAND_LIGHT_CARD = "#FFFFFF"
BRAND_LIGHT_FIELD = "#F7FBFC"
BRAND_LIGHT_BORDER = "#BACDD3"
BRAND_LIGHT_TEXT = "#18262B"
BRAND_LIGHT_MUTED = "#607780"

BRAND_DARK_BG = "#101722"
BRAND_DARK_NAV = "#0B111B"
BRAND_DARK_CARD = "#182230"
BRAND_DARK_ELEVATED = "#1E2B3B"
BRAND_DARK_FIELD = "#0D1520"
BRAND_DARK_BORDER = "#2A4055"
BRAND_DARK_TEXT = "#EAF4F7"
BRAND_DARK_MUTED = "#91A9B3"

BRAND_SUCCESS = "#65C18C"
BRAND_WARNING = "#E6B86A"
BRAND_ERROR = "#FF6B75"
BRAND_INFO = "#6CB6FF"

_LIGHT_BG = BRAND_LIGHT_BG
_DARK_BG = BRAND_DARK_BG

_PAGE_NAMES = (
    "launchInterface",
    "modsInterface",
    "logsInterface",
    "cfgInterface",
    "pboBuilderInterface",
    "settingsInterface",
)


def _page_selectors() -> str:
    return ",\n".join(f"QWidget#{name}" for name in _PAGE_NAMES)


def _main_qss(*, bg: str, nav: str, card: str, border: str, muted: str) -> str:
    pages = _page_selectors()
    return f"""
FluentWindow#raizoMainWindow {{ background-color: {bg}; }}
FluentWindow#raizoMainWindow NavigationInterface,
FluentWindow#raizoMainWindow FluentTitleBar {{ background-color: {nav}; }}
FluentWindow#raizoMainWindow NavigationInterface {{ border-right: 1px solid {border}; }}
FluentWindow#raizoMainWindow StackedWidget {{ background-color: {bg}; }}
{pages} {{ background-color: {bg}; }}
FluentWindow#raizoMainWindow CardWidget {{
    background-color: {card};
    border: 1px solid {border};
    border-radius: 10px;
}}
FluentWindow#raizoMainWindow QGroupBox {{
    background-color: {card};
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 9px;
    padding-top: 8px;
}}
FluentWindow#raizoMainWindow QGroupBox::title {{
    color: {muted};
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}
FluentWindow#raizoMainWindow QToolTip {{
    border: 1px solid {BRAND_ACCENT};
}}
"""


MAIN_LIGHT_QSS = _main_qss(
    bg=BRAND_LIGHT_BG,
    nav=BRAND_LIGHT_NAV,
    card=BRAND_LIGHT_CARD,
    border=BRAND_LIGHT_BORDER,
    muted=BRAND_LIGHT_MUTED,
)
MAIN_DARK_QSS = _main_qss(
    bg=BRAND_DARK_BG,
    nav=BRAND_DARK_NAV,
    card=BRAND_DARK_CARD,
    border=BRAND_DARK_BORDER,
    muted=BRAND_DARK_MUTED,
)


def _pbo_qss(
    *,
    bg: str,
    card: str,
    elevated: str,
    field: str,
    border: str,
    text: str,
    muted: str,
    pressed: str,
) -> str:
    return f"""
* {{ font-family: "Segoe UI", "Arial"; font-size: 10pt; color: {text}; }}
QWidget#pboBuilderInterface, QDialog {{ background: {bg}; }}
QWidget {{ background: transparent; }}
#Card {{ background: {card}; border: 1px solid {border}; border-radius: 9px; }}
#DialogTitle {{ font-size: 15pt; font-weight: 700; color: {text}; }}
#CardTitle {{ color: {BRAND_ACCENT}; font-weight: 700; padding: 3px 0 5px 0; }}
#FieldLabel {{ color: {muted}; font-size: 9pt; }}
#StatusBadge {{ background: {field}; border: 1px solid {border}; border-radius: 7px; max-height: 25px; }}
QLabel#StatusText {{ font-size: 8pt; }}
QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QSpinBox, QComboBox {{
    background: {field}; border: 1px solid {border}; border-radius: 6px; padding: 5px;
    color: {text}; selection-background-color: {BRAND_ACCENT};
}}
QComboBox {{ padding-right: 20px; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {field}; border: 1px solid {border};
    selection-background-color: {BRAND_ACCENT}; outline: 0;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QListWidget:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {BRAND_ACCENT}; }}
QListWidget::item {{ min-height: 24px; padding: 4px 7px; border-radius: 4px; }}
QListWidget::item:hover {{ background: {elevated}; }}
QListWidget::item:selected {{ background: {BRAND_ACCENT_PRESSED}; color: white; }}
QCheckBox {{ spacing: 7px; color: {text}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {border};
    border-radius: 4px; background: {field};
}}
QCheckBox::indicator:hover {{ border: 1px solid {BRAND_ACCENT}; }}
QCheckBox::indicator:checked {{ background: {BRAND_ACCENT}; border: 1px solid {BRAND_ACCENT}; }}
QPushButton, QToolButton {{
    background: {elevated}; border: 1px solid {border}; border-radius: 6px;
    padding: 5px 8px; color: {text}; min-height: 24px;
}}
QPushButton:hover, QToolButton:hover {{ background: {card}; border: 1px solid {BRAND_ACCENT}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {pressed}; }}
QPushButton:disabled {{ color: {muted}; background: {field}; border: 1px solid {border}; }}
#PrimaryButton {{ background: {BRAND_ACCENT}; border: 1px solid {BRAND_ACCENT}; font-weight: 700; color: #071316; }}
#PrimaryButton:hover {{ background: {BRAND_ACCENT_HOVER}; }}
#AddonIconButton {{ min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; }}
#PathIconButton {{ min-width: 32px; max-width: 32px; min-height: 28px; max-height: 28px; padding: 0; }}
QProgressBar {{
    background: {field}; border: 1px solid {border}; border-radius: 5px;
    min-height: 8px; max-height: 8px;
}}
QProgressBar::chunk {{ background: {BRAND_ACCENT}; border-radius: 5px; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: {field}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BRAND_ACCENT}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


PBO_LIGHT_QSS = _pbo_qss(
    bg=BRAND_LIGHT_BG,
    card=BRAND_LIGHT_CARD,
    elevated=BRAND_LIGHT_NAV,
    field=BRAND_LIGHT_FIELD,
    border=BRAND_LIGHT_BORDER,
    text=BRAND_LIGHT_TEXT,
    muted=BRAND_LIGHT_MUTED,
    pressed="#C9E3E8",
)
PBO_DARK_QSS = _pbo_qss(
    bg=BRAND_DARK_BG,
    card=BRAND_DARK_CARD,
    elevated=BRAND_DARK_ELEVATED,
    field=BRAND_DARK_FIELD,
    border=BRAND_DARK_BORDER,
    text=BRAND_DARK_TEXT,
    muted=BRAND_DARK_MUTED,
    pressed="#12313B",
)

ICON_FILE = RES_DIR / "core" / "pbobuilder" / "assets" / "icon.ico"
_icon_cache: QIcon | None = None


def app_icon(dark: bool | None = None) -> QIcon:
    """Готовая многоразмерная ICO без перекраски и пересборки."""
    del dark
    global _icon_cache
    if _icon_cache is None:
        _icon_cache = QIcon(str(ICON_FILE))
    return _icon_cache


def link_color() -> str:
    """Цвет ссылки под текущую тему.

    Системный синий Qt на тёмном фоне почти неразличим, поэтому используем
    светлый и тёмный варианты фирменного бирюзового акцента.
    """
    return "#56D6E4" if isDarkTheme() else "#087C8C"


def link_html(url: str, text: str = "") -> str:
    """Ссылка с явным цветом. Через таблицу стилей QLabel цвет ссылки задать
    нельзя — Qt красит её сам, пока цвет не указан прямо в теге."""
    return f'<a href="{url}" style="color:{link_color()};">{text or url}</a>'


def outside_icon() -> QIcon:
    """Та же готовая ICO для панели задач, проводника, Alt+Tab и трея."""
    return app_icon()


class _ThemeStyleBinder(QObject):
    """Обновляет дополнительный QSS при переключении Fluent-темы."""

    def __init__(self, widget: QWidget, light_qss: str, dark_qss: str) -> None:
        super().__init__(widget)
        self.widget = widget
        self.base_qss = widget.styleSheet()
        self.light_qss = light_qss
        self.dark_qss = dark_qss
        qconfig.themeChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        custom = self.dark_qss if isDarkTheme() else self.light_qss
        self.widget.setStyleSheet(f"{self.base_qss}\n{custom}")


def _apply_bound_style(widget: QWidget, attr: str, light_qss: str, dark_qss: str) -> None:
    binder = getattr(widget, attr, None)
    if binder is None:
        binder = _ThemeStyleBinder(widget, light_qss, dark_qss)
        setattr(widget, attr, binder)
    else:
        binder.refresh()


def apply_brand_style(widget: QWidget) -> None:
    """Применить общую палитру к главному Fluent-окну."""
    _apply_bound_style(widget, "_raizo_main_style_binder", MAIN_LIGHT_QSS, MAIN_DARK_QSS)


def apply_pbo_style(widget: QWidget) -> None:
    """Применить ту же палитру к обычным Qt-виджетам PBO Builder."""
    _apply_bound_style(widget, "_raizo_pbo_style_binder", PBO_LIGHT_QSS, PBO_DARK_QSS)


def _page_qss(bg: str) -> str:
    """Фон страниц мастера и их дочерних контейнеров.

    Правило QDialog из DIALOG.qss до QWizardPage не достаёт, а нативный стиль
    Windows (windowsvista + ModernStyle) рисует область страницы белой поверх
    тёмного фона самого окна.
    """
    return f"QWizardPage{{background-color:{bg};}}QWizardPage QGroupBox{{background-color:transparent;}}"


class ThemedDialog(QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        FluentStyleSheet.DIALOG.apply(self)


class ThemedWizard(QWizard):
    """QWizard — тоже QDialog в Qt, поэтому тот же DIALOG.qss (селектор QDialog
    в стилевом листе матчит и подклассы) красит фон самого окна; страницы
    приходится красить отдельно (см. _page_qss)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ClassicStyle — иначе windowsvista подмешивает свой светлый заголовок
        # и рамку страницы, которые не подчиняются таблице стилей
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        FluentStyleSheet.DIALOG.apply(self)
        setCustomStyleSheet(self, _page_qss(_LIGHT_BG), _page_qss(_DARK_BG))
