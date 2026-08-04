"""Глобальные настройки приложения (config/settings.json)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _res_dir() -> Path:
    """Папка встроенных ресурсов: data, lang, иконка. Только чтение.

    В собранном виде PyInstaller распаковывает их к себе и кладёт путь в
    sys._MEIPASS; из исходников это просто корень проекта.
    """
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def _app_dir() -> Path:
    """Папка пользовательских данных: настройки, пресеты, загрузки.

    Из исходников — корень проекта, как было. В собранном виде она обязана
    лежать вне установки: папку программы обновление перезаписывает целиком, а
    в Program Files ещё и писать нельзя без прав администратора.

    Портативный режим: если рядом с exe есть папка config, работаем в ней —
    так приложение можно носить на флешке и держать несколько независимых
    копий. Иначе — %LOCALAPPDATA%\\RaiZo_Tools.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    near_exe = Path(sys.executable).resolve().parent
    if (near_exe / "config").is_dir():
        return near_exe
    appdata = os.environ.get("LOCALAPPDATA")
    return Path(appdata) / "RaiZo_Tools" if appdata else near_exe


RES_DIR = _res_dir()
APP_DIR = _app_dir()
CONFIG_DIR = APP_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PRESETS_DIR = CONFIG_DIR / "presets"
MOD_PRESETS_DIR = CONFIG_DIR / "mod_presets"
MOD_SOURCES_FILE = CONFIG_DIR / "mod_sources.json"
MOD_DEPENDENCIES_FILE = CONFIG_DIR / "mod_dependencies.json"
# ключ мода -> id воркшопа: помним по всем стим-модам, которые видели. Нужен,
# когда мод отписали: зависимость по ключу остаётся, а id взять уже неоткуда
MOD_WORKSHOP_IDS_FILE = CONFIG_DIR / "mod_workshop_ids.json"
MOD_FLAGS_FILE = CONFIG_DIR / "mod_flags.json"
MOD_FLAG_DEFS_FILE = CONFIG_DIR / "mod_flag_defs.json"

STABLE = "stable"
EXPERIMENTAL = "experimental"


CLIENT_EXE = "DayZ_x64.exe"
SERVER_EXE = "DayZServer_x64.exe"

# поле настроек -> исполняемый файл, по которому опознаётся установка
ROOT_EXES: dict[str, str] = {
    "client_stable": CLIENT_EXE,
    "client_exp": CLIENT_EXE,
    "server_stable": SERVER_EXE,
    "server_exp": SERVER_EXE,
}

# результаты check_path
PATH_OK = ""
PATH_MISSING = "missing"  # папки по пути нет
PATH_NOT_INSTALLED = "not_installed"  # папка есть, но программы в ней нет


def atomic_write_json(path: Path, data: object) -> None:
    """Записывает JSON через временный файл и атомарную замену."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def is_install(path: str, exe: str) -> bool:
    """Является ли папка установкой игры/сервера.

    Проверяется исполняемый файл, а не просто существование папки: после
    удаления игры из Steam каталог часто остаётся — Steam не удаляет его, если
    внутри есть чужое содержимое (наши симлинки filepatching, serverDZ.cfg,
    ban.txt, mpmissions). Такой остаток установкой не является.
    """
    return bool(path) and (Path(path) / exe).is_file()


def check_path(key: str, value: str) -> str:
    """Проверка пути из настроек: PATH_OK / PATH_MISSING / PATH_NOT_INSTALLED.

    Пустое поле ошибкой не считается — компонент просто не установлен, это
    нормальное состояние. Путь автоматически не стирается: папка может быть
    временно недоступна (внешний диск, сеть), и терять из-за этого настройку
    нельзя — пользователю показывается предупреждение.
    """
    if not value:
        return PATH_OK
    p = Path(value)
    if not p.is_dir():
        return PATH_MISSING
    exe = ROOT_EXES.get(key)
    if exe and not (p / exe).is_file():
        return PATH_NOT_INSTALLED
    return PATH_OK


@dataclass
class Settings:
    language: str = "ru"
    first_run_done: bool = False
    project_prefix: str = ""  # префикс мододела/проекта — подставляется в hostname создаваемых серверов
    theme: str = "auto"  # "light" | "dark" | "auto" (следовать теме Windows)
    last_preset: str = ""
    last_mod_preset: str = ""

    # Корневые папки установок
    client_stable: str = ""
    client_exp: str = ""
    server_stable: str = ""
    server_exp: str = ""

    # Инструменты
    dayz_tools: str = ""  # папка DayZ Tools
    dayz_tools_exp: str = ""  # папка DayZ Experimental Tools

    # Steam Workshop: папки content/221100 (может быть несколько библиотек)
    workshop_dirs: list[str] = field(default_factory=list)

    # Админские настройки (для модов-админок; интеграция — в будущих версиях)
    admin_steamids: list[str] = field(default_factory=list)
    admin_password: str = ""

    # Запаковка
    # Устаревшая строка сохраняется только для бесшовного чтения старых
    # конфигураций KR_QTS; встроенный backend её не использует.
    #
    # Чего здесь намеренно нет:
    #   -$ — управляет разрешением собирать pbo без префикса; при нём терялся
    #        $PBOPREFIX$ и мод паковался без префикса вообще;
    #   -W — в разных версиях это либо «warnings are errors», либо рабочий диск;
    #   +N — подробный лог, объём вывода огромен и заметно замедляет сборку;
    #   +R — не настройка пользователя, а обязательное условие, ставится в
    #        core/packer.py вместе с -E/-M.
    # -X — маски файлов, которые в pbo не попадают. «source» в списке не нужен:
    # папка ~source\ не инспектируется никогда.
    pack_flags: str = (
        "-P -N +B -C -D -H -T +G -Q +Z -O -K "
        "-X=*.h,*.hpp,*.png,*.cpp,thumbs.db,*.dep,*.bak,*.log,*.pew,"
        "*.tga,*.bat,*.psd,*.cmd,*.mcr,*.fbx,*.max,*.blend,*.blend1,*.blend2,"
        "*.blend3,*.blend4,*.blend5,*.txa,.claude"
    )
    clean_meta: bool = True  # удалять *.meta в сорсах перед сборкой
    # "" — не перепаковывать, "normal" — cache, "full" — полная сборка
    pack_engine: str = "normal"
    repack_before_launch: bool = False  # перепаковывать изменённые локальные моды перед запуском
    pack_use_binarize: bool = True
    pack_protect_p3d: bool = False
    pack_convert_config: bool = True
    pack_sign_pbos: bool = False
    pack_private_key: str = ""
    pack_preflight: bool = True
    pack_max_processes: int = 0
    pack_binarize_exe: str = ""
    pack_cfgconvert_exe: str = ""
    pack_p3d_obfuscator_exe: str = ""
    pack_dssignfile_exe: str = ""
    pack_temp_dir: str = ""
    pack_preflight_checks: dict[str, bool] = field(default_factory=dict)
    pack_exclude_patterns: str = (
        "*.h,*.hpp,*.png,*.cpp,*.txt,thumbs.db,*.dep,*.bak,*.log,*.pew,source,*.tga,*.bat,*.psd,*.cmd,*.mcr,*.fbx,*.max"
    )
    # Последние пути вкладки PBO Builder. Они не привязаны к реестру модов
    # и потому подходят для сборки любого локального addon.
    pbo_last_source_root: str = ""
    pbo_last_output_root: str = ""
    pbo_last_output_server_root: str = ""
    pbo_last_project_root: str = ""
    pbo_last_name: str = ""
    pbo_source_roots: list[str] = field(default_factory=list)
    pbo_output_roots: list[str] = field(default_factory=list)
    pbo_output_server_roots: list[str] = field(default_factory=list)

    # Общая папка загрузок (моды карт с GitHub); пусто — <папка программы>/downloads
    downloads_dir: str = ""

    # Папки с локальными модами (@папки собственных сборок)
    local_mods_dirs: list[str] = field(default_factory=list)

    # Положение мини-окна на экране — чтобы оно не прыгало в центр при каждом
    # сворачивании в трей; пусто — открыть там, где решит система
    mini_pos: list[int] = field(default_factory=list)

    # Папки скриптов на диске P:, подключённые ссылками для filepatching
    # (см. core/filepatch.py). Хранится исходный P:-путь, а не разрешённый:
    # цель вычисляется заново при каждой синхронизации.
    filepatch_links: list[str] = field(default_factory=list)

    # Моды, скрытые из списка вручную (ключ — folder_name.lower()); сама папка
    # мода/подписка на Steam остаётся нетронутой, мод просто не показывается
    excluded_mods: list[str] = field(default_factory=list)

    # Недавно выбранные папки сорсов — для боковой панели диалога выбора
    # (недативный Qt-диалог с мультивыбором своих «последних папок» не знает)
    recent_source_dirs: list[str] = field(default_factory=list)

    # Окна логов поверх остальных окон — раздельно для сервера и клиента:
    # поверх всего обычно держат одно из двух, второе в это время мешает
    # Окно сервера DayZ несёт ровно то же, что server_console.log, который мы
    # и так читаем. Прятать его можно без потери сведений, см. core/winhide.
    hide_server_window: bool = False
    # Как останавливать сервер и клиент: «soft» — попросить окна закрыться,
    # программа завершится своим порядком; «hard» — убить процесс сразу.
    # По умолчанию мягко: убийство обрывает сохранение на полуслове.
    stop_method: str = "soft"
    log_on_top_server: bool = False
    log_on_top_client: bool = False

    # Проверять новую версию на GitHub при запуске. Сетевой запрос на старте
    # без возможности отключить — то, за что справедливо ругают, поэтому галка.
    check_updates: bool = True
    # Версия, чейнджлог которой пользователь уже открывал: пункт в навигации
    # останется, но окно само не откроется второй раз
    update_seen: str = ""

    # Steam Web API ключ (steamcommunity.com/dev/apikey) — для зависимостей модов;
    # пусто — зависимости читаются со страницы воркшопа
    steam_api_key: str = ""

    def client_root(self, branch: str) -> str:
        return self.client_exp if branch == EXPERIMENTAL else self.client_stable

    def server_root(self, branch: str) -> str:
        return self.server_exp if branch == EXPERIMENTAL else self.server_stable

    def save(self) -> None:
        atomic_write_json(SETTINGS_FILE, asdict(self))

    @classmethod
    def load(cls) -> Settings:
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
                return cls(**{k: v for k, v in data.items() if k in known})
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        return cls()
