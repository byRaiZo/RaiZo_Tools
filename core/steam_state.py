"""Состояние установок и загрузок Steam — по локальным файлам клиента.

Steam Web API про загрузки у конкретного пользователя не знает ничего: он
описывает только облако (что опубликовано в воркшопе, размер, дата). Зато
клиент держит всё нужное в текстовых файлах библиотеки:

    steamapps/appmanifest_<appid>.acf        — игра/сервер/тулзы
    steamapps/workshop/appworkshop_<appid>.acf — моды воркшопа
    steamapps/downloading/<appid>/            — существует, пока идёт загрузка
    steamapps/workshop/downloads/<appid>/<id>/ — то же для мода

Отсюда читаются и факт установки, и прогресс в байтах, и момент завершения.
Проверено вживую: при установке DayZ Server StateFlags менялся 1026 -> 4,
BytesDownloaded дорастал до BytesToDownload, папка downloading/ исчезала.

Прогресс по каждому отдельному моду воркшопа Steam на диск не пишет — там
доступно только «качается / установлен».
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from collections.abc import Iterable
from pathlib import Path

# Биты AppState.StateFlags (нужные нам; остальные для наших задач не важны)
STATE_UNINSTALLED = 1
STATE_UPDATE_REQUIRED = 2
STATE_FULLY_INSTALLED = 4
STATE_UPDATE_RUNNING = 1024

_KV_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*(?:"((?:[^"\\]|\\.)*)")?')


def parse_vdf(text: str) -> dict:
    """Разбор текстового VDF (формат .acf) в словарь вложенных словарей.

    Своя реализация, а не библиотека vdf: формат тривиальный, а лишняя
    зависимость ради двух файлов не нужна. Значения — всегда строки.
    """
    root: dict = {}
    stack: list[dict] = [root]
    pending: str | None = None  # ключ, за которым ждём открывающую скобку

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("{"):
            node: dict = {}
            if pending is not None:
                stack[-1][pending] = node
                pending = None
            stack.append(node)
            continue
        if line.startswith("}"):
            if len(stack) > 1:
                stack.pop()
            continue

        m = _KV_RE.match(line)
        if not m:
            continue
        key = m.group(1).replace("\\\\", "\\").replace('\\"', '"')
        val = m.group(2)
        if val is None:
            pending = key  # секция, скобка на следующей строке
        else:
            stack[-1][key] = val.replace("\\\\", "\\").replace('\\"', '"')
    return root


def _read_vdf(path: Path) -> dict:
    """Чтение .acf с оглядкой на то, что Steam пишет их асинхронно.

    Рядом с файлом можно увидеть appworkshop_221100.acf.async16240.tmp — в
    момент подмены файл легко прочитать полупустым, поэтому любая ошибка
    здесь означает «сейчас данных нет», а не аварию.
    """
    try:
        return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


# --------------------------------------------------------------- библиотеки


def steam_root() -> Path | None:
    """Папка установки Steam по реестру."""
    try:
        import winreg
    except ImportError:
        return None
    for hive, key, name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                p = Path(winreg.QueryValueEx(k, name)[0])
                if p.is_dir():
                    return p
        except OSError:
            continue
    return None


_LIB_CACHE: tuple[float, list[Path]] | None = None
_LIB_TTL = 30.0  # состав библиотек меняется редко, а опрос идёт раз в пару секунд


def libraries(refresh: bool = False) -> list[Path]:
    """Все библиотеки Steam (папки, внутри которых лежит steamapps).

    Результат кэшируется: список меняется только при подключении новой
    библиотеки, а дёргать реестр на каждом тике опроса ни к чему.
    """
    global _LIB_CACHE
    if not refresh and _LIB_CACHE and time.monotonic() - _LIB_CACHE[0] < _LIB_TTL:
        return _LIB_CACHE[1]

    root = steam_root()
    libs: list[Path] = []
    if root:
        libs.append(root)
        data = _read_vdf(root / "steamapps" / "libraryfolders.vdf")
        for entry in data.get("libraryfolders", {}).values():
            if not isinstance(entry, dict):
                continue
            p = entry.get("path")
            if p and Path(p).is_dir() and Path(p) not in libs:
                libs.append(Path(p))
    _LIB_CACHE = (time.monotonic(), libs)
    return libs


# ------------------------------------------------------- состояние приложения


@dataclass
class AppState:
    appid: str
    name: str = ""
    path: str = ""  # полный путь к папке установки
    library: str = ""
    flags: int = 0
    bytes_downloaded: int = 0
    bytes_to_download: int = 0
    bytes_staged: int = 0
    bytes_to_stage: int = 0
    size_on_disk: int = 0
    active: bool = False  # есть steamapps/downloading/<appid> — качается прямо сейчас

    @property
    def installed(self) -> bool:
        """Установлено полностью. Во время докачки папка уже существует,
        поэтому наличие пути само по себе ничего не доказывает."""
        return bool(self.flags & STATE_FULLY_INSTALLED) and Path(self.path).is_dir()

    @property
    def downloading(self) -> bool:
        return self.active or bool(self.flags & STATE_UPDATE_RUNNING)


def _int(d: dict, key: str) -> int:
    try:
        return int(d.get(key, "0"))
    except (TypeError, ValueError):
        return 0


def _state_in_lib(lib: Path, appid: str) -> AppState | None:
    manifest = lib / "steamapps" / f"appmanifest_{appid}.acf"
    if not manifest.is_file():
        return None
    st = _read_vdf(manifest).get("AppState")
    if not isinstance(st, dict):
        return None
    installdir = st.get("installdir", "")
    return AppState(
        appid=appid,
        name=st.get("name", ""),
        path=str(lib / "steamapps" / "common" / installdir) if installdir else "",
        library=str(lib),
        flags=_int(st, "StateFlags"),
        bytes_downloaded=_int(st, "BytesDownloaded"),
        bytes_to_download=_int(st, "BytesToDownload"),
        bytes_staged=_int(st, "BytesStaged"),
        bytes_to_stage=_int(st, "BytesToStage"),
        size_on_disk=_int(st, "SizeOnDisk"),
        active=(lib / "steamapps" / "downloading" / appid).is_dir(),
    )


def app_state(appid: str) -> AppState | None:
    """Состояние приложения по appid; None — Steam про него не знает.

    Манифест ищется по всем библиотекам: пользователь мог выбрать при
    установке любую из них, и угадывать её по имени папки не нужно.
    """
    for lib in libraries():
        st = _state_in_lib(lib, appid)
        if st is not None:
            return st
    return None


def app_states(appids: Iterable[str]) -> dict[str, AppState]:
    """Состояния сразу нескольких приложений за один обход библиотек."""
    res: dict[str, AppState] = {}
    pending = list(dict.fromkeys(appids))
    for lib in libraries():
        for appid in list(pending):
            st = _state_in_lib(lib, appid)
            if st is not None:
                res[appid] = st
                pending.remove(appid)
        if not pending:
            break
    return res


# ------------------------------------------------------------ Workshop


@dataclass
class WorkshopState:
    installed: dict[str, int] = field(default_factory=dict)  # id -> размер на диске
    outdated: set[str] = field(default_factory=set)  # есть обновление
    downloading: set[str] = field(default_factory=set)  # качается прямо сейчас
    content_dirs: list[str] = field(default_factory=list)  # workshop/content/<appid>


def workshop_state(appid: str) -> WorkshopState:
    """Что из воркшопа скачано, что качается, чему нужно обновление.

    Побайтового прогресса по отдельному моду Steam не хранит, поэтому
    downloading — это просто «папка загрузки существует».
    """
    res = WorkshopState()
    for lib in libraries():
        ws = lib / "steamapps" / "workshop"
        content = ws / "content" / appid
        if content.is_dir():
            res.content_dirs.append(str(content))

        dl = ws / "downloads" / appid
        if dl.is_dir():
            try:
                res.downloading.update(p.name for p in dl.iterdir())
            except OSError:
                pass

        data = _read_vdf(ws / f"appworkshop_{appid}.acf").get("AppWorkshop")
        if not isinstance(data, dict):
            continue

        for item_id, info in (data.get("WorkshopItemsInstalled") or {}).items():
            if isinstance(info, dict):
                res.installed[item_id] = _int(info, "size")

        for item_id, info in (data.get("WorkshopItemDetails") or {}).items():
            if not isinstance(info, dict):
                continue
            # манифест разошёлся с последним опубликованным — мод устарел
            latest = info.get("latest_manifest")
            if latest and latest != info.get("manifest"):
                res.outdated.add(item_id)
    # то, что уже докачалось, в «качается» показывать незачем
    res.downloading -= set(res.installed)
    return res
