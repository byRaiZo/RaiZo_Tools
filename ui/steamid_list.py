"""Список админских SteamID: список записей и кнопки «+» и «−» сбоку.

Раньше это было свободное текстовое поле, по одному значению на строку. Туда
попадало что угодно: опечатка, ник вместо идентификатора, ссылка целиком,
случайно вставленный кусок текста. Заметить это было негде — список уходит
в конфиги админок (COT, VPPAdminTools, LBmaster), а те просто молча не выдают
прав, и человек ищет причину в чём угодно, только не в лишнем пробеле.

Теперь запись нельзя создать мимо проверки. Ввод разбирается: готовый
SteamID64 и ссылка /profiles/<id> принимаются сразу, ссылка /id/<имя> и голое
имя требуют обращения к Steam, всё остальное отклоняется с объяснением. В
список попадает только SteamID64 из семнадцати цифр.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)

from core import steam_api
from core.i18n import tr
from ui.theme import ThemedDialog


class ResolveSteamIdWorker(QThread):
    """Определение SteamID64 по ссылке или имени профиля — в фоне: ходит в сеть."""

    done = Signal(str, str)  # SteamID64 (пусто — не вышло), исходный ввод

    def __init__(self, value: str, api_key: str, parent=None):
        super().__init__(parent)
        self.value = value
        self.api_key = api_key

    def run(self) -> None:
        try:
            sid = steam_api.resolve_steamid(self.value, self.api_key)
        except Exception:  # noqa: BLE001 — сеть/парсинг не должны ронять приложение
            sid = ""
        self.done.emit(sid, self.value)


class SteamIdDialog(ThemedDialog):
    """Ввод одного SteamID: готовый идентификатор либо ссылка на профиль.

    Разбирает ввод на лету и говорит, что получилось, ещё до нажатия «ОК» —
    так человек видит ошибку сразу, а не после того, как окно закрылось.
    """

    def __init__(
        self, api_key: str = "", current: str = "", taken: tuple[str, ...] = (), parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.api_key = api_key
        self.taken = tuple(t for t in taken if t != current)
        self.value = ""
        self._worker: ResolveSteamIdWorker | None = None
        self.setWindowTitle(tr("sid.dlg_title", "SteamID"))
        self.resize(460, 210)

        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel(tr("sid.dlg_head", "SteamID64 или ссылка на профиль Steam")))
        self.edit = LineEdit(self)
        self.edit.setText(current)
        self.edit.setPlaceholderText("76561198000000000")
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._recheck)
        layout.addWidget(self.edit)

        self.hint = CaptionLabel("")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = PushButton(tr("common.cancel", "Отмена"))
        b_cancel.clicked.connect(self.reject)
        self.b_ok = PrimaryPushButton(tr("common.ok", "ОК"))
        self.b_ok.clicked.connect(self._accept)
        btns.addWidget(b_cancel)
        btns.addWidget(self.b_ok)
        layout.addLayout(btns)

        self.edit.returnPressed.connect(self._accept)
        self._recheck()

    # ------------------------------------------------------------ проверка

    def _recheck(self) -> None:
        """Подсказка под полем и доступность «ОК» по текущему вводу."""
        raw = self.edit.text().strip()
        if not raw:
            self.hint.setText("")
            self.b_ok.setEnabled(False)
            return
        kind, val = steam_api.parse_steamid_input(raw)
        if kind == "id" and val in self.taken:
            self.hint.setText(tr("sid.dup", "{id} уже в списке", id=val))
            self.b_ok.setEnabled(False)
        elif kind == "id":
            self.hint.setText(tr("sid.ready", "SteamID64: {id}", id=val))
            self.b_ok.setEnabled(True)
        elif kind == "vanity":
            self.hint.setText(tr("sid.vanity", "Имя профиля «{n}» — определим через Steam, нужна сеть.", n=val))
            self.b_ok.setEnabled(True)
        elif raw.isdigit():
            # самый частый промах — сказать сразу, чего именно не хватает
            self.hint.setText(tr("sid.digits", "SteamID64 состоит из 17 цифр, а здесь {n}.", n=len(raw)))
            self.b_ok.setEnabled(False)
        else:
            self.hint.setText(
                tr("sid.bad", "Не похоже ни на SteamID64 из 17 цифр, ни на ссылку вида steamcommunity.com/id/<имя>.")
            )
            self.b_ok.setEnabled(False)

    def _accept(self) -> None:
        if not self.b_ok.isEnabled():
            return
        kind, val = steam_api.parse_steamid_input(self.edit.text())
        if kind == "id":
            self.value = val
            self.accept()
            return
        # имя профиля: за идентификатором надо сходить в сеть
        self.b_ok.setEnabled(False)
        self.edit.setEnabled(False)
        self.hint.setText(tr("sid.resolving", "Определяем SteamID…"))
        self._worker = ResolveSteamIdWorker(self.edit.text().strip(), self.api_key, self)
        self._worker.done.connect(self._resolved)
        self._worker.start()

    def _resolved(self, sid: str, _source: str) -> None:
        self.edit.setEnabled(True)
        if not sid:
            self.hint.setText(
                tr("sid.failed", "Steam не ответил или такого профиля нет. Проверьте ссылку или введите SteamID64.")
            )
            self.b_ok.setEnabled(True)
            return
        if sid in self.taken:
            self.hint.setText(tr("sid.dup", "{id} уже в списке", id=sid))
            return
        self.value = sid
        self.accept()


class SteamIdList(QWidget):
    """Список SteamID с кнопками «+» и «−».

    «+» открывает окно ввода, двойной клик по записи — то же окно, но заменяет
    выбранную запись. «−» удаляет выбранную и недоступен, пока выбирать нечего:
    нажатие, которое ничего не делает, — это вопрос «а почему не сработало?».
    """

    changed = Signal()  # список правился — «Настройкам» пора включить «Сохранить»

    def __init__(self, ids: list[str], api_key: Callable[[], str] | str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._api_key = api_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.lst = ListWidget(self)
        self.lst.setMaximumHeight(96)
        self.lst.addItems(ids)
        self.lst.itemDoubleClicked.connect(lambda _i: self._edit())
        self.lst.currentRowChanged.connect(lambda _r: self._sync())
        layout.addWidget(self.lst, 1)

        side = QVBoxLayout()
        side.setSpacing(4)
        self.b_add = ToolButton(FIF.ADD, self)
        self.b_add.setToolTip(tr("sid.add_tip", "Добавить SteamID или ссылку на профиль"))
        self.b_add.clicked.connect(self._add)
        self.b_del = ToolButton(FIF.REMOVE, self)
        self.b_del.setToolTip(tr("sid.del_tip", "Удалить выбранную запись"))
        self.b_del.clicked.connect(self._remove)
        side.addWidget(self.b_add)
        side.addWidget(self.b_del)
        side.addStretch(1)
        layout.addLayout(side)

        if ids:
            self.lst.setCurrentRow(0)
        self._sync()

    # -------------------------------------------------------------- данные

    def values(self) -> list[str]:
        return [self.lst.item(i).text() for i in range(self.lst.count())]

    def set_values(self, ids: list[str]) -> None:
        self.lst.clear()
        self.lst.addItems(ids)
        if ids:
            self.lst.setCurrentRow(0)
        self._sync()

    # ------------------------------------------------------------ действия

    def _key(self) -> str:
        return self._api_key() if callable(self._api_key) else self._api_key

    def _sync(self) -> None:
        self.b_del.setEnabled(self.lst.currentRow() >= 0 and self.lst.count() > 0)

    def _ask(self, current: str = "") -> str:
        dlg = SteamIdDialog(self._key(), current, tuple(self.values()), self)
        return dlg.value if dlg.exec() else ""

    def _add(self) -> None:
        sid = self._ask()
        if sid:
            self.lst.addItem(sid)
            self.lst.setCurrentRow(self.lst.count() - 1)
            self._sync()
            self.changed.emit()

    def _edit(self) -> None:
        row = self.lst.currentRow()
        if row < 0:
            return
        sid = self._ask(self.lst.item(row).text())
        if sid:
            self.lst.item(row).setText(sid)
            self.changed.emit()

    def _remove(self) -> None:
        row = self.lst.currentRow()
        if row < 0:
            return
        self.lst.takeItem(row)
        if self.lst.count():
            self.lst.setCurrentRow(min(row, self.lst.count() - 1))
        self._sync()
        self.changed.emit()
