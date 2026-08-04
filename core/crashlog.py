"""Crash-лог DayZ — единственное место, где написано, почему запуск не удался.

Движок заводит `crash_<дата>.log` в папке профиля только когда запуск
действительно сорвался. Внутри — причина и, что важнее всего, файл со строкой:

    DESKTOP-S9UD2IO, 20.07 2026 23:10:10
    Can't compile "World" script module!

    KR/kr_data/scripts/4_World/…/ar_buttstocks.c(11): Invalid statement ')'

Из 18 накопившихся crash-логов 17 — именно несобравшийся слой, и в каждом
указан конкретный файл и номер строки. Это на порядок полезнее, чем счётчик
`(E)`-строк в RPT: там 71 строка, из которых 63 — ругань движка на текстуры
GUI, одинаковая при любом наборе модов.

Второй вид — `Virtual Machine Exception`: скрипты собрались, но упали в
рантайме; там есть причина, класс и стек вызовов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .scriptmem import MODULES

COMPILE, EXCEPTION, OTHER = "compile", "exception", "other"

_HEAD_RE = re.compile(r"^\S+,\s+\d{2}\.\d{2}\s+\d{4}\s")
_COMPILE_RE = re.compile(r"""Can't compile\s+"(?P<mod>\w+)"\s+script module""", re.IGNORECASE)
# «KR/…/ar_buttstocks.c(11): Invalid statement ')'»
_WHERE_RE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+)\):\s*(?P<msg>.+)$")
_REASON_RE = re.compile(r"^Reason:\s*(?P<msg>.+)$")


@dataclass
class CrashReport:
    """Разобранный crash-лог."""

    path: Path
    kind: str = OTHER
    layer: str = ""  # 4_World и т.п., если движок назвал слой
    file: str = ""  # файл со сломанным кодом
    line: int = 0
    message: str = ""  # сама причина
    headline: str = ""  # первая строка тела — как её написал движок

    @property
    def where(self) -> str:
        """«ar_buttstocks.c(11)» — коротко, без длинного пути к моду."""
        if not self.file:
            return ""
        return f"{Path(self.file.replace(chr(92), '/')).name}({self.line})"

    def summary(self) -> str:
        parts = [self.layer or self.headline]
        if self.where:
            parts.append(self.where)
        if self.message:
            parts.append(self.message)
        return " — ".join(p for p in parts if p)


def parse(path: Path) -> CrashReport:
    """Разбирает crash-лог. Нераспознанный формат не теряется: headline и
    message заполняются как есть, чтобы пользователь увидел текст движка."""
    rep = CrashReport(path=path)
    try:
        lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    except OSError:
        return rep
    # тело начинается после строки «ХОСТ, дд.мм гггг чч:мм:сс»
    start = next((i for i, ln in enumerate(lines) if _HEAD_RE.match(ln)), None)
    if start is None:
        return rep
    body = [ln.strip() for ln in lines[start + 1 :]]
    body = [ln for ln in body if ln and not ln.startswith(("Runtime mode", "CLI params"))]
    if not body:
        return rep
    rep.headline = body[0]

    m = _COMPILE_RE.search(body[0])
    if m:
        rep.kind = COMPILE
        rep.layer = MODULES.get(m.group("mod"), m.group("mod"))
        for ln in body[1:]:
            w = _WHERE_RE.match(ln)
            if w:
                rep.file, rep.line = w.group("file"), int(w.group("line"))
                rep.message = w.group("msg")
                break
        return rep

    if "exception" in body[0].lower():
        rep.kind = EXCEPTION
        rep.headline = body[0]
        for ln in body[1:]:
            r = _REASON_RE.match(ln)
            if r:
                rep.message = r.group("msg")
                break
        return rep

    rep.message = body[1] if len(body) > 1 else ""
    return rep


def crash_files(directory: Path) -> set[str]:
    """Пути ко всем crash-логам в папке — снимок для сравнения «до/после»."""
    if not directory or not Path(directory).is_dir():
        return set()
    return {str(p) for p in Path(directory).glob("crash_*.log")}


def newest_since(directory: Path, known: set[str]) -> Path | None:
    """Самый свежий crash-лог, которого не было в снимке known."""
    fresh = [Path(p) for p in crash_files(directory) - known]
    if not fresh:
        return None
    return max(fresh, key=lambda p: p.stat().st_mtime if p.exists() else 0)


def all_since(directory: Path, known: set[str]) -> list[Path]:
    """Все crash-логи, которых не было в снимке known, от старых к новым.

    Нужны все, а не только свежий: исключения времени выполнения запуск не
    срывают, их за сессию набирается сколько угодно, и каждое считается.
    """
    fresh = [Path(p) for p in crash_files(directory) - known]
    return sorted(fresh, key=lambda p: p.stat().st_mtime if p.exists() else 0)


def is_fatal(report: CrashReport) -> bool:
    """Сорвался ли из-за этого запуск.

    Не собравшийся модуль — да: без скомпилированных скриптов игра не
    стартует вовсе. Исключение времени выполнения (Virtual Machine Exception,
    NULL pointer to instance) — нет: движок продолжает работать, а это ошибка
    в коде мода, каких за сессию бывает много. Путать их значит объявлять
    рабочий сервер упавшим.
    """
    return report.kind == COMPILE
