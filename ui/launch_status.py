"""Статус запуска в журнале главной страницы: сервер, клиент, память, срывы.

Журнал запуска намеренно короткий — подробности лежат в окнах логов. Здесь
только то, что нужно видеть, не отрываясь от кнопки «Запустить»:

    Сервер: [KR] test TEST ................ [запущен]
      Скриптовая память: 2_GameLib 0% · 3_Game 14% · 4_World 32% · 5_Mission 11%
    Клиент: DayZDiag_x64 .................. [не запустился]
      Запуск сорван: 4_World — ar_buttstocks.c(11) — Invalid statement ')'

Сервер и клиент разделены: у них свои логи в разных папках, свои наборы модов
(-serverMod клиенту не уходит) и свои лимиты — одна общая строка не сказала бы,
где именно смотреть.

Блок переписывается на месте — так же, как таблица запаковки: иначе за один
запуск в журнал улетело бы несколько десятков почти одинаковых строк.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from core import crashlog, logsource, scriptmem
from core.i18n import tr

SERVER, CLIENT = "server", "client"

_DIM = "#777777"
_ERR = "#ff6b6b"
_ENGINE = "#e5c07b"
_MIN_WIDTH = 34
_INDENT = "&nbsp;&nbsp;"

# Правило готовности общее для сервера, клиента и ожидания в LaunchWorker —
# поэтому сам слой объявлен в core/scriptmem.py
READY_LAYER = scriptmem.READY_LAYER

# Готовность стороны — то, что видно только из логов. Живёт отдельно от
# состояния процесса: процесс может существовать, а клиент при этом ещё висеть
# на загрузке.
ST_LAUNCHING, ST_CONNECTING, ST_READY = "launching", "connecting", "ready"

# Состояние процесса приходит снаружи и всегда главнее готовности: мёртвый
# процесс «запущенным» быть не может, какие бы слои он до этого ни успел
# скомпилировать. Значения — те же run/dead/off, что у индикаторов в шапке
# главного окна и у кружков мини-окна: правило на все три индикатора одно.
PROC_RUN, PROC_DEAD, PROC_OFF = "run", "dead", "off"
# Попросили закрыться и ждём: процесс ещё жив, но «запущен» он уже не в
# том смысле, в каком это слово нужно человеку.
PROC_STOPPING = "stopping"


class _Side:
    """Состояние одной стороны — сервера или клиента."""

    def __init__(self, title: str):
        self.title = title
        self.name = ""
        self.active = False
        self.ready = ST_LAUNCHING
        self.proc = PROC_OFF
        self.seen_run = False  # процесс хоть раз был живым в эту сессию
        self.usage: dict[str, scriptmem.Usage] = {}
        # Падение, из-за которого запуск действительно сорван, — только
        # несобравшийся модуль. Исключения времени выполнения сюда не попадают:
        # они запуск не срывают, их считает errors.
        self.crash: crashlog.CrashReport | None = None
        self.errors = 0  # ошибок в скриптах за эту сессию
        self.last_error: crashlog.CrashReport | None = None

    @property
    def state(self) -> str:
        """Подпись в квадратных скобках — одна на все источники."""
        if self.crash:
            return tr("status.failed", "не запустился")
        if self.proc == PROC_STOPPING:
            return tr("status.stopping", "выключается")
        if self.proc == PROC_DEAD:
            return tr("status.died", "завершился")
        if self.proc == PROC_OFF:
            return tr("status.stopped", "остановлен") if self.seen_run else tr("status.starting", "запускается")
        return {
            ST_READY: tr("status.running", "запущен"),
            ST_CONNECTING: tr("status.connecting", "подключается"),
        }.get(self.ready, tr("status.starting", "запускается"))


class LaunchStatus:
    """Живой блок статуса внутри QPlainTextEdit журнала запуска."""

    def __init__(self, view: QPlainTextEdit):
        self.view = view
        self.sides = {
            SERVER: _Side(tr("common.server", "Сервер")),
            CLIENT: _Side(tr("common.client", "Клиент")),
        }
        self._block = -1

    # ------------------------------------------------------------- отрисовка

    def _line_head(self, side: _Side) -> str:
        left = f"{side.name} ".ljust(_MIN_WIDTH, ".")
        text = html.escape(f"{side.title}: {left} [{side.state}]")
        line = f'<span style="color:#d4d4d4;">{text}</span>'
        if side.errors:
            # Ошибки в скриптах запуск не срывают — это счётчик, а не приговор.
            # Держим их рядом с состоянием: смотреть надо туда же, куда и на
            # «запущен», а не искать отдельную строку.
            cnt = html.escape(tr("status.errors", "ошибок: {n}", n=side.errors))
            line += f' <span style="color:{_ERR};">· {cnt}</span>'
        return line

    def _line_memory(self, side: _Side) -> str:
        parts = []
        for layer in scriptmem.LAYERS:
            u = side.usage.get(layer)
            if u is None:
                # слой ещё не скомпилирован — показываем прочерк, а не 0%:
                # ноль читался бы как «памяти не занято», а это не так
                parts.append(f'<span style="color:{_DIM};">{layer} —</span>')
                continue
            col = scriptmem.color(u.percent)
            weight = ";font-weight:700" if u.dangerous else ""
            parts.append(f'<span style="color:{col}{weight};">{layer} {u.percent:.0f}%</span>')
        head = html.escape(tr("status.memory", "Скриптовая память") + ": ")
        return _INDENT + f'<span style="color:#d4d4d4;">{head}</span>' + " · ".join(parts)

    def _line_crash(self, side: _Side) -> str:
        """Причина сорвавшегося запуска — из crash-лога.

        Считать `(E)`-строки в RPT смысла нет: их там 71, и 63 из них — ругань
        движка на текстуры GUI, одинаковая при любом наборе модов. Значение
        имеет ровно одно: собрались скрипты или нет, и если нет — где именно.
        """
        c = side.crash
        if not c:
            return ""
        head = html.escape(tr("status.crash_head", "Запуск сорван") + ": ")
        return _INDENT + f'<span style="color:{_ERR};font-weight:700;">{head}{html.escape(c.summary())}</span>'

    def _html(self) -> str:
        lines: list[str] = []
        for key in (SERVER, CLIENT):
            side = self.sides[key]
            if not side.active:
                continue
            lines += [ln for ln in (self._line_head(side), self._line_memory(side), self._line_crash(side)) if ln]
        return "<br>".join(lines)

    def _render(self) -> None:
        doc = self.view.document()
        if self._block < 0 or self._block >= doc.blockCount():
            return
        cursor = QTextCursor(doc.findBlockByNumber(self._block))
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        # BlockUnderCursor забирает и разделитель перед блоком — возвращаем его,
        # кроме случая самого первого блока, у которого разделителя нет
        if self._block > 0:
            cursor.insertBlock()
        cursor.insertHtml(self._html())
        cursor.endEditBlock()

    # -------------------------------------------------------------- действия

    def start(self, server_name: str = "", client_name: str = "") -> None:
        """Начинает новый блок. Пустое имя = сторона не запускается и не
        показывается вовсе — пустая строка «Клиент: [—]» только мешала бы."""
        for key, name in ((SERVER, server_name), (CLIENT, client_name)):
            side = self.sides[key]
            side.name = name
            side.active = bool(name)
            side.ready = ST_LAUNCHING
            side.proc = PROC_OFF
            side.seen_run = False
            side.usage = {}
            side.crash = None
        self.view.appendHtml(self._html())
        # индекс — по факту вставки: в пустом документе appendHtml пишет в уже
        # существующий блок 0 и нового не создаёт
        self._block = self.view.document().blockCount() - 1

    def set_running(self, side: str) -> None:
        self.sides[side].ready = ST_READY
        self._render()

    def set_connecting(self, side: str) -> None:
        """Процесс живёт, но своей работы ещё не делает.

        Для клиента запущенный процесс ничего не значит: окно может висеть на
        загрузке или вовсе не достучаться до сервера. Запущенным считаем его с
        момента, когда в его логе появится расход памяти слоя 5_Mission —
        он компилируется последним.
        """
        self.sides[side].ready = ST_CONNECTING
        self._render()

    def set_process_state(self, side: str, proc: str) -> None:
        """Живёт ли процесс — то же, что показывают шапка и кружки мини-окна.

        Приходит по таймеру главного окна, а не по событию: раньше блок узнавал
        об остановке только через переход «был жив -> исчез», и процесс, умерший
        до первой отметки, оставлял блок в «запускается» навсегда.
        """
        s = self.sides[side]
        if s.proc == proc:
            return
        s.proc = proc
        if proc == PROC_RUN:
            s.seen_run = True
        self._render()

    def set_usage(self, side: str, usage: scriptmem.Usage) -> None:
        self.sides[side].usage[usage.layer] = usage
        self._render()

    def is_ready(self, side: str) -> bool:
        """Сторона отработала запуск — по ней и красятся все индикаторы."""
        return self.sides[side].ready == ST_READY

    def set_crash(self, side: str, report) -> None:
        """Подпись менять не нужно: state её выводит сам, увидев crash."""
        self.sides[side].crash = report
        self._render()

    def add_error(self, side: str, report) -> None:
        """Ошибка в скриптах: считаем, но состояние стороны не трогаем."""
        s = self.sides[side]
        s.errors += 1
        s.last_error = report
        self._render()

    def errors(self, side: str) -> int:
        return self.sides[side].errors


class _SessionTail:
    """Хвост логов, ограниченный текущей сессией.

    Файлы, лежавшие в папке на момент старта, запоминаются и игнорируются:
    иначе в статус уехали бы данные прошлого запуска — как раз того, ради
    исправления которого запуск и повторяют.
    """

    def __init__(self, directory, pattern: str, adopt: bool = False):
        self.pattern = pattern
        # adopt — сессия началась до нас: подхватываем работающий процесс, и
        # «уже лежащий» файл как раз её и описывает. Пропускать его значило бы
        # никогда не узнать ни готовности, ни расхода памяти подхваченной
        # стороны — она навсегда осталась бы «запускается».
        self._known = set() if adopt else {str(f) for f in logsource.log_files(directory) if f.match(pattern)}
        self._tailer = logsource.LogTailer(directory, pattern_filter=pattern)

    def poll(self) -> list[str]:
        lines = self._tailer.poll()
        current = self._tailer.current
        if current is None or str(current) in self._known:
            return []  # файл этой сессии ещё не создан
        return lines


class LaunchMonitor(QObject):
    """Следит за папкой логов одной стороны: память слоёв и срыв запуска.

    Источников два, и оба нужны:

    * script_*.log — расход памяти слоёв. Клиент пишет эти строки только сюда,
      в его RPT их нет вовсе (у сервера они есть в обоих файлах). По ним же
      видно готовность: 5_Mission компилируется последним;
    * crash_<дата>.log — причина сорвавшегося запуска, с файлом и строкой.
      Заводится ровно тогда, когда запуск не удался.
    """

    usage = Signal(str, object)  # сторона, scriptmem.Usage
    danger = Signal(str, object)  # впервые перевалило за 95%
    limit = Signal(str, object)  # лимит достигнут
    crashed = Signal(str, object)  # сторона, crashlog.CrashReport — запуск сорван
    errored = Signal(str, object)  # то же, но ошибка в скриптах: запуск идёт дальше

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side
        self._dir = None
        self._tails: list[_SessionTail] = []
        self._known_crash: set[str] = set()  # crash-логи, существовавшие до запуска
        self._crashed = False
        # слои, о которых уже сказали; раздельно, иначе слой, доросший до 96% и
        # потом упёршийся в лимит, второго — главного — сообщения бы не дал
        self._warned: set[str] = set()
        self._over: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)

    def start(self, directory, adopt: bool = False) -> None:
        """adopt — сторона уже работала до нас, читаем и то, что успело написаться."""
        self.stop()
        if not directory:
            return
        self._reset()
        self._dir = Path(directory)
        # crash-логи при подхвате не считаем задним числом: они относятся к
        # чужой для нас части сессии, и вываливать их окнами задним числом
        # было бы неожиданностью на пустом месте
        self._known_crash = crashlog.crash_files(self._dir)
        self._tails = [_SessionTail(directory, p, adopt) for p in ("script_*.log", "*.RPT")]
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._tails = []

    def _reset(self) -> None:
        self._crashed = False
        self._warned.clear()
        self._over.clear()

    def _poll(self) -> None:
        if not self._tails:
            return
        self._check_crash()
        lines = [ln for tail in self._tails for ln in tail.poll()]
        for line in lines:
            u = scriptmem.parse(line)
            if not u:
                continue
            self.usage.emit(self.side, u)
            # о каждом слое предупреждаем один раз: World компилируется заново
            # при каждой смене миссии, и повторные окна были бы навязчивы
            if u.over_limit and u.layer not in self._over:
                self._over.add(u.layer)
                self._warned.add(u.layer)
                self.limit.emit(self.side, u)
            elif u.dangerous and not u.over_limit and u.layer not in self._warned:
                self._warned.add(u.layer)
                self.danger.emit(self.side, u)

    def _check_crash(self) -> None:
        """Разбирает crash-логи, появившиеся за эту сессию.

        Их два разных вида, и путать их нельзя. Несобравшийся модуль срывает
        запуск — о нём говорим один раз и громко: без скомпилированных скриптов
        игра не стартует. Исключение времени выполнения (NULL pointer и прочее)
        — обычная ошибка в коде мода: сервер работает дальше, таких за сессию
        бывает много, и место им в счётчике, а не в объявлении о провале.

        Разобранные файлы запоминаем: движок дописывает их не мгновенно, и без
        этого одно падение расползлось бы в несколько одинаковых сообщений.
        """
        if not self._dir:
            return
        for path in crashlog.all_since(self._dir, self._known_crash):
            self._known_crash.add(str(path))
            report = crashlog.parse(path)
            if crashlog.is_fatal(report):
                if self._crashed:
                    continue  # о сорванном запуске говорим один раз
                self._crashed = True
                self.crashed.emit(self.side, report)
            else:
                self.errored.emit(self.side, report)
