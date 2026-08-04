"""Управление пользовательскими флагами модов (название, цвет, начертание,
иконка) — открывается кнопкой «Флаги…» с вкладки «Моды»."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QListWidgetItem,
    QColorDialog,
    QScrollArea,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    ToolButton,
    LineEdit,
    CheckBox,
    ListWidget,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    Theme,
)

from core.i18n import tr
from core.mods import ModFlagDef, ModInfo, ModRegistry, load_flag_defs, save_flag_defs
from ui.theme import ThemedDialog

_DEFAULT_COLOR = "#c9a227"
_ALL_ICON_NAMES = sorted(n for n in dir(FIF) if n.isupper())


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_").lower()
    return s or "flag"


def _swatch_icon(color: str) -> QIcon:
    pix = QPixmap(14, 14)
    pix.fill(QColor(color))
    return QIcon(pix)


def flag_font(d: ModFlagDef) -> QFont:
    font = QFont()
    font.setBold(d.bold)
    font.setItalic(d.italic)
    font.setUnderline(d.underline)
    return font


def flag_icon(d: ModFlagDef) -> QIcon | None:
    """Иконка флага под текущую тему.

    Без явной темы FluentIcon отдаёт чёрный вариант — на тёмном фоне его
    почти не видно. Theme.AUTO выбирает чёрный или белый по текущей теме
    приложения.
    """
    if d.icon and hasattr(FIF, d.icon):
        return getattr(FIF, d.icon).icon(Theme.AUTO)
    return None


def _mod_flag_defs(mod, flag_defs: dict) -> list[ModFlagDef]:
    return [flag_defs[fid] for fid in mod.flags if fid in flag_defs]


def style_checkbox_by_flags(cb, mod, flag_defs: dict) -> None:
    """Оформляет CheckBox по флагам мода — цвет/иконка от первого назначенного,
    начертание объединяется по всем сразу (см. ModsPanel._make_mod_item)."""
    defs = _mod_flag_defs(mod, flag_defs)
    if not defs:
        return
    font = cb.font()
    font.setBold(any(d.bold for d in defs))
    font.setItalic(any(d.italic for d in defs))
    font.setUnderline(any(d.underline for d in defs))
    cb.setFont(font)
    cb.setTextColor(defs[0].color, defs[0].color)
    icon = flag_icon(defs[0])
    if icon:
        cb.setIcon(icon)


def style_list_item_by_flags(item, mod, flag_defs: dict) -> None:
    """Оформляет QListWidgetItem по флагам мода — аналог style_checkbox_by_flags."""
    defs = _mod_flag_defs(mod, flag_defs)
    if not defs:
        return
    font = item.font()
    font.setBold(any(d.bold for d in defs))
    font.setItalic(any(d.italic for d in defs))
    font.setUnderline(any(d.underline for d in defs))
    item.setFont(font)
    item.setForeground(QColor(defs[0].color))
    icon = flag_icon(defs[0])
    if icon:
        item.setIcon(icon)


class IconPickerDialog(ThemedDialog):
    """Сетка всех доступных иконок (qfluentwidgets.FluentIcon) — клик выбирает."""

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.chosen = current
        self.setWindowTitle(tr("flags.icon_pick_title", "Выбор иконки"))
        self.resize(420, 480)
        layout = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # QScrollArea сама тему не подхватывает: её viewport остаётся системным
        # белым даже в тёмной теме — делаем прозрачной, чтобы был виден фон диалога
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QWidget()
        inner.setObjectName("iconGrid")
        inner.setStyleSheet("QWidget#iconGrid{background:transparent;}")
        grid = QGridLayout(inner)
        grid.setSpacing(4)
        cols = 8
        b_none = ToolButton()
        b_none.setToolTip(tr("flags.icon_none", "Без иконки"))
        b_none.clicked.connect(lambda: self._pick(""))
        grid.addWidget(b_none, 0, 0)
        for i, name in enumerate(_ALL_ICON_NAMES, start=1):
            btn = ToolButton(getattr(FIF, name))
            btn.setToolTip(name)
            btn.clicked.connect(lambda _=False, n=name: self._pick(n))
            grid.addWidget(btn, i // cols, i % cols)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        layout.addLayout(btns)

    def _pick(self, name: str) -> None:
        self.chosen = name
        self.accept()


class FlagEditorDialog(ThemedDialog):
    """Создание/редактирование одного флага: название, цвет, начертание, иконка."""

    def __init__(self, flag: ModFlagDef | None, parent=None):
        super().__init__(parent)
        self._color = flag.color if flag else _DEFAULT_COLOR
        self._icon = flag.icon if flag else ""
        self.setWindowTitle(tr("flags.rename_title", "Флаг") if flag else tr("flags.add_title", "Новый флаг"))
        self.resize(360, 260)
        layout = QVBoxLayout(self)

        layout.addWidget(BodyLabel(tr("flags.name_prompt", "Название флага:")))
        self.name_edit = LineEdit()
        self.name_edit.setText(flag.name if flag else "")
        layout.addWidget(self.name_edit)

        style_row = QHBoxLayout()
        self.chk_bold = CheckBox(tr("flags.bold", "Жирный"))
        self.chk_italic = CheckBox(tr("flags.italic", "Курсив"))
        self.chk_underline = CheckBox(tr("flags.underline", "Подчёркнутый"))
        if flag:
            self.chk_bold.setChecked(flag.bold)
            self.chk_italic.setChecked(flag.italic)
            self.chk_underline.setChecked(flag.underline)
        for cb in (self.chk_bold, self.chk_italic, self.chk_underline):
            style_row.addWidget(cb)
        layout.addLayout(style_row)

        pick_row = QHBoxLayout()
        self.b_color = PushButton(tr("flags.color", "Цвет…"))
        self.b_color.setIcon(_swatch_icon(self._color))
        self.b_color.clicked.connect(self._pick_color)
        self.b_icon = PushButton(tr("flags.icon", "Иконка…"))
        self._update_icon_button()
        self.b_icon.clicked.connect(self._pick_icon)
        pick_row.addWidget(self.b_color)
        pick_row.addWidget(self.b_icon)
        layout.addLayout(pick_row)

        preview_row = QHBoxLayout()
        preview_row.addWidget(CaptionLabel(tr("flags.preview", "Предпросмотр:")))
        self.preview = BodyLabel("")
        preview_row.addWidget(self.preview, 1)
        layout.addLayout(preview_row)
        for w in (self.name_edit,):
            w.textChanged.connect(self._update_preview)
        for cb in (self.chk_bold, self.chk_italic, self.chk_underline):
            cb.toggled.connect(self._update_preview)
        self._update_preview()

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(tr("common.save", "Сохранить"))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def _update_icon_button(self) -> None:
        self.b_icon.setIcon(getattr(FIF, self._icon) if self._icon else FIF.ADD)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, tr("flags.pick_color", "Цвет флага"))
        if color.isValid():
            self._color = color.name()
            self.b_color.setIcon(_swatch_icon(self._color))
            self._update_preview()

    def _pick_icon(self) -> None:
        dlg = IconPickerDialog(self._icon, self)
        if dlg.exec():
            self._icon = dlg.chosen
            self._update_icon_button()
            self._update_preview()

    def _update_preview(self) -> None:
        font = QFont()
        font.setBold(self.chk_bold.isChecked())
        font.setItalic(self.chk_italic.isChecked())
        font.setUnderline(self.chk_underline.isChecked())
        self.preview.setFont(font)
        self.preview.setStyleSheet(f"color: {self._color};")
        self.preview.setText(self.name_edit.text().strip() or tr("flags.name_prompt", "Название флага:"))

    def result_values(self) -> tuple[str, str, bool, bool, bool, str]:
        return (
            self.name_edit.text().strip(),
            self._color,
            self.chk_bold.isChecked(),
            self.chk_italic.isChecked(),
            self.chk_underline.isChecked(),
            self._icon,
        )


class ModFlagsDialog(ThemedDialog):
    """Список пользовательских флагов — создать/изменить/удалить. Назначение
    флагов конкретным модам — через ПКМ на вкладке «Моды»."""

    def __init__(self, registry: ModRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.defs: list[ModFlagDef] = load_flag_defs()
        self.changed = False

        self.setWindowTitle(tr("flags.title", "Флаги модов"))
        self.resize(360, 420)
        layout = QVBoxLayout(self)
        hint = CaptionLabel(
            tr(
                "flags.hint",
                "Флаги — метки модов с произвольным названием, цветом, начертанием и "
                "иконкой. Назначаются правым кликом по моду на вкладке «Моды» → «Флаги».",
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lst = ListWidget()
        self.lst.setIconSize(QSize(16, 16))
        self.lst.itemDoubleClicked.connect(lambda _i: self._edit())
        self._reload_list()
        layout.addWidget(self.lst, 1)

        btns = QHBoxLayout()
        b_add = PushButton(FIF.ADD, tr("flags.add", "Добавить…"))
        b_add.clicked.connect(self._add)
        b_edit = PushButton(FIF.EDIT, tr("flags.edit", "Изменить…"))
        b_edit.clicked.connect(self._edit)
        b_del = PushButton(FIF.DELETE, tr("flags.delete", "Удалить"))
        b_del.clicked.connect(self._delete)
        for b in (b_add, b_edit, b_del):
            btns.addWidget(b)
        layout.addLayout(btns)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        b_close = PrimaryPushButton(tr("common.close", "Закрыть"))
        b_close.clicked.connect(self.accept)
        close_row.addWidget(b_close)
        layout.addLayout(close_row)

    def _reload_list(self) -> None:
        self.lst.clear()
        for d in self.defs:
            icon = flag_icon(d) or _swatch_icon(d.color)
            item = QListWidgetItem(icon, d.name)
            item.setFont(flag_font(d))
            item.setForeground(QColor(d.color))
            item.setData(Qt.ItemDataRole.UserRole, d.id)
            self.lst.addItem(item)

    def _current_def(self) -> ModFlagDef | None:
        item = self.lst.currentItem()
        if not item:
            return None
        fid = item.data(Qt.ItemDataRole.UserRole)
        return next((d for d in self.defs if d.id == fid), None)

    def _unique_id(self, base: str) -> str:
        existing = {d.id for d in self.defs}
        fid, n = base, 2
        while fid in existing:
            fid = f"{base}_{n}"
            n += 1
        return fid

    def _add(self) -> None:
        dlg = FlagEditorDialog(None, self)
        if not dlg.exec():
            return
        name, color, bold, italic, underline, icon = dlg.result_values()
        if not name:
            return
        self.defs.append(
            ModFlagDef(
                id=self._unique_id(_slug(name)),
                name=name,
                color=color,
                bold=bold,
                italic=italic,
                underline=underline,
                icon=icon,
            )
        )
        save_flag_defs(self.defs)
        self.changed = True
        self._reload_list()

    def _edit(self) -> None:
        d = self._current_def()
        if not d:
            return
        dlg = FlagEditorDialog(d, self)
        if not dlg.exec():
            return
        name, color, bold, italic, underline, icon = dlg.result_values()
        if not name:
            return
        d.name, d.color, d.bold, d.italic, d.underline, d.icon = name, color, bold, italic, underline, icon
        save_flag_defs(self.defs)
        self.changed = True
        self._reload_list()

    def _delete(self) -> None:
        d = self._current_def()
        if not d:
            return
        self.defs = [x for x in self.defs if x.id != d.id]
        save_flag_defs(self.defs)
        # чистим ссылки на удалённый флаг у всех модов, иначе он «осиротеет»
        # в mod_flags.json и будет висеть невидимым (стиля для него уже нет)
        dirty = False
        for mod in self.registry.mods.values():
            if d.id in mod.flags:
                mod.flags.remove(d.id)
                dirty = True
        if dirty:
            self.registry.save_flags()
        self.changed = True
        self._reload_list()


class FlagAssignDialog(ThemedDialog):
    """Назначение флагов одному или нескольким модам разом (массовое —
    Ctrl/Shift+клик на вкладке «Моды», затем ПКМ → «Флаги…»). Флаг, стоящий
    только у части выбранных модов, показывается в промежуточном состоянии —
    если его не трогать, назначение не меняется ни у кого; кликом по нему
    можно поставить/снять сразу для всех выбранных."""

    def __init__(self, mods: list[ModInfo], flag_defs: list[ModFlagDef], parent=None):
        super().__init__(parent)
        title = mods[0].name if len(mods) == 1 else tr("flags.assign_title_n", "{n} модов", n=len(mods))
        self.setWindowTitle(tr("flags.assign_title", "Флаги — {t}", t=title))
        self.resize(320, 380)
        layout = QVBoxLayout(self)

        self.lst = ListWidget()
        self.lst.setIconSize(QSize(16, 16))
        if not flag_defs:
            layout.addWidget(CaptionLabel(tr("mods.ctx_no_flags", "Флагов пока нет…")))
        for d in flag_defs:
            icon = flag_icon(d) or _swatch_icon(d.color)
            item = QListWidgetItem(icon, d.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setFont(flag_font(d))
            item.setForeground(QColor(d.color))
            item.setData(Qt.ItemDataRole.UserRole, d.id)
            n = sum(1 for m in mods if d.id in m.flags)
            item.setCheckState(
                Qt.CheckState.Unchecked
                if n == 0
                else Qt.CheckState.Checked
                if n == len(mods)
                else Qt.CheckState.PartiallyChecked
            )
            self.lst.addItem(item)
        layout.addWidget(self.lst, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        b_ok = PrimaryPushButton(tr("common.save", "Сохранить"))
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        layout.addLayout(btns)

    def result_changes(self) -> dict[str, bool]:
        """id флага -> назначить всем (True) / снять со всех (False). Флаги,
        оставшиеся в промежуточном состоянии (не тронутые), не включаются."""
        out = {}
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            state = item.checkState()
            if state == Qt.CheckState.PartiallyChecked:
                continue
            out[item.data(Qt.ItemDataRole.UserRole)] = state == Qt.CheckState.Checked
        return out
