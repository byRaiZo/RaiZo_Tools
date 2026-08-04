import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path
from typing import cast


def get_available_logical_threads():
    # Prefer the amount of logical CPUs actually available to this process.
    # This can differ from total CPU threads when CPU affinity, VM/container limits,
    # or OS-level restrictions are active.
    process_cpu_count = cast(Callable[[], int | None] | None, getattr(os, "process_cpu_count", None))

    if callable(process_cpu_count):
        try:
            count = process_cpu_count()
            if count and count > 0:
                return count
        except Exception:
            pass

    sched_getaffinity = cast(
        Callable[[int], Collection[int]] | None,
        getattr(os, "sched_getaffinity", None),
    )

    if callable(sched_getaffinity):
        try:
            return max(1, len(sched_getaffinity(0)))
        except Exception:
            pass

    return os.cpu_count() or 8


def get_default_max_processes():
    # Default to all logical threads available to this process.
    # Clamp to the UI spinbox range.
    available_threads = get_available_logical_threads()
    return max(1, min(available_threads, 64))


def get_initial_dir_from_value(value, fallback=""):
    value = value.strip() if value else ""
    fallback = fallback.strip() if fallback else ""
    if value:
        if os.path.isdir(value):
            return value
        parent = os.path.dirname(value)
        if parent and os.path.isdir(parent):
            return parent
    if fallback:
        if os.path.isdir(fallback):
            return fallback
        parent = os.path.dirname(fallback)
        if parent and os.path.isdir(parent):
            return parent
    return str(Path.home())


def is_safe_window_geometry(value):
    if not value or not isinstance(value, str):
        return False

    # Accept normal Tk geometry strings like 1080x900 or 1080x900+120+80.
    match = re.match(r"^(\d+)x(\d+)([+-]\d+[+-]\d+)?$", value.strip())

    if not match:
        return False

    width = int(match.group(1))
    height = int(match.group(2))

    return width >= 800 and height >= 600


def resource_path(relative_path):
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        return os.path.join(bundle_root, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def get_app_data_dir():
    local_appdata = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_appdata) if local_appdata else Path.home()
    app_dir = base_dir / "RaiZo_Tools" / "pbo"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_settings_file_path():
    return get_app_data_dir() / "settings.json"


def get_cache_file_path():
    return get_app_data_dir() / "cache.json"


def get_logs_dir():
    logs_dir = get_app_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def create_build_log_path():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return get_logs_dir() / f"build_{stamp}.log"


def load_json_file(path):
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def load_saved_settings():
    return load_json_file(get_settings_file_path())


def save_saved_settings(data):
    save_json_file(get_settings_file_path(), data)


def load_build_cache():
    return load_json_file(get_cache_file_path())


def save_build_cache(data):
    save_json_file(get_cache_file_path(), data)


def get_subprocess_creationflags():
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def get_hidden_startupinfo():
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo
