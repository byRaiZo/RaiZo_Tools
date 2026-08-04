"""Реестр модов: Steam Workshop + локальные, junction-подключение, .bikey."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path

from . import junction
from .settings import (
    Settings,
    MOD_SOURCES_FILE,
    MOD_DEPENDENCIES_FILE,
    MOD_FLAGS_FILE,
    MOD_FLAG_DEFS_FILE,
    MOD_WORKSHOP_IDS_FILE,
)


SOURCE_STEAM = "steam"
SOURCE_LOCAL = "local"
SOURCE_GITHUB = "github"  # скачан приложением в пользовательское хранилище

_DEFAULT_FLAG_COLOR = "#c9a227"


@dataclass
class ModFlagDef:
    """Пользовательский флаг мода — название, цвет, начертание текста и
    иконка, которыми отмечается имя мода в списках (см. ModsPanel/
    ConnectModsDialog). icon — имя константы qfluentwidgets.FluentIcon,
    пусто — без иконки."""

    id: str
    name: str
    color: str = _DEFAULT_FLAG_COLOR
    bold: bool = False
    italic: bool = False
    underline: bool = False
    icon: str = ""


def _default_flag_defs() -> list[ModFlagDef]:
    """Флаги, с которыми приложение поставляется «из коробки»."""
    return [
        ModFlagDef(id="framework", name="Framework", color="#ffaa00", bold=True, underline=True, icon="COMMAND_PROMPT"),
        ModFlagDef(id="map", name="Map", color="#00aa00", bold=True, icon="PHOTO"),
        ModFlagDef(id="admintools", name="AdminTools", color="#55aaff", bold=True, icon="MIX_VOLUMES"),
        ModFlagDef(id="exp", name="EXP", color="#55007f", italic=True, icon="SPEED_HIGH"),
    ]


def workshop_ids() -> dict[str, str]:
    """Запомненные «ключ мода -> id воркшопа», см. ModRegistry.remember_workshop_ids."""
    if MOD_WORKSHOP_IDS_FILE.is_file():
        try:
            data = json.loads(MOD_WORKSHOP_IDS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load_flag_defs() -> list[ModFlagDef]:
    if MOD_FLAG_DEFS_FILE.is_file():
        try:
            data = json.loads(MOD_FLAG_DEFS_FILE.read_text(encoding="utf-8"))
            return [
                ModFlagDef(
                    id=d["id"],
                    name=d["name"],
                    color=d.get("color", _DEFAULT_FLAG_COLOR),
                    bold=bool(d.get("bold")),
                    italic=bool(d.get("italic")),
                    underline=bool(d.get("underline")),
                    icon=d.get("icon", ""),
                )
                for d in data
            ]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
    return _default_flag_defs()


# Автоопределение флагов по известным Steam Workshop id — имена флагов (не id:
# у пользователя они могут отличаться, если флаг создан/переименован вручную).
# Применяется один раз при первом обнаружении мода (см. ModRegistry.scan) —
# дальше пользователь волен снять флаг, повторно он не навяжется.
_AUTO_FLAG_WORKSHOP_MAP: dict[str, tuple[str, ...]] = {
    "1559212036": ("Framework",),
    "2545327648": ("Framework",),
    "1625463737": ("Framework", "EXP"),
    "1564026768": ("AdminTools",),  # Community-Online-Tools
    "1828439124": ("AdminTools",),  # VPPAdminTools
    "2968284194": ("AdminTools",),
    "2829480906": ("Map",),
    "2469798930": ("Map",),
    "3101918894": ("Map",),
    "2289456201": ("Map",),
    "2153795105": ("Map",),
    "2941620614": ("Map",),
    "2727569951": ("Map",),
    "1602372402": ("Map",),
    "2415195639": ("Map",),
}


def save_flag_defs(defs: list[ModFlagDef]) -> None:
    MOD_FLAG_DEFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "id": d.id,
            "name": d.name,
            "color": d.color,
            "bold": d.bold,
            "italic": d.italic,
            "underline": d.underline,
            "icon": d.icon,
        }
        for d in defs
    ]
    MOD_FLAG_DEFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_flag_order()


# Порядок флагов = порядок их описаний в настройках флагов. Кешируется:
# sort_key зовётся на каждый мод в каждом списке, читать файл столько раз
# незачем. Сбрасывается при сохранении описаний.
_FLAG_ORDER: dict[str, int] | None = None


def invalidate_flag_order() -> None:
    global _FLAG_ORDER
    _FLAG_ORDER = None


def flag_order() -> dict[str, int]:
    global _FLAG_ORDER
    if _FLAG_ORDER is None:
        _FLAG_ORDER = {d.id: i for i, d in enumerate(load_flag_defs())}
    return _FLAG_ORDER


def sort_key(mod: ModInfo) -> tuple:
    """Порядок модов по умолчанию — один на все списки в приложении.

    Помеченные флагами идут первыми: флаг ставят как раз тому, что нужно
    держать на виду (карты, фреймворки, админки), и искать их глазами среди
    сотни воркшопных подписок неудобно.

    Внутри помеченных моды группируются по флагам — вперемешку они дают ту же
    кашу, от которой уходили. Порядок групп берётся из настроек флагов, так
    что его задаёт сам пользователь.

    Группа — весь набор флагов мода, а не старший из них: иначе «STALKER +
    Мои» встал бы вперемешку с просто «Мои», раз старший флаг у них общий.
    Флаги без описания уходят в конец помеченных.
    """
    if not mod.flags:
        return (1, (), mod.name.lower())
    order = flag_order()
    ranks = tuple(sorted(order[f] for f in mod.flags if f in order))
    return (0, ranks or (len(order),), mod.name.lower())


@dataclass
class ModInfo:
    name: str  # отображаемое имя, оно же имя @папки при подключении
    path: str  # реальная папка мода
    source: str  # steam | local | github
    group: str = ""  # группа в дереве: Steam / GitHub / имя папки
    workshop_id: str = ""
    has_keys: bool = False
    duplicate_of_steam: str = ""  # id, если локальный мод дублирует воркшопный
    sources: list[str] = field(default_factory=list)  # папки сорсов (для запаковки)
    dependencies: list[str] = field(default_factory=list)  # ключи модов (folder_name.lower()),
    # от которых зависит этот — задаётся вручную для локальных модов (у Steam-модов
    # зависимости вместо этого разрешаются на лету через steam_api, см. mods_panel.py)
    is_server: bool = False  # по умолчанию подключать в -serverMod, а не в -mod
    flags: list[str] = field(default_factory=list)  # id пользовательских флагов (ModFlagDef.id)
    problem: str = ""  # причина невалидности (нет addons/.pbo и т.п.), пусто — всё ок
    size_bytes: int = 0  # суммарный размер папки мода на диске
    pbo_names: list[str] = field(default_factory=list)  # имена .pbo в addons
    mtime: float = 0.0  # дата последнего изменения файлов мода (эпоха, локально на диске)
    outdated: bool = False  # для Steam: в Workshop есть более новая версия (см. steam_api)

    @property
    def valid(self) -> bool:
        return not self.problem

    @property
    def can_have_sources(self) -> bool:
        """Можно ли привязать к моду папки сорсов.

        Сорсы — это то, что мы сами пересобираем в pbo. Мод карты, скачанный
        приложением с GitHub, приходит уже собранным и обновляется целиком
        новой загрузкой; собирать его из сорсов мы не умеем и не должны.
        Воркшопные моды не наши по той же причине.
        """
        return self.source == SOURCE_LOCAL

    @property
    def pbo_count(self) -> int:
        return len(self.pbo_names)

    @property
    def folder_name(self) -> str:
        n = self.name if self.name.startswith("@") else "@" + self.name
        # символы, недопустимые в имени папки Windows
        return re.sub(r'[<>:"/\\|?*]', "_", n)


def _read_meta_name(mod_dir: Path) -> str:
    """Имя стим-мода из meta.cpp (запасной вариант — mod.cpp)."""
    for fname in ("meta.cpp", "mod.cpp"):
        f = mod_dir / fname
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                m = re.search(r'name\s*=\s*"([^"]+)"', text)
                if m:
                    return m.group(1).strip()
            except OSError:
                pass
    return ""


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def scan_mod_stats(mod_dir: Path) -> tuple[list[str], int, float]:
    """Имена .pbo в addons (топ-уровень), суммарный размер и дата последнего
    изменения (самый свежий mtime файла) всей папки мода."""
    pbo_names: list[str] = []
    try:
        for child in mod_dir.iterdir():
            if child.is_dir() and child.name.lower() == "addons":
                pbo_names = sorted(f.name for f in child.iterdir() if f.is_file() and f.suffix.lower() == ".pbo")
                break
    except OSError:
        pass
    total = 0
    newest = 0.0
    try:
        for root, _dirs, files in os.walk(mod_dir):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                    mt = os.path.getmtime(fp)
                    if mt > newest:
                        newest = mt
                except OSError:
                    pass
    except OSError:
        pass
    return pbo_names, total, newest


def validate_mod_dir(p: Path) -> str:
    """Проверка правил локального мода. Возвращает текст проблемы или пустую строку.

    Правила: имя с @, внутри папка addons с .pbo, никаких не-ASCII символов.
    """
    from .i18n import tr

    if not p.name.startswith("@"):
        return tr("mods.val_at", "{n}: имя папки должно начинаться с @", n=p.name)
    if not all(ord(c) < 128 for c in p.name):
        return tr("mods.val_ascii", "{n}: в имени папки недопустимы русские символы", n=p.name)
    addons = None
    for child in p.iterdir() if p.is_dir() else []:
        if child.is_dir() and child.name.lower() == "addons":
            addons = child
            break
    if addons is None:
        return tr("mods.val_addons", "{n}: внутри нет папки addons", n=p.name)
    if not any(f.suffix.lower() == ".pbo" for f in addons.iterdir() if f.is_file()):
        return tr("mods.val_pbo", "{n}: в addons нет ни одного .pbo", n=p.name)
    return ""


def _is_link(p: Path) -> bool:
    """True для junction/symlink."""
    try:
        # is_junction появился в Python 3.12; на 3.11 отработает ветка ниже
        return p.is_junction() or p.is_symlink()  # type: ignore[attr-defined]
    except AttributeError:
        try:
            return p.is_symlink() or bool(p.stat(follow_symlinks=False).st_reparse_tag)
        except (OSError, AttributeError):
            return False


class ModRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mods: dict[str, ModInfo] = {}  # ключ — folder_name без учёта регистра
        self.hidden: dict[str, ModInfo] = {}  # скрытые вручную — для HiddenModsDialog
        # (показать реальное имя, а не голый ключ), см. п.4 scan()

    # ------------------------------------------------------------- сканирование

    def scan(
        self, progress: Callable[[str], None] | None = None, cancel: Callable[[], bool] | None = None
    ) -> list[ModInfo]:
        """Пересобирает реестр модов, обходя все папки на диске.

        progress зовётся с именем очередного мода, cancel — признак «бросай».
        Оба нужны фоновому обходу: считаются размер и дата каждого файла в
        каждом моде (у автора этих строк — 1750 файлов на 18.8 ГБ), и на
        холодном кеше или внешнем диске это уже не доли секунды.
        """
        self.mods = {}
        sources_map = self._load_sources_map()

        def stop() -> bool:
            return bool(cancel and cancel())

        # 1. Steam Workshop
        for wdir in self.settings.workshop_dirs:
            wpath = Path(wdir)
            if not wpath.is_dir():
                continue
            for item in wpath.iterdir():
                if not item.is_dir():
                    continue
                if stop():
                    return self.all()
                name = _read_meta_name(item) or item.name
                if progress:
                    progress(name)
                pbo_names, size_bytes, mtime = scan_mod_stats(item)
                mod = ModInfo(
                    name=name,
                    path=str(item),
                    source=SOURCE_STEAM,
                    group="Steam",
                    workshop_id=item.name,
                    has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                    pbo_names=pbo_names,
                    size_bytes=size_bytes,
                    mtime=mtime,
                )
                self.mods[mod.folder_name.lower()] = mod

        # 2. Локальные @папки в корнях клиента и сервера (junction пропускаем —
        #    это наши же ссылки на воркшоп или на другие локальные моды),
        #    настроенные папки локальных модов и скачанные с GitHub
        from .layout import mods_dl_dir

        roots = [
            self.settings.client_stable,
            self.settings.client_exp,
            self.settings.server_stable,
            self.settings.server_exp,
        ]
        scan_dirs: list[tuple[Path, str, str]] = []  # (папка, источник, группа)
        for root in roots:
            if root and Path(root).is_dir():
                scan_dirs.append((Path(root), SOURCE_LOCAL, Path(root).name))
        singles: list[tuple[Path, str, str]] = []  # одиночные @папки-моды
        for d in self.settings.local_mods_dirs:
            p = Path(d) if d else None
            if not p or not p.is_dir():
                continue
            if p.name.startswith("@"):
                singles.append((p, SOURCE_LOCAL, p.parent.name))
            else:
                scan_dirs.append((p, SOURCE_LOCAL, p.name))
        dl = mods_dl_dir(self.settings)
        if dl.is_dir():
            scan_dirs.append((dl, SOURCE_GITHUB, "GitHub"))

        def _add_local(item: Path, source: str, group: str) -> None:
            if progress:
                progress(item.name)
            key = item.name.lower()
            dup = ""
            if key in self.mods and self.mods[key].source == SOURCE_STEAM:
                dup = self.mods[key].workshop_id  # локальный приоритетнее, помечаем дубль
            pbo_names, size_bytes, mtime = scan_mod_stats(item)
            self.mods[key] = ModInfo(
                name=item.name.lstrip("@"),
                path=str(item),
                source=source,
                group=group,
                has_keys=(item / "keys").is_dir() or (item / "Keys").is_dir(),
                duplicate_of_steam=dup,
                problem=validate_mod_dir(item),  # проверяется при каждом скане
                pbo_names=pbo_names,
                size_bytes=size_bytes,
                mtime=mtime,
            )

        for rpath, source, group in scan_dirs:
            if stop():
                return self.all()
            for item in rpath.iterdir():
                # is_dir() уже возвращает False для битых ссылок — отдельно
                # проверять _is_link не нужно, а рабочие junction-ссылки на
                # реальные сборки (частый способ организовать локальные моды)
                # пропускать не должны
                if not item.name.startswith("@") or not item.is_dir():
                    continue
                _add_local(item, source, group)
        for item, source, group in singles:
            if item.is_dir():
                _add_local(item, source, group)

        # 3. Привязка сорсов, зависимостей и флагов (сервер/пользовательские)
        deps_map = self._load_dependencies_map()
        flags_map = self._load_flags_map()
        for key, mod in self.mods.items():
            if key in sources_map:
                mod.sources = sources_map[key]
            if key in deps_map:
                mod.dependencies = deps_map[key]
            if key in flags_map:
                entry = flags_map[key]
                mod.is_server = bool(entry.get("server"))
                # "library" — старый формат (bool) до введения пользовательских
                # флагов; переносим как обычный флаг с id "library"
                flags = list(entry.get("flags", []))
                if entry.get("library") and "library" not in flags:
                    flags.append("library")
                mod.flags = flags

        # 3б. Автоопределение флагов по известным Steam id — только для
        # модов, у которых ещё вообще нет своей записи в mod_flags.json
        # (иначе повторно навязывали бы флаг, который пользователь снял)
        name_to_flag_id = {d.name.lower(): d.id for d in load_flag_defs()}
        auto_dirty = False
        for key, mod in self.mods.items():
            if key in flags_map:
                continue
            tag_names: tuple[str, ...] | None
            if mod.source == SOURCE_GITHUB:
                # в mods_dl лежит только то, что приложение само качало под
                # пустую карту — это всегда мод карты
                tag_names = ("Map",)
            elif mod.source == SOURCE_STEAM and mod.workshop_id:
                tag_names = _AUTO_FLAG_WORKSHOP_MAP.get(mod.workshop_id)
            else:
                tag_names = None
            if not tag_names:
                continue
            for tname in tag_names:
                fid = name_to_flag_id.get(tname.lower())
                if fid and fid not in mod.flags:
                    mod.flags.append(fid)
                    auto_dirty = True
        if auto_dirty:
            self.save_flags()

        # Запоминаем id воркшопа до сокрытия: скрытый мод остаётся подпиской,
        # и его id пригодится ровно так же, как у видимого.
        self.remember_workshop_ids()

        # 4. Моды, скрытые вручную (папка/подписка остаётся — просто не показываем)
        self.hidden = {}
        for key in self.settings.excluded_mods:
            m = self.mods.pop(key, None)
            if m:
                self.hidden[key] = m

        return self.all()

    def all(self) -> list[ModInfo]:
        return sorted(self.mods.values(), key=sort_key)

    def get(self, name: str) -> ModInfo | None:
        n = name if name.startswith("@") else "@" + name
        return self.mods.get(n.lower())

    def index_of(self, mod: ModInfo, names: list[str]) -> int | None:
        """Позиция мода в списке имён пресета (mods/server_mods) — сравнение
        по folder_name, а не по имени из списка (могло устареть)."""
        for i, n in enumerate(names):
            got = self.get(n)
            if got and got.folder_name == mod.folder_name:
                return i
        return None

    # ------------------------------------------------------------- сорсы модов

    def _load_sources_map(self) -> dict[str, list[str]]:
        if MOD_SOURCES_FILE.is_file():
            try:
                return json.loads(MOD_SOURCES_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_sources(self) -> None:
        MOD_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: m.sources for k, m in self.mods.items() if m.sources}
        MOD_SOURCES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # --------------------------------------------------- память id воркшопа

    def remember_workshop_ids(self) -> None:
        """Дописывает «ключ мода -> id воркшопа» по всем найденным стим-модам.

        Зависимости хранятся ключами вида «@cf», а id воркшопа живёт только в
        реестре. Стоит отписаться от мода — папка исчезает, ключ перестаёт
        находиться, и предложить подписку уже не по чему: id к тому моменту
        потерян. Поэтому помним, и только дописываем: мод, которого сейчас нет,
        из памяти вычёркивать нельзя, ради него всё и затевалось.
        """
        known = workshop_ids()
        known.update({key: m.workshop_id for key, m in self.mods.items() if m.source == SOURCE_STEAM and m.workshop_id})
        try:
            MOD_WORKSHOP_IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
            MOD_WORKSHOP_IDS_FILE.write_text(
                json.dumps(known, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass  # не смогли запомнить — не повод ронять пересканирование

    # ------------------------------------------------------- зависимости модов

    def _load_dependencies_map(self) -> dict[str, list[str]]:
        if MOD_DEPENDENCIES_FILE.is_file():
            try:
                return json.loads(MOD_DEPENDENCIES_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_dependencies(self) -> None:
        MOD_DEPENDENCIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: m.dependencies for k, m in self.mods.items() if m.dependencies}
        MOD_DEPENDENCIES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------- флаги модов (сервер/библиотека)

    def _load_flags_map(self) -> dict[str, dict]:
        if MOD_FLAGS_FILE.is_file():
            try:
                return json.loads(MOD_FLAGS_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_flags(self) -> None:
        MOD_FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {k: {"server": m.is_server, "flags": m.flags} for k, m in self.mods.items() if m.is_server or m.flags}
        MOD_FLAGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------- подключение

    def ensure_available(self, mod: ModInfo, root: str) -> tuple[bool, str]:
        """Гарантирует junction на мод в <DayZServer>/MODS/@Имя.

        Чужие ссылки и настоящие папки не заменяются.
        """
        from .layout import mods_link_dir

        link_dir = mods_link_dir(root)
        try:
            link_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, str(e)
        link = link_dir / mod.folder_name
        target = Path(mod.path)

        if link.exists():
            try:
                if link.resolve() == target.resolve():
                    return True, ""
            except OSError:
                pass
            kind = "чужая ссылка" if _is_link(link) else "настоящая папка"
            return False, f"{link}: уже существует {kind}; RaiZo Tools её не заменяет"
        err = junction.create(link, target)
        return (False, err) if err else (True, "")

    def copy_keys(self, mod: ModInfo, server_root: str) -> None:
        """Копирует .bikey мода в keys сервера (для verifySignatures)."""
        dest = Path(server_root) / "keys"
        if not dest.is_dir():
            dest = Path(server_root) / "Keys"
        if not dest.is_dir():
            return
        for kdir in (Path(mod.path) / "keys", Path(mod.path) / "Keys"):
            if kdir.is_dir():
                for key in kdir.glob("*.bikey"):
                    try:
                        shutil.copy2(key, dest / key.name)
                    except OSError:
                        pass
