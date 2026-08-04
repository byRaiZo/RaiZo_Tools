"""Предстартовая проверка конфигурации: критичные и некритичные проблемы."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import packer
from .i18n import tr
from .launcher import port_is_free
from .mods import ModRegistry
from .presets import ServerPreset, MODE_DIAG
from .servercfg import needs_reencode
from .settings import Settings

CRITICAL = "critical"
WARNING = "warning"


@dataclass
class Problem:
    check_id: str
    severity: str
    message: str


def run_checks(preset: ServerPreset, settings: Settings, branch: str, registry: ModRegistry) -> list[Problem]:
    """Возвращает список найденных проблем (пустой список — всё в порядке)."""
    problems: list[Problem] = []

    def crit(cid: str, msg: str) -> None:
        problems.append(Problem(cid, CRITICAL, msg))

    def warn(cid: str, msg: str) -> None:
        problems.append(Problem(cid, WARNING, msg))

    client_root = settings.client_root(branch)
    server_root = settings.server_root(branch)

    # Корни и экзешники
    if not client_root or not Path(client_root).is_dir():
        crit("client_root", tr("check.client_root", "Папка клиента не найдена: {p}", p=client_root or "—"))
        return problems  # без корня клиента дальше проверять нечего

    if preset.mode == MODE_DIAG:
        if not (Path(client_root) / "DayZDiag_x64.exe").is_file():
            crit("diag_exe", tr("check.diag_exe", "DayZDiag_x64.exe не найден в {p}", p=client_root))
    else:
        if not server_root or not Path(server_root).is_dir():
            crit("server_root", tr("check.server_root", "Папка сервера не найдена: {p}", p=server_root or "—"))
        elif not (Path(server_root) / "DayZServer_x64.exe").is_file():
            crit("server_exe", tr("check.server_exe", "DayZServer_x64.exe не найден в {p}", p=server_root))

    if preset.launch_client:
        exe = "DayZDiag_x64.exe" if (preset.mode == MODE_DIAG or preset.client_use_diag) else "DayZ_x64.exe"
        if not (Path(client_root) / exe).is_file():
            crit("client_exe", tr("check.client_exe", "{exe} не найден в {p}", exe=exe, p=client_root))

    # Пути пресета
    from .layout import resolve_config, resolve_profiles

    cfg = resolve_config(preset.server_config, settings, branch, preset.mode)
    if not cfg or not Path(cfg).is_file():
        crit("config", tr("check.config", "Серверный конфиг не найден: {p}", p=cfg or "—"))
    elif needs_reencode(Path(cfg)):
        warn(
            "config_enc", tr("check.config_enc", "Кодировка конфига не UTF-8 без BOM — будет исправлена автоматически.")
        )

    from .missions import resolve_mission

    mission = resolve_mission(preset.mission, settings, branch, preset.mode)
    if not mission or not Path(mission).is_dir():
        crit("mission", tr("check.mission", "Папка миссии не найдена: {p}", p=mission or "—"))

    # template внутри CFG является запасным значением. RaiZo Tools всегда
    # передаёт выбранную миссию через -mission=..., поэтому проверяем именно
    # поле пресета и не блокируем намеренное совместное использование CFG.

    profiles = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    if not profiles:
        warn(
            "profiles",
            tr("check.profiles_empty", "Папка профиля не указана — сервер будет писать логи в папку по умолчанию."),
        )
    elif not Path(profiles).is_dir():
        warn(
            "profiles_missing",
            tr("check.profiles_missing", "Папка профиля не существует и будет создана: {p}", p=profiles),
        )

    # Моды
    for name in preset.mods + preset.server_mods:
        mod = registry.get(name)
        if not mod:
            crit("mod_" + name, tr("check.mod_missing", "Мод не найден: {m}", m=name))
        elif not Path(mod.path).is_dir():
            crit("mod_" + name, tr("check.mod_gone", "Папка мода исчезла: {m} ({p})", m=name, p=mod.path))
    selected = [m for m in (registry.get(n) for n in preset.mods + preset.server_mods) if m]
    # Про устаревшие сорсы говорим, только когда перепаковка включена: при
    # выключенной они ни во что не выльются, а при работе через filepatching
    # это вообще штатное состояние — предупреждать не о чем.
    if settings.repack_before_launch:
        stale_names = [mod.name for mod, _ in packer.stale_mods(selected)]
        if stale_names:
            missing: list[str] = []
            tools_root = Path(settings.dayz_tools)
            if settings.pack_use_binarize and not (tools_root / "Bin" / "Binarize" / "binarize.exe").is_file():
                missing.append("Binarize.exe")
            if settings.pack_convert_config and not (tools_root / "Bin" / "CfgConvert" / "CfgConvert.exe").is_file():
                missing.append("CfgConvert.exe")
            if settings.pack_sign_pbos and not Path(settings.pack_private_key).is_file():
                missing.append(".biprivatekey")
            if missing:
                crit(
                    "packer",
                    tr(
                        "check.packer_missing",
                        "Моды {mods} требуют перепаковки, но {tool} не найден: {p}",
                        mods=", ".join(stale_names),
                        tool=", ".join(missing),
                        p=settings.dayz_tools or "—",
                    ),
                )
            else:
                warn(
                    "stale",
                    tr("check.stale", "Будут перепакованы устаревшие моды: {mods}", mods=", ".join(stale_names)),
                )

    # Порт
    if preset.launch_server and not port_is_free(preset.port):
        warn(
            "port",
            tr(
                "check.port",
                "UDP-порт {port} занят — возможно, сервер уже запущен (старые процессы будут завершены).",
                port=preset.port,
            ),
        )

    # Режим diag и BattlEye
    if preset.mode == MODE_DIAG and preset.params_server.get("battleye", None) is not False:
        warn(
            "battleye",
            tr(
                "check.battleye", "Diag-режим обычно требует battleye=0 — проверьте параметры, если сервер не стартует."
            ),
        )

    return problems


def has_critical(problems: list[Problem]) -> bool:
    return any(p.severity == CRITICAL for p in problems)
