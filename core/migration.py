"""Однократный импорт конфигурации прежнего RaiZo Tools v2."""

from __future__ import annotations

import json
import shutil

from .presets import MODE_DEDICATED, MODE_DIAG, ModPreset, ServerPreset
from .settings import APP_DIR, CONFIG_DIR, SETTINGS_FILE, Settings


def _mod_name(value: object) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    name = text.rsplit("/", 1)[-1]
    return name if name.startswith("@") else ("@" + name if name else "")


def migrate_legacy_v2() -> bool:
    """Переносит старый config.json, не меняя и не удаляя оригинал."""
    source = APP_DIR / "config.json"
    marker = CONFIG_DIR / "migrated_from_raizo_v2"
    if SETTINGS_FILE.exists() or marker.exists() or not source.is_file():
        return False
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("schemaVersion") != 2:
        return False

    server_data = data.get("serverPresets") or {}
    first = next(iter(server_data.values()), {})
    active = data.get("active") or {}
    active_server = str(active.get("serverPreset") or "")
    active_mod = str(active.get("modPreset") or "")
    mod_data = data.get("modPresets") or {}
    active_mod_raw = mod_data.get(active_mod) or {}
    active_client_mods = [value for value in (_mod_name(v) for v in active_mod_raw.get("client", [])) if value]
    active_server_mods = [value for value in (_mod_name(v) for v in active_mod_raw.get("server", [])) if value]

    stable_client = stable_server = exp_client = exp_server = ""
    workshop_dirs: list[str] = []
    local_mods_dirs: list[str] = []
    for raw in server_data.values():
        experimental = bool(raw.get("isExperimental", False)) or (
            str(raw.get("distribution", "")).lower() == "experimental"
        )
        game_path = str(raw.get("gamePath", ""))
        server_path = str(raw.get("serverPath", ""))
        if experimental:
            exp_client = exp_client or game_path
            exp_server = exp_server or server_path
        else:
            stable_client = stable_client or game_path
            stable_server = stable_server or server_path
        workshop = raw.get("workshop") or {}
        if isinstance(workshop, dict):
            steam = workshop.get("steam")
            local = workshop.get("local")
            if steam and str(steam) not in workshop_dirs:
                workshop_dirs.append(str(steam))
            if local and str(local) not in local_mods_dirs:
                local_mods_dirs.append(str(local))

    settings = Settings(
        language=active.get("language") or active.get("lang") or "ru",
        first_run_done=bool(first),
        last_preset=active_server,
        last_mod_preset=active_mod,
        client_stable=stable_client or first.get("gamePath", ""),
        server_stable=stable_server or first.get("serverPath", ""),
        client_exp=exp_client,
        server_exp=exp_server,
        workshop_dirs=workshop_dirs,
        local_mods_dirs=local_mods_dirs,
        hide_server_window=not bool(first.get("showServerWindow", True)),
    )
    settings.save()

    for name, raw in server_data.items():
        file_patching = bool(raw.get("filePatching", False))
        mode = MODE_DIAG if raw.get("runtimeMode") == "diag" else MODE_DEDICATED
        experimental = bool(raw.get("isExperimental", False)) or (
            str(raw.get("distribution", "")).lower() == "experimental"
        )
        preset = ServerPreset(
            name=name,
            mode=mode,
            branch="experimental" if experimental else "stable",
            server_config=raw.get("serverConfig", "serverDZ.cfg"),
            mission=raw.get("missionName", "dayzOffline.chernarusplus"),
            profiles="profiles",
            server_ip=raw.get("serverIp", "127.0.0.1"),
            port=int(raw.get("serverPort", 2302)),
            clean_logs=raw.get("cleanLogs", False) not in (False, "none", None),
            params_server={"filePatching": True} if file_patching and mode == MODE_DIAG else {},
            params_client={"filePatching": True} if file_patching else {},
            mods=list(active_client_mods),
            server_mods=list(active_server_mods),
            launch_server=bool(raw.get("launchServer", True)),
            launch_client=bool(raw.get("launchClient", True)),
        )
        preset.save()

    for name, raw in mod_data.items():
        client = [_mod_name(v) for v in raw.get("client", [])]
        server = [_mod_name(v) for v in raw.get("server", [])]
        ModPreset(
            name=name,
            mods=[v for v in client if v],
            server_mods=[v for v in server if v],
        ).save()

    backup = APP_DIR / "config.v2.kr-base.backup.json"
    if not backup.exists():
        shutil.copy2(source, backup)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("3be692cb37b7e33686cd00e272280c87e075a086\n", encoding="ascii")
    return True
