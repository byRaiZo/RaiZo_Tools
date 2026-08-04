"""Окна логов PBO Builder byRaiZo: сборка и бинаризация.

Логи пишет встроенный backend в LOCALAPPDATA, и у крупного мода
это тысячи строк, среди которых пара предупреждений. Поэтому по умолчанию
показываются только строки с Warning/Error, а полный текст — по галке.

Перед каждым логом идёт итог: сколько предупреждений и ошибок. Он же красит
заголовок — зелёный, если чисто.
"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox, isDarkTheme, qconfig

from core import packlog
from core.i18n import tr
from ui.theme import (
    BRAND_ACCENT,
    BRAND_DARK_BG,
    BRAND_DARK_BORDER,
    BRAND_DARK_CARD,
    BRAND_DARK_TEXT,
    BRAND_LIGHT_BG,
    BRAND_LIGHT_BORDER,
    BRAND_LIGHT_CARD,
    BRAND_LIGHT_TEXT,
)

_WARN_COLOR = "#e5c07b"
_ERR_COLOR = "#ff6b6b"
_OK_COLOR = "#4caf50"
_TEXT_COLOR = "#d4d4d4"
_CONSOLE_QSS = "QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;border:1px solid #333;border-radius:6px;padding:4px;}"

_TITLES = {packlog.PACKING: "Логи запаковки", packlog.BINARIZE: "Логи бинаризации"}


class _PackLogPage(QWidget):
    """Одна вкладка логов по всем PBO последней запаковки."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self._reports: list[packlog.LogReport] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        row = QHBoxLayout()
        self.chk_full = CheckBox(tr("packlog.show_full", "Показать полностью"))
        self.chk_full.setToolTip(
            tr(
                "packlog.show_full_tip",
                "Весь текст логов. Без галки показываются только строки с предупреждениями и ошибками.",
            )
        )
        self.chk_full.toggled.connect(lambda _v: self._render())
        row.addWidget(self.chk_full)
        row.addStretch(1)
        layout.addLayout(row)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setStyleSheet(_CONSOLE_QSS)
        layout.addWidget(self.view, 1)

    # ----------------------------------------------------------------- данные

    def set_names(self, names: list[str]) -> None:
        """Показывает логи только что собранных PBO — а не всё, что лежит в temp
        от прошлых сессий."""
        self._reports = packlog.read_all(names, self.kind)
        self._render()

    def _summary(self, rep: packlog.LogReport) -> str:
        head = tr("packlog.summary", "[Результаты запаковки {n}]", n=f"{rep.name}.pbo")
        color = _OK_COLOR if rep.clean else _TEXT_COLOR
        parts = [f'<span style="color:{color};font-weight:600;">{html.escape(head)}</span>']
        if rep.clean:
            parts.append(
                f'<span style="color:{_OK_COLOR};">' + html.escape(tr("packlog.no_issues", "без замечаний")) + "</span>"
            )
        else:
            parts.append(f'<span style="color:{_WARN_COLOR};">Warnings: {rep.warnings}</span>')
            parts.append(f'<span style="color:{_ERR_COLOR};">Errors: {rep.errors}</span>')
        return " ".join(parts)

    def _line_html(self, line: str) -> str:
        """Красим только метку в начале строки, а не строку целиком —
        так текст остаётся читаемым."""
        n = packlog.mark_len(line)
        if not n:
            return f'<span style="color:{_TEXT_COLOR};">{html.escape(line)}</span>'
        color = _WARN_COLOR if packlog.mark_of(line) == packlog.WARNING else _ERR_COLOR
        return (
            f'<span style="color:{color};font-weight:600;">{html.escape(line[:n])}</span>'
            f'<span style="color:{_TEXT_COLOR};">{html.escape(line[n:])}</span>'
        )

    def _render(self) -> None:
        self.view.clear()
        if not self._reports:
            self.view.appendHtml(
                f'<span style="color:{_TEXT_COLOR};">'
                + html.escape(tr("packlog.empty", "Пока ничего не паковалось."))
                + "</span>"
            )
            return
        full = self.chk_full.isChecked()
        blocks = []
        for rep in self._reports:
            if not rep.exists:
                continue
            block = [self._summary(rep)]
            lines = rep.lines if full else rep.marked_lines()
            block += [self._line_html(ln) for ln in lines]
            if rep.truncated and full:
                # молча обрезать нельзя: конец лога — как раз то место, где
                # обычно и лежит причина падения сборки
                block.append(
                    self._line_html(
                        tr(
                            "packlog.truncated",
                            "=== лог слишком велик: показаны первые {n} строк ===",
                            n=packlog.MAX_LINES,
                        )
                    )
                )
            blocks.append("<br>".join(block))
        self.view.appendHtml(
            "<br><br>".join(blocks)
            if blocks
            else f'<span style="color:{_TEXT_COLOR};">'
            + html.escape(tr("packlog.no_logs", "Логи не найдены."))
            + "</span>"
        )
        self.view.moveCursor(self.view.textCursor().MoveOperation.Start)


class PackLogWindow(QWidget):
    """Единое окно логов запаковки и бинаризации."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("packLogsWindow")
        self.setWindowTitle(tr("packlog.title_packing", "Логи запаковки"))
        self.resize(960, 650)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages = {kind: _PackLogPage(kind) for kind in packlog.KINDS}
        for kind, page in self.pages.items():
            title = _TITLES[kind]
            self.tabs.addTab(page, tr(f"packlog.title_{kind}", title))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.tabs)

        self._apply_bg()
        qconfig.themeChanged.connect(self._apply_bg)

    def _apply_bg(self) -> None:
        if isDarkTheme():
            bg, card, border, text = BRAND_DARK_BG, BRAND_DARK_CARD, BRAND_DARK_BORDER, BRAND_DARK_TEXT
        else:
            bg, card, border, text = BRAND_LIGHT_BG, BRAND_LIGHT_CARD, BRAND_LIGHT_BORDER, BRAND_LIGHT_TEXT
        self.setStyleSheet(
            f"""
            QWidget#packLogsWindow {{ background-color: {bg}; }}
            QTabWidget::pane {{ background: {card}; border: 1px solid {border}; border-radius: 7px; }}
            QTabBar::tab {{ background: {bg}; color: {text}; padding: 8px 18px; border: 1px solid {border}; }}
            QTabBar::tab:selected {{ background: {BRAND_ACCENT}; color: #071316; }}
            """
            + _CONSOLE_QSS
        )

    def set_names(self, names: list[str]) -> None:
        for page in self.pages.values():
            page.set_names(names)
