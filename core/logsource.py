"""Источники логов: поиск папок, живой хвост с подхватом нового файла сессии."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from .presets import ServerPreset
from .settings import Settings, EXPERIMENTAL

# Файлы логов DayZ. Почти все — новый файл на сессию, с меткой времени в
# имени; server_console.log единственный с постоянным именем: движок пишет
# в него консольный вывод сервера (имя задаётся logFile в serverDZ.cfg).
LOG_PATTERNS = ("*.RPT", "script*.log", "*.ADM", "crash*.log", "error.log", "server_console.log")

# Что показывать живым хвостом в окне логов. Консоль сервера — то, что у
# обычного серверного ПО видно прямо в терминале: подключения игроков,
# сообщения движка. DayZ консоли не имеет вовсе (все три его exe собраны как
# GUI-приложения, subsystem=2), поэтому перехватить их вывод нечем — движок
# сам кладёт его в этот файл.
TAIL_PATTERNS = ("script_*.log", "server_console.log")

# Что можно выбрать в окне логов. Порядок — порядок в выпадающем списке, первый
# показывается по умолчанию: скриптовый лог отвечает на вопрос «что не так с
# модом», а два других нужны реже.
#
#   script — ошибки скриптов, ради них окно и открывают
#   crash  — почему запуск сорвался; файл появляется только при обвале
#   RPT    — полный журнал движка: всё подряд, включая ругань на текстуры
KINDS: dict[str, tuple[str, ...]] = {
    "script": ("script_*.log",),
    "console": ("server_console.log",),
    "adm": ("*.ADM",),
    "crash": ("crash_*.log",),
    "rpt": ("*.RPT",),
}

# Строка, с которой движок начинает каждую сессию в server_console.log. Файл
# общий для всех запусков, и без этой отметки нельзя отличить сегодняшнюю
# сессию от вчерашней.
CONSOLE_SESSION_MARK = "SteamGameServer_Init"

# Виды, которые есть только у сервера. Консоль пишет он один — её задаёт
# logFile в serverDZ.cfg; у клиента такого файла нет вовсе, и предлагать этот
# пункт в его окне значило бы обещать несуществующее.
SERVER_ONLY_KINDS = ("console", "adm")


def files_of_kind(directory: Path | None, kind: str) -> list[Path]:
    """Файлы выбранного вида, новые первыми."""
    if not directory or not Path(directory).is_dir():
        return []
    out: list[Path] = []
    for pattern in KINDS.get(kind, ()):
        out.extend(Path(directory).glob(pattern))
    out.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)
    return out


def newest_of_kind(directory: Path | None, kind: str) -> Path | None:
    files = files_of_kind(directory, kind)
    return files[0] if files else None


# Признаки уровня строки. Это простой поиск подстрок, а не разбор: регулярка
# из одних литералов, склеенных через «|», делает ровно то же самое, но втрое
# дольше — а classify зовётся на каждой строке лога.
_ERROR_WORDS = ("error", "critical", "fatal", "exception", "can't", "cannot find", "missing")
_WARN_WORDS = ("warning", "obsolete", "deprecated", "unable to")


def classify(line: str) -> str:
    """info | warning | error — для цветовой дифференциации."""
    low = line.lower()
    if any(w in low for w in _ERROR_WORDS):
        return "error"
    if any(w in low for w in _WARN_WORDS):
        return "warning"
    return "info"


def server_log_dir(preset: ServerPreset, settings: Settings, branch: str) -> Path | None:
    from .layout import resolve_profiles

    p = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    return Path(p) if p else None


def client_log_dir(branch: str) -> Path | None:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    # У Experimental-клиента своя папка (уточняется; DayZ Exp — наиболее вероятное имя)
    name = "DayZ Exp" if branch == EXPERIMENTAL else "DayZ"
    p = Path(local) / name
    if branch == EXPERIMENTAL and not p.is_dir():
        p = Path(local) / "DayZ"
    return p


def log_files(directory: Path) -> list[Path]:
    """Все файлы логов в папке, новые первыми."""
    files: list[Path] = []
    if directory and directory.is_dir():
        for pattern in LOG_PATTERNS:
            files.extend(directory.glob(pattern))
    files = list(set(files))
    files.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)
    return files


# Сколько байт забирать за один опрос. Лог сервера за сессию набирает сотни
# мегабайт, и проглотить их целиком одним чтением — это и всплеск памяти, и
# застывший интерфейс. Хвост дочитывается следующими тактами: опрос идёт два
# раза в секунду, отставание рассасывается само.
_CHUNK = 1 << 20  # 1 МБ

# Предел на строку без перевода. Обычно недописанная строка — это последние
# байты, которые движок вот-вот допишет. Но если файл вообще без переносов,
# ждать нечего: отдаём как есть, иначе буфер рос бы бесконечно.
_MAX_LINE = 1 << 20

# Сколько байт начала файла держать как отпечаток для проверки подмены
_SIG = 64


class LogTailer:
    """Читает лог инкрементально; при появлении более нового файла переключается на него.

    Файл открывается в двоичном режиме и разбирается на строки вручную. Причин
    две. Первая: в текстовом режиме tell() возвращает непрозрачный маркер, а не
    смещение в байтах, и сравнивать его с размером файла из stat() нельзя —
    на кириллице они расходятся. Вторая: опрос попадает в середину строки, и
    read().splitlines() рвал её пополам — половина уходила в окно, остаток
    приходил следующим тактом отдельной строкой.
    """

    def __init__(self, directory: Path, pattern_filter: str | None = None, start_from: str = "begin") -> None:
        """start_from — откуда читать вновь выбранный файл:

        «begin» — с начала. Годится для логов, которые движок заводит заново
            на каждый запуск: весь файл и есть текущая сессия.
        «end» — только то, что допишется дальше. Для файлов, которые движок
            ведёт непрерывно между запусками: server_console.log за день
            накапливает несколько тысяч строк от разных сессий, и вываливать
            их целиком значит показать вчерашнее как сегодняшнее.
        любая другая строка — считается признаком начала сессии: читаем с
            последнего её вхождения. Так текущая сессия находится и в общем
            файле, даже если сервер запущен до нас.
        """
        self.directory = directory
        self.pattern_filter = pattern_filter  # например "*.RPT", None = все
        self.start_from = start_from
        self.current: Path | None = None
        self._pos = 0  # сколько байт файла уже прочитано
        self._tail = b""  # недописанная строка, ждём её конца
        self._sig = b""  # начало файла — по нему видно подмену содержимого

    def _candidates(self) -> list[Path]:
        files = log_files(self.directory)
        if self.pattern_filter:
            files = [f for f in files if f.match(self.pattern_filter)]
        return files

    def _restart(self, path: Path | None) -> None:
        self.current = path
        self._pos = 0
        self._tail = b""
        self._sig = b""
        if path is None or self.start_from == "begin":
            return
        try:
            size = path.stat().st_size
            if self.start_from == "end":
                self._pos = size
                return
            # признак начала сессии: ищем его последнее вхождение
            with open(path, "rb") as f:
                data = f.read()
            mark = self.start_from.encode("utf-8", "replace")
            at = data.rfind(mark)
            if at >= 0:
                # отступаем к началу строки, иначе первая выйдет обрезанной
                self._pos = data.rfind(b"\n", 0, at) + 1
            else:
                self._pos = size
        except OSError:
            self._pos = 0

    def poll(self) -> list[str]:
        """Новые целые строки с момента прошлого вызова.

        Пустой список — не обязательно «ничего нет»: файл может быть занят
        другим процессом или только что исчезнуть. В обоих случаях молчим и
        пробуем на следующем такте, состояние не теряя.
        """
        files = self._candidates()
        if not files:
            return []
        newest = files[0]
        lines: list[str] = []

        if self.current != newest:
            self._restart(newest)  # новая сессия — файл с начала
            lines.append(f"=== {newest.name} ===")
        current = self.current
        if current is None:  # сюда не попасть: файл выбран выше
            return lines

        try:
            size = current.stat().st_size
        except OSError:
            # исчез между выбором и чтением: следующий опрос выберет другой
            return lines
        if size < self._pos:
            # стал короче — обрезан; читаем заново
            self._restart(current)

        try:
            with open(current, "rb") as f:
                # Начало файла как отпечаток. Одного размера мало: файл могут
                # переписать под тем же именем на больший объём, и тогда чтение
                # с прежнего смещения попадёт в середину чужой строки. Сравниваем
                # по общей длине — растущий файл своё начало не меняет.
                head = f.read(_SIG)
                common = min(len(head), len(self._sig))
                if common and head[:common] != self._sig[:common]:
                    self._pos = 0
                    self._tail = b""
                if len(head) > len(self._sig):
                    self._sig = head
                if size <= self._pos:
                    return lines
                f.seek(self._pos)
                data = f.read(_CHUNK)
                self._pos = f.tell()
        except OSError:
            # PermissionError — файл держит другой процесс; FileNotFoundError —
            # удалён прямо сейчас. И то и другое лечится ожиданием такта
            return lines

        buf = self._tail + data
        parts = buf.split(b"\n")
        self._tail = parts.pop()  # последняя — ещё дописывается
        if len(self._tail) > _MAX_LINE:
            parts.append(self._tail)
            self._tail = b""
        lines.extend(p.rstrip(b"\r").decode("utf-8", "replace") for p in parts)
        return lines


def search_in_files(
    directory: Path,
    query: str,
    current_only: Path | None = None,
    max_results: int = 500,
    cancel: Callable[[], bool] | None = None,
) -> list[tuple[str, int, str]]:
    """Поиск по логам. Возвращает [(имя файла, номер строки, строка)].

    cancel — функция без аргументов; вернула True, значит результат уже никому
    не нужен, и обход прекращается. Нужна интерактивному поиску: пока читается
    папка с сотнями мегабайт RPT, пользователь успевает дописать ещё пару
    символов, и прошлый запрос становится мусором.
    """
    results: list[tuple[str, int, str]] = []
    q = query.lower()
    files = [current_only] if current_only else log_files(directory)
    for f in files:
        if not f or not f.is_file() or (cancel and cancel()):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    # проверяем не на каждой строке: их миллионы, а вызов
                    # функции на каждую заметен сам по себе
                    if cancel and i % 4096 == 0 and cancel():
                        return results
                    if q in line.lower():
                        results.append((f.name, i, line.rstrip()))
                        if len(results) >= max_results:
                            return results
        except OSError:
            continue
    return results


def delete_logs(directory: Path, *, recursive: bool = True, excluded: Iterable[Path] = ()) -> int:
    """Удаляет DayZ-логи; рекурсивно, но без указанных защищённых каталогов."""
    if not directory or not directory.is_dir():
        return 0

    protected = {os.path.normcase(os.path.abspath(str(path))) for path in excluded}

    def is_protected(path: Path) -> bool:
        key = os.path.normcase(os.path.abspath(str(path)))
        return any(key == root or key.startswith(root + os.sep) for root in protected)

    suffixes = {".log", ".mdmp", ".rpt", ".adm"}
    n = 0
    if recursive:
        for current, dirs, files in os.walk(directory, topdown=True, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not is_protected(current_path / name)]
            for name in files:
                path = current_path / name
                if path.suffix.lower() not in suffixes or is_protected(path):
                    continue
                try:
                    path.unlink()
                    n += 1
                except OSError:
                    pass
    else:
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            try:
                path.unlink()
                n += 1
            except OSError:
                pass
    return n
