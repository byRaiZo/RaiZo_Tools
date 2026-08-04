"""Слежение за загрузками Steam для UI.

Пользователь жмёт «скачать», Steam открывается отдельным окном и дальше
приложение о нём ничего не знает — а путь к установке всё это время
остаётся пустым. Наблюдатель опрашивает манифесты Steam и сообщает, когда
компонент докачался, чтобы поле пути заполнилось само.

Опрос, а не QFileSystemWatcher: следить надо за файлами в нескольких
библиотеках, часть которых может лежать на внешних дисках, где уведомления
файловой системы работают ненадёжно. Чтение пары мелких текстовых файлов раз
в две секунды дешевле, чем разбираться с этим.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from core import steam_state
from core.i18n import tr
from core.steam_urls import SETTINGS_APPS

POLL_MS = 2000
_MISSING = object()


class SteamWatcher(QObject):
    """Опрашивает состояние компонентов DayZ и модов воркшопа.

    Работает в GUI-потоке: один тик — это чтение нескольких .acf, доли
    миллисекунды. Таймер запускается только когда есть за чем следить.
    """

    # ключ настроек -> состояние (AppState). Шлётся при любом изменении.
    app_changed = Signal(str, object)
    # ключ настроек -> путь установки. Шлётся один раз, когда компонент дошёл
    # до «установлено полностью»: по этому сигналу поле пути заполняется само.
    app_installed = Signal(str, str)
    # состояние воркшопа (WorkshopState) — при изменении состава
    workshop_changed = Signal(object)

    def __init__(self, parent=None, interval: int = POLL_MS):
        super().__init__(parent)
        self._keys: list[str] = []
        self._workshop_appid: str = ""
        self._apps: dict[str, tuple[int, int, str, bool] | None] = {}
        self._ws: tuple | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval)
        self._timer.timeout.connect(self.poll)

    # ---------------------------------------------------------------- запуск

    def watch_apps(self, keys) -> None:
        """Задаёт список полей настроек, за которыми следим."""
        self._keys = [k for k in keys if k in SETTINGS_APPS]

    def watch_workshop(self, appid: str) -> None:
        self._workshop_appid = appid

    def start(self, immediate: bool = True) -> None:
        if not self._keys and not self._workshop_appid:
            return
        if immediate:
            self.poll(initial=True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    # ----------------------------------------------------------------- опрос

    def poll(self, initial: bool = False) -> None:
        """Один цикл опроса. initial — первый снимок, без сигнала «установлено»
        (иначе при открытии окна посыплются уведомления про то, что и так стоит)."""
        if self._keys:
            self._poll_apps(initial)
        if self._workshop_appid:
            self._poll_workshop()

    def _poll_apps(self, initial: bool) -> None:
        wanted = {SETTINGS_APPS[k][0]: k for k in self._keys}
        states = steam_state.app_states(wanted)

        for appid, key in wanted.items():
            st = states.get(appid)
            snap = (st.flags, st.bytes_downloaded, st.path, st.active) if st else None
            was = self._apps.get(key, _MISSING)
            if snap == was:
                continue
            self._apps[key] = snap

            self.app_changed.emit(key, st)
            if initial or st is None or not st.installed:
                continue
            # был не установлен (или мы его не видели) и стал установлен —
            # именно этот переход и означает «загрузка завершилась»
            if (
                was is _MISSING
                or was is None
                or (isinstance(was, tuple) and not (was[0] & steam_state.STATE_FULLY_INSTALLED))
            ):
                self.app_installed.emit(key, st.path)

    def states(self) -> dict:
        """Текущее состояние отслеживаемых компонентов: ключ настроек -> AppState.

        Отсутствующий ключ означает, что Steam про компонент ничего не знает.
        """
        wanted = {SETTINGS_APPS[k][0]: k for k in self._keys}
        return {wanted[appid]: st for appid, st in steam_state.app_states(wanted).items()}

    def _poll_workshop(self) -> None:
        ws = steam_state.workshop_state(self._workshop_appid)
        snap = (frozenset(ws.installed), frozenset(ws.downloading), frozenset(ws.outdated))
        if snap == self._ws:
            return
        self._ws = snap
        self.workshop_changed.emit(ws)


def status_text(st) -> str:
    """Строка состояния под полем пути; пусто — показывать нечего.

    Без прогресса: BytesDownloaded в манифесте держится нулём до самого конца
    загрузки (проверено на живой установке), так что показывать было бы нечего,
    кроме застывшего «0%». Нам важен сам факт — по завершении путь подставится.
    """
    if st is None or not st.downloading:
        return ""
    return tr("steam.dl_running", "Скачивание началось")
