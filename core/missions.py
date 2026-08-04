"""Каталог миссий (GitHub), установленные миссии в mpmissions, проверка версий."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import Settings, RES_DIR

CATALOG_FILE = RES_DIR / "data" / "missions_catalog.json"
META_NAME = ".krsm_mission.json"
TEMPLATE_PREFIX = "actual"  # actual.<world> — скачанный шаблон карты


def template_name(world: str) -> str:
    return f"{TEMPLATE_PREFIX}.{world}"


# ------------------------------------------------------- db/globals.xml миссии


def _globals_xml(mission_dir: Path) -> Path:
    return Path(mission_dir) / "db" / "globals.xml"


def read_global_var(mission_dir: Path, name: str) -> str | None:
    """Значение <var name="..." value="..."/> из db/globals.xml (None — нет файла/переменной)."""
    f = _globals_xml(mission_dir)
    if not f.is_file():
        return None
    try:
        m = re.search(
            rf'<var\s+name="{re.escape(name)}"[^>]*\bvalue="([^"]*)"', f.read_text(encoding="utf-8", errors="replace")
        )
        return m.group(1) if m else None
    except OSError:
        return None


def set_global_var(mission_dir: Path, name: str, value: str) -> bool:
    """Точечно меняет value переменной в db/globals.xml. True — записано."""
    f = _globals_xml(mission_dir)
    if not f.is_file():
        return False
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
        new_text, n = re.subn(
            rf'(<var\s+name="{re.escape(name)}"[^>]*\bvalue=")[^"]*(")',
            lambda m: m.group(1) + str(value) + m.group(2),
            text,
            count=1,
        )
        if n == 0:
            return False
        if new_text != text:
            f.write_bytes(new_text.encode("utf-8"))
        return True
    except OSError:
        return False


_UA = {"User-Agent": "RaiZoTools (github.com/byRaiZo/RaiZo_Tools)"}


@dataclass
class CatalogEntry:
    id: str
    title: str
    world: str
    repo: str
    branch: str
    path: str
    # моды карты из того же репозитория: [{"path": "@ModFolder"}]
    mods: list = field(default_factory=list)
    # Steam Workshop id мода карты (для карт вроде Namalsk/DeerIsle/Banov —
    # отдельная подписка, не входит в репозиторий миссии); пусто — не нужен
    map_mod: str = ""


@dataclass
class InstalledMission:
    name: str  # имя папки, например myserver.chernarusplus
    world: str  # суффикс после последней точки
    path: str
    meta: dict = field(default_factory=dict)  # содержимое .krsm_mission.json, если есть

    @property
    def from_catalog(self) -> bool:
        return bool(self.meta.get("catalog_id"))


def load_catalog() -> list[CatalogEntry]:
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        return [
            CatalogEntry(
                **{k: m[k] for k in ("id", "title", "world", "repo", "branch", "path")},
                mods=m.get("mods", []),
                map_mod=m.get("map_mod", ""),
            )
            for m in data.get("missions", [])
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return []


def map_mod_installed(settings: Settings, workshop_id: str) -> bool:
    """Мод карты (map_mod) реально подписан — папка content/221100/<id>
    есть хотя бы в одной из настроенных папок Steam Workshop."""
    if not workshop_id:
        return True
    return any((Path(wdir) / workshop_id).is_dir() for wdir in settings.workshop_dirs)


def mpmissions_dir(settings: Settings, branch: str, mode: str) -> Path:
    """Папка миссий: DayZServer/mpmissions."""
    from .layout import debug_dir, MISSIONS_SUBDIR

    base = debug_dir(settings, branch, mode)
    return base / MISSIONS_SUBDIR if str(base) else Path("")


def resolve_mission(value: str, settings: Settings, branch: str, mode: str) -> str:
    """Значение миссии из пресета -> абсолютный путь (см. layout._resolve)."""
    from .layout import resolve_mission as _rm

    return _rm(value, settings, branch, mode)


def installed_missions(directory: Path) -> list[InstalledMission]:
    out: list[InstalledMission] = []
    if not directory or not directory.is_dir():
        return out
    for item in sorted(directory.iterdir()):
        if not item.is_dir() or "." not in item.name:
            continue
        meta = {}
        mf = item / META_NAME
        if mf.is_file():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        out.append(
            InstalledMission(
                name=item.name,
                world=item.name.rsplit(".", 1)[1],
                path=str(item),
                meta=meta,
            )
        )
    return out


def write_meta(mission_dir: Path, entry: CatalogEntry, sha: str | None, resolved_path: str) -> None:
    (mission_dir / META_NAME).write_text(
        json.dumps(
            {
                "catalog_id": entry.id,
                "repo": entry.repo,
                "branch": entry.branch,
                "path": resolved_path,
                "sha": sha or "",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ GitHub API


def _api_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve_entry_path(entry: CatalogEntry) -> str:
    """Подставляет {latestV} — старшую папку вида V5.9 в корне репозитория."""
    if "{latestV}" not in entry.path:
        return entry.path
    items = _api_json(f"https://api.github.com/repos/{entry.repo}/contents/?ref={entry.branch}")
    best: str | None = None
    best_key: tuple[int, ...] = ()
    for it in items:
        if it.get("type") != "dir":
            continue
        m = re.fullmatch(r"[Vv](\d+(?:\.\d+)*)", it.get("name", ""))
        if m:
            key = tuple(int(x) for x in m.group(1).split("."))
            if key > best_key:
                best, best_key = it["name"], key
    if not best:
        raise RuntimeError(f"В {entry.repo} не найдено папок версий V*")
    return entry.path.replace("{latestV}", best)


def latest_sha(entry: CatalogEntry, resolved_path: str) -> str | None:
    """SHA последнего коммита, затронувшего путь миссии (None при недоступности API)."""
    try:
        from urllib.parse import quote

        commits = _api_json(
            f"https://api.github.com/repos/{entry.repo}/commits"
            f"?sha={entry.branch}&path={quote(resolved_path)}&per_page=1"
        )
        return commits[0]["sha"] if commits else None
    except Exception:  # noqa: BLE001 — лимит API/сеть не должны ломать загрузку
        return None


def zip_url(entry: CatalogEntry) -> str:
    return f"https://codeload.github.com/{entry.repo}/zip/refs/heads/{entry.branch}"
