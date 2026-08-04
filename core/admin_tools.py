"""Автовыдача админских прав модам-админкам в папке профиля сервера.

Каждая админка хранит список админов по-своему и создаёт свои файлы только
при первом запуске (с заглушкой внутри) — пользователю приходится вручную
править их после каждого пересоздания профиля. Здесь эти файлы готовятся
заранее, из settings.admin_steamids, по факту подключения самой админки
к пресету.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .mods import ModInfo
from .servercfg import ServerCfg

_STEAMID_RE = re.compile(r"^\d{17}$")


@dataclass(frozen=True)
class AdminTool:
    key: str
    title: str
    workshop_ids: tuple[str, ...]
    # подстроки имени @папки (в нижнем регистре) — для локальных копий
    # и переименованных сборок, у которых нет workshop_id
    folder_markers: tuple[str, ...]


COT = AdminTool(
    key="cot",
    title="Community Online Tools",
    workshop_ids=("1564026768",),
    folder_markers=("community-online-tools", "community_online_tools"),
)
VPP = AdminTool(
    key="vpp",
    title="VPPAdminTools",
    workshop_ids=("1828439124",),
    folder_markers=("vppadmintools", "vpp_admintools"),
)
# Один общий конфиг на все моды LBmaster (Groups, Banking, Leaderboard и т.д.),
# поэтому опознаём по имени папки: workshop_id у каждого мода свой.
LBMASTER = AdminTool(
    key="lbmaster",
    title="LBmaster",
    workshop_ids=(),
    folder_markers=("lbmaster", "lb_master"),
)
KNOWN_TOOLS = (COT, VPP, LBMASTER)

# шаблон Admins.json на случай, когда мод ещё не создал свой
_LB_TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "lbmaster_admins_template.json"


def detect_tools(mods: list[ModInfo]) -> list[AdminTool]:
    """Какие из известных админок есть среди подключённых модов."""
    found = []
    for tool in KNOWN_TOOLS:
        for mod in mods:
            folder = mod.folder_name.lstrip("@").lower()
            if mod.workshop_id in tool.workshop_ids or any(mark in folder for mark in tool.folder_markers):
                found.append(tool)
                break
    return found


def valid_steamids(ids: list[str]) -> list[str]:
    """Только корректные SteamID64 (17 цифр), без дублей, порядок сохраняется."""
    out: list[str] = []
    for raw in ids:
        sid = raw.strip()
        if _STEAMID_RE.match(sid) and sid not in out:
            out.append(sid)
    return out


VPP_DISABLE_PASSWORD = "vppDisablePassword"


def sync_vpp_password_flag(config_path: str | Path, password: str) -> str | None:
    """vppDisablePassword в serverDZ.cfg: 0 — пароль задан, 1 — входа без пароля.

    Возвращает новое значение, если оно поменялось; None — если менять нечего
    (нет файла/переменной или значение уже верное).
    """
    path = Path(config_path)
    if not str(config_path) or not path.is_file():
        return None
    want = "0" if password.strip() else "1"
    try:
        cfg = ServerCfg(path)
        current = next((v for v in cfg.variables() if v.name == VPP_DISABLE_PASSWORD), None)
        if current is None or current.value.strip() == want:
            return None
        cfg.set_values({VPP_DISABLE_PASSWORD: want})
        cfg.save()
    except OSError:
        return None
    return want


def _apply_cot(profile: Path, steamids: list[str]) -> list[str]:
    """PermissionsFramework/Players/<steamid>.json с ролью admin.

    Уже существующие файлы не трогаем — у пользователя там могли быть
    настроены свои роли, перезаписывать их нельзя.
    """
    players = profile / "PermissionsFramework" / "Players"
    players.mkdir(parents=True, exist_ok=True)
    created = []
    for sid in steamids:
        f = players / f"{sid}.json"
        if f.exists():
            continue
        f.write_text(json.dumps({"Roles": ["admin"]}, indent=4), encoding="utf-8")
        created.append(sid)
    return created


def _apply_vpp(profile: Path, steamids: list[str], password: str) -> list[str]:
    """VPPAdminTools: список суперадминов + пароль входа.

    Permissions/SuperAdmins/SuperAdmins.txt — по SteamID на строку; строка-заглушка
    мода («Remove this text and add your steam64 ID…») и прочий мусор отбрасываются,
    вписанные вручную ID сохраняются.
    Permissions/credentials.txt — пароль строго первой строкой.
    """
    base = profile / "VPPAdminTools" / "Permissions"
    admins = base / "SuperAdmins" / "SuperAdmins.txt"
    admins.parent.mkdir(parents=True, exist_ok=True)

    old_text = ""
    if admins.is_file():
        try:
            old_text = admins.read_text(encoding="utf-8", errors="replace")
        except OSError:
            old_text = ""

    existing = valid_steamids(old_text.splitlines())
    merged = existing + [sid for sid in steamids if sid not in existing]
    new_text = "\n".join(merged) + "\n"
    if new_text != old_text:  # переписываем, даже если ID те же — уберёт заглушку
        admins.write_text(new_text, encoding="utf-8")

    _write_vpp_password(base, password)
    return [sid for sid in steamids if sid not in existing]


def _write_vpp_password(permissions_dir: Path, password: str) -> bool:
    """Пароль первой строкой credentials.txt. True — файл изменён.

    Пустой пароль в настройках — файл не трогаем: вход и так без пароля
    (vppDisablePassword = 1), а в файле мог остаться пароль, выставленный вручную.
    """
    password = password.strip()
    if not password:
        return False
    f = permissions_dir / "credentials.txt"
    f.parent.mkdir(parents=True, exist_ok=True)

    rest: list[str] = []
    if f.is_file():
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        # первая строка — либо заглушка мода (начинается с //), либо старый
        # пароль; в обоих случаях её заменяем, остальное оставляем как есть
        rest = lines[1:] if lines else []
    new_text = "\n".join([password] + rest) + "\n"
    old_text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    if new_text == old_text:
        return False
    f.write_text(new_text, encoding="utf-8")
    return True


def _lb_template() -> dict:
    """Заготовка Admins.json с группой Owner. Файл данных мог не доехать в
    сборку — тогда обходимся минимумом: grantAllPermissions выдаёт всё и без
    группы."""
    try:
        return json.loads(_LB_TEMPLATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "admins": [], "groups": []}


def _apply_lb(profile: Path, steamids: list[str]) -> list[str]:
    """LBmaster: LBmaster/Config/Common/Admins.json — один файл на все моды LBmaster.

    Существующий файл дополняем, а не переписываем: дописываются только
    недостающие SteamID в admins, группы прав и уже заведённые записи
    остаются нетронутыми. Если файла ещё нет, берём заготовку с группой Owner.
    """
    f = profile / "LBmaster" / "Config" / "Common" / "Admins.json"

    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []  # чужой или битый файл не трогаем
        if not isinstance(data, dict):
            return []
    else:
        data = _lb_template()

    admins = data.get("admins")
    if not isinstance(admins, list):
        admins = []
        data["admins"] = admins

    existing = {str(a.get("steamid", "")).strip() for a in admins if isinstance(a, dict)}
    groups = [g.get("name") for g in data.get("groups", []) if isinstance(g, dict)]
    # на права это не влияет (grantAllPermissions выдаёт всё), но так запись
    # выглядит как сделанная самим модом
    group = ["Owner"] if "Owner" in groups else []

    added = []
    for sid in steamids:
        if sid in existing:
            continue
        admins.append(
            {
                "steamid": sid,
                "ingameNameForPermissions": "",
                "comment": "",
                "grantAllPermissions": 1,
                "permissionGroups": group,
            }
        )
        added.append(sid)

    if added or not f.is_file():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    return added


def _apply_tool(tool: AdminTool, profile: Path, steamids: list[str], password: str) -> list[str]:
    if tool.key == COT.key:
        return _apply_cot(profile, steamids)
    if tool.key == LBMASTER.key:
        return _apply_lb(profile, steamids)
    return _apply_vpp(profile, steamids, password)


def apply(
    profile_dir: str | Path, mods: list[ModInfo] | None, steamids: list[str], password: str = ""
) -> list[tuple[AdminTool, list[str]]]:
    """Готовит файлы прав админок в папке профиля.

    mods=None — готовим сразу для всех известных админок (создание профиля,
    кнопка «Актуализировать данные для Admin Tools»); иначе только для тех,
    что реально подключены к пресету.
    Возвращает [(админка, добавленные SteamID)] — для лога.
    """
    profile = Path(profile_dir)
    ids = valid_steamids(steamids)
    if not str(profile_dir) or (not ids and not password.strip()):
        return []
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except OSError:
        return []

    out = []
    for tool in KNOWN_TOOLS if mods is None else detect_tools(mods):
        try:
            added = _apply_tool(tool, profile, ids, password)
        except OSError:
            continue  # права/занятый файл не должны ломать запуск
        out.append((tool, added))
    return out
