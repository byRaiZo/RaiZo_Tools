"""Сборка командных строк и запуск сервера/клиента с умным ожиданием готовности."""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QThread, Signal

from . import packer, packlog, winhide
from .command_lock import ProcessCommandLock, process_command_lock
from .i18n import tr
from .mods import ModInfo, ModRegistry
from .params import default_params, specs_for, SERVER, CLIENT
from .presets import ServerPreset, MODE_DIAG
from .settings import Settings

PROC_NAMES = {"dayz_x64.exe", "dayzdiag_x64.exe", "dayzserver_x64.exe", "dayz_be.exe"}

READY_TIMEOUT = 180  # секунд ждём, пока сервер займёт UDP-порт
CLIENT_SPAWN_TIMEOUT = 30  # секунд ждём DayZ_x64 после запуска BattlEye


def dayz_running() -> bool:
    """Запущен ли хоть один процесс DayZ (сервер/клиент/диаг).

    Правки cfg и чистка профиля во время работы сервера либо не подхватятся
    (файлы прочитаны при старте), либо потеряются — он перезапишет их своими.
    """
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() in PROC_NAMES:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


SERVER_EXE_NAME = "dayzserver_x64.exe"
CLIENT_EXE_NAME = "dayz_x64.exe"
DIAG_EXE_NAME = "dayzdiag_x64.exe"
BATTLEYE_EXE_NAME = "dayz_be.exe"


def parse_extra_args(command_line: str) -> list[str]:
    """Разбирает сохранённую строку аргументов по правилам Windows.

    На Windows используется системный ``CommandLineToArgvW``. Fallback нужен
    для тестов и запуска инструментов разработки на других ОС.
    """
    if not command_line:
        return []
    if os.name != "nt":
        return shlex.split(command_line, posix=False)

    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    parse = shell32.CommandLineToArgvW
    parse.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL

    argc = ctypes.c_int()
    argv = parse(f"RaiZoTools.exe {command_line}", ctypes.byref(argc))
    if not argv:
        raise OSError(ctypes.get_last_error(), "CommandLineToArgvW failed")
    try:
        return [argv[index] for index in range(1, argc.value)]
    finally:
        kernel32.LocalFree(argv)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Неизменяемая идентичность процесса для защиты от повторного PID.

    Поля команды могут быть пустыми: BattlEye разрешает увидеть имя, путь и
    время создания DayZ_x64, но блокирует чтение ``cmdline`` и ``cwd``.
    """

    pid: int
    create_time: float
    exe: str
    kind: str | None
    config: str
    port: str
    connect: str


def _process_identity(proc: psutil.Process) -> ProcessIdentity | None:
    try:
        pid = proc.pid
        create_time = proc.create_time()
        kind = _proc_kind(proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
        return None
    try:
        exe = _path_key(proc.exe())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
        exe = ""
    try:
        args = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
        args = []
    try:
        cwd = proc.cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
        cwd = ""
    return ProcessIdentity(
        pid=pid,
        create_time=create_time,
        exe=exe,
        kind=kind,
        config=_arg_path(args, "-config=", cwd) if cwd else "",
        port=_arg_value(args, "-port="),
        connect=_arg_value(args, "-connect=").casefold(),
    )


def _identity_matches(expected: ProcessIdentity, current: ProcessIdentity | None) -> bool:
    """Тот же процесс, даже если BattlEye скрыл часть данных после запуска."""
    if current is None:
        return False
    if expected.pid != current.pid or expected.create_time != current.create_time or expected.kind != current.kind:
        return False
    if expected.exe and current.exe and expected.exe != current.exe:
        return False
    for field in ("config", "port", "connect"):
        before = getattr(expected, field)
        now = getattr(current, field)
        if before and now and before != now:
            return False
    return True


def capture_process_identity(pid: int | None) -> ProcessIdentity | None:
    if not pid:
        return None
    try:
        return _process_identity(psutil.Process(pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None


def identity_is_current(identity: ProcessIdentity | None) -> bool:
    """PID всё ещё принадлежит тому же процессу DayZ."""
    if identity is None:
        return False
    current = capture_process_identity(identity.pid)
    return _identity_matches(identity, current)


def _proc_kind(proc: psutil.Process) -> str | None:
    """server | client | None (не наш процесс).

    В diag-режиме сервер и клиент — один и тот же DayZDiag_x64.exe, отличается
    только аргумент -server, поэтому по имени их не разделить. Если командную
    строку прочитать не удалось, возвращаем None: лучше не тронуть чужой
    процесс, чем случайно убить работающий сервер.
    """
    try:
        name = (proc.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    if name == SERVER_EXE_NAME:
        return "server"
    if name == CLIENT_EXE_NAME:
        return "client"
    if name != DIAG_EXE_NAME:
        return None
    try:
        return "server" if any(a.lower() == "-server" for a in proc.cmdline()) else "client"
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def kill_pid(process: int | ProcessIdentity | None) -> bool:
    """Гасит один процесс по pid — чтобы остановить только сервер или только
    клиент, не трогая второй. True, если процесс был жив и убит."""
    if process is None:
        return False
    if isinstance(process, ProcessIdentity):
        identity: ProcessIdentity | None = process
        pid = process.pid
    else:
        identity = None
        pid = process
    try:
        proc = psutil.Process(pid)
        if identity is not None and not _identity_matches(identity, _process_identity(proc)):
            return False
        proc.kill()
        proc.wait(timeout=5)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return False


def resolve_path(value: str, client_root: str) -> str:
    """Пути пресета хранятся относительно корня клиента; в командную строку — абсолютные."""
    if not value:
        return ""
    p = Path(value)
    return str(p) if p.is_absolute() else str(Path(client_root) / p)


def rel_to(path: str, root: str) -> str:
    """Путь относительно корня игры/сервера.

    Миссия, моды, профиль и серверный конфиг передаются в DayZ именно
    относительными: рабочей папкой процесса мы и так задаём корень, а
    абсолютные пути раздували командную строку вдвое — в каждый мод повторно
    вписывался весь путь до корня.

    Относительный путь невозможен только между разными дисками — там
    ничего не поделать, оставляем как есть.
    """
    if not path:
        return path
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _params_args(preset: ServerPreset, target: str) -> list[str]:
    stored = preset.params_server if target == SERVER else preset.params_client
    values = default_params(target, diag=True) if preset.mode == MODE_DIAG else {}
    values.update(stored)
    args = []
    for spec in specs_for(target, preset.mode == MODE_DIAG):
        # В Dedicated filePatching не должен уходить ни DayZServer_x64, ни
        # обычному клиенту. Этот параметр относится только к режиму Diag.
        if preset.mode != MODE_DIAG and spec.name == "filePatching":
            continue
        if spec.name in values:
            a = spec.to_arg(values[spec.name])
            if a:
                args.append(a)
    return args


def _mods_arg(names: list[str], registry: ModRegistry, cwd: str, mods_root: str, *, absolute: bool = False) -> str:
    r"""Пути junction из DayZServer/MODS.

    DayZ не открывает PBO по пути с ``..``. Поэтому клиент и Diag, чей рабочий
    каталог находится вне DayZServer, получают абсолютные пути. Dedicated
    сохраняет короткие пути ``MODS\@Mod`` относительно своего cwd.
    """
    from .layout import mods_link_dir

    base = mods_link_dir(mods_root)
    folders = []
    for n in names:
        mod = registry.get(n)
        folder = mod.folder_name if mod else (n if n.startswith("@") else "@" + n)
        path = str(base / folder)
        folders.append(path if absolute else rel_to(path, cwd))
    return ";".join(folders)


def build_server_command(
    preset: ServerPreset, settings: Settings, branch: str, registry: ModRegistry
) -> tuple[str, list[str], str]:
    """Возвращает (exe, args, cwd) для сервера."""
    client_root = settings.client_root(branch)
    if preset.mode == MODE_DIAG:
        exe = str(Path(client_root) / "DayZDiag_x64.exe")
        cwd = client_root
        args = ["-server"]
    else:
        cwd = settings.server_root(branch)
        exe = str(Path(cwd) / "DayZServer_x64.exe")
        args = []

    from .layout import resolve_config, resolve_profiles, resolve_mission

    config = resolve_config(preset.server_config, settings, branch, preset.mode)
    mission = resolve_mission(preset.mission, settings, branch, preset.mode)
    profiles = resolve_profiles(preset.profiles, settings, branch, preset.mode)
    external_data = preset.mode == MODE_DIAG
    args += [
        f"-config={config if external_data else rel_to(config, cwd)}",
        f"-mission={mission if external_data else rel_to(mission, cwd)}",
        f"-profiles={profiles if external_data else rel_to(profiles, cwd)}",
        f"-port={preset.port}",
    ]
    if preset.mods:
        args.append(
            f"-mod={_mods_arg(preset.mods, registry, cwd, settings.server_root(branch), absolute=external_data)}"
        )
    if preset.server_mods:
        server_mods = _mods_arg(
            preset.server_mods,
            registry,
            cwd,
            settings.server_root(branch),
            absolute=external_data,
        )
        args.append(f"-serverMod={server_mods}")
    args += _params_args(preset, SERVER)
    args += parse_extra_args(preset.extra_server)
    if preset.mode != MODE_DIAG:
        args = [arg for arg in args if arg.partition("=")[0].casefold() != "-filepatching"]
    return exe, args, cwd


def build_client_command(
    preset: ServerPreset, settings: Settings, branch: str, registry: ModRegistry
) -> tuple[str, list[str], str]:
    """Возвращает (exe, args, cwd) для клиента."""
    client_root = settings.client_root(branch)
    use_diag = preset.mode == MODE_DIAG or preset.client_use_diag
    exe = str(Path(client_root) / ("DayZDiag_x64.exe" if use_diag else "DayZ_x64.exe"))
    args = [f"-connect={preset.server_ip or '127.0.0.1'}:{preset.port}"]
    if preset.mods:
        args.append(
            f"-mod={_mods_arg(preset.mods, registry, client_root, settings.server_root(branch), absolute=True)}"
        )
    args += _params_args(preset, CLIENT)
    args += parse_extra_args(preset.extra_client)
    if preset.mode != MODE_DIAG:
        args = [arg for arg in args if arg.partition("=")[0].casefold() != "-filepatching"]
    return exe, args, client_root


def build_client_launch_command(
    preset: ServerPreset, settings: Settings, branch: str, registry: ModRegistry
) -> tuple[str, list[str], str]:
    """Команда, которую нужно запустить для создания клиента DayZ.

    Обычный клиент Dedicated-сервера обязан стартовать через ``DayZ_BE.exe``:
    он поднимает BattlEye и затем создаёт настоящий ``DayZ_x64.exe``. Для
    сопоставления, остановки и подхвата процесса по-прежнему используется
    :func:`build_client_command`, описывающая именно конечный процесс игры.
    Diag-клиент запускается напрямую и BattlEye не использует.
    """
    runtime_exe, args, cwd = build_client_command(preset, settings, branch, registry)
    if Path(runtime_exe).name.casefold() == CLIENT_EXE_NAME:
        return str(Path(cwd) / "DayZ_BE.exe"), args, cwd
    return runtime_exe, args, cwd


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _arg_value(args: list[str], prefix: str) -> str:
    low = prefix.lower()
    for arg in args:
        if arg.lower().startswith(low):
            return arg[len(prefix) :].strip('"')
    return ""


def _arg_path(args: list[str], prefix: str, cwd: str) -> str:
    raw = _arg_value(args, prefix)
    if not raw:
        return ""
    return _path_key(raw if Path(raw).is_absolute() else str(Path(cwd) / raw))


def _matches_command(proc: psutil.Process, kind: str, command: tuple[str, list[str], str]) -> bool:
    """Совпадает ли процесс с конкретной командой RaiZo Tools."""
    exe, expected_args, expected_cwd = command
    try:
        if _path_key(proc.exe()) != _path_key(exe) or _proc_kind(proc) != kind:
            return False
        args = proc.cmdline()
        cwd = proc.cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False

    if kind == "server":
        if _arg_value(args, "-port=") != _arg_value(expected_args, "-port="):
            return False
        return _arg_path(args, "-config=", cwd) == _arg_path(expected_args, "-config=", expected_cwd)
    return _arg_value(args, "-connect=").lower() == _arg_value(expected_args, "-connect=").lower()


def _wait_for_matching_process(
    kind: str,
    command: tuple[str, list[str], str],
    excluded_pids: set[int] | None = None,
    *,
    timeout: float = CLIENT_SPAWN_TIMEOUT,
) -> psutil.Process | None:
    """Ждёт конечный процесс, созданный промежуточным лаунчером.

    ``DayZ_BE.exe`` не является самим клиентом и может завершиться сразу после
    передачи управления. Обычно проверяем аргументы выбранного пресета. Если
    BattlEye запрещает их читать, принимаем только новый ожидаемый EXE, которого
    не было до запуска.
    """
    excluded = excluded_pids or set()
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.pid in excluded or (proc.info["name"] or "").lower() not in PROC_NAMES:
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if _matches_command(proc, kind, command) or (
                kind == "client" and _matches_runtime_executable(proc, kind, command)
            ):
                return proc
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)


def _matches_runtime_executable(
    proc: psutil.Process,
    kind: str,
    command: tuple[str, list[str], str],
) -> bool:
    """Совпадает конечный EXE, даже если BattlEye закрыл командную строку."""
    expected_exe = command[0]
    if _proc_kind(proc) != kind:
        return False
    try:
        return _path_key(proc.exe()) == _path_key(expected_exe)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
        try:
            return (proc.name() or "").casefold() == Path(expected_exe).name.casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
            return False


def _runtime_process_pids(kind: str, command: tuple[str, list[str], str]) -> set[int]:
    """Снимок всех конечных процессов до запуска промежуточного лаунчера."""
    result: set[int] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if _matches_runtime_executable(proc, kind, command):
                result.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, AttributeError):
            continue
    return result


def matching_processes(
    preset: ServerPreset, settings: Settings, branch: str, registry: ModRegistry, kinds: Iterable[str]
) -> list[psutil.Process]:
    """Только процессы, точно соответствующие выбранному пресету и роли."""
    wanted = set(kinds)
    commands: list[tuple[str, tuple[str, list[str], str]]] = []
    if "server" in wanted:
        commands.append(("server", build_server_command(preset, settings, branch, registry)))
    if "client" in wanted:
        commands.append(("client", build_client_command(preset, settings, branch, registry)))

    matches: list[psutil.Process] = []
    seen: set[int] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() not in PROC_NAMES:
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if proc.pid in seen:
            continue
        if any(_matches_command(proc, kind, command) for kind, command in commands):
            matches.append(proc)
            seen.add(proc.pid)
    return matches


def stop_processes(
    processes: Iterable[psutil.Process],
    timeout: float = 15.0,
    *,
    force: bool = False,
) -> int:
    """Останавливает процессы мягко либо немедленно для restart-ярлыка."""
    victims = list({proc.pid: proc for proc in processes}.values())
    identities = {proc.pid: _process_identity(proc) for proc in victims}
    for proc in victims:
        try:
            identity = identities.get(proc.pid)
            if identity is not None and not identity_is_current(identity):
                continue
            if force:
                proc.kill()
                continue
            if not winhide.ask_close(proc.pid):
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    if not victims:
        return 0
    _gone, alive = psutil.wait_procs(victims, timeout=min(timeout, 5.0) if force else timeout)
    for proc in alive:
        try:
            identity = identities.get(proc.pid)
            if identity is not None and not identity_is_current(identity):
                continue
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=5)
    return len(victims)


def clear_launch_logs(preset: ServerPreset, settings: Settings, branch: str, kinds: Iterable[str]) -> int:
    """Очищает логи выбранных сторон, не заходя в моды и миссии."""
    from . import logsource

    wanted = set(kinds)
    removed = 0
    if "server" in wanted:
        root = Path(settings.server_root(branch))
        removed += logsource.delete_logs(
            root,
            recursive=True,
            excluded=(root / "MODS", root / "mpmissions", root / "keys"),
        )
    if "client" in wanted:
        directory = logsource.client_log_dir(branch)
        if directory:
            removed += logsource.delete_logs(directory, recursive=True)
    return removed


def port_is_free(port: int) -> bool:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _script_logs(profiles: str) -> set[str]:
    """Снимок script-логов в папке профиля — что было до запуска."""
    if not profiles or not Path(profiles).is_dir():
        return set()
    return {str(f) for f in Path(profiles).glob("script_*.log")}


def scripts_ready(known: set[str], profiles: str = "") -> bool:
    """Собрал ли сервер скрипты миссии.

    Признак — строка про расход памяти слоя 5_Mission в script-логе этой
    сессии. Слой компилируется последним, так что до него дело доходит, только
    когда всё остальное уже поднялось. Файлы из known — прошлые сессии, их не
    смотрим: там 5_Mission есть всегда, и ожидание завершилось бы мгновенно.
    """
    from . import scriptmem

    for path in _script_logs(profiles) - known if profiles else set():
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            u = scriptmem.parse(line)
            if u and u.layer == scriptmem.READY_LAYER:
                return True
    return False


def _server_ready(proc: psutil.Process, port: int) -> bool:
    """Сервер готов, когда занял свой UDP-порт."""
    try:
        conns = proc.net_connections(kind="inet")
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except AttributeError:  # psutil < 6
        conns = proc.connections(kind="inet")
    return any(c.laddr and c.laddr.port == port for c in conns)


class LaunchWorker(QThread):
    """Последовательность запуска в отдельном потоке.

    Шаги: перепаковка устаревших модов -> kill -> junction -> ключи ->
    сервер -> ожидание готовности -> клиент.
    """

    log = Signal(str, str)  # message, level: info|warning|error
    pack_plan = Signal(list)  # имена pbo, которые предстоит собрать
    pack_status = Signal(str, str, int, int, int)  # pbo, состояние, мс, warnings, errors
    server_started = Signal(int)  # pid
    server_ready = Signal()  # порт занят — сервер принимает клиент
    client_started = Signal(int)  # pid
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        preset: ServerPreset,
        settings: Settings,
        branch: str,
        registry: ModRegistry,
        parent: QObject | None = None,
        *,
        force_restart: bool = False,
    ) -> None:
        super().__init__(parent)
        self.preset = preset
        self.settings = settings
        self.branch = branch
        self.registry = registry
        self.force_restart = force_restart

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — любая ошибка должна дойти до UI
            self.failed.emit(str(e))

    def run_blocking(self) -> str:
        """Выполняет тот же запуск без GUI-потока; используется CLI-ярлыками."""
        errors: list[str] = []
        on_error = errors.append
        self.failed.connect(on_error)
        try:
            self._run()
        except Exception as error:  # noqa: BLE001 — CLI обязан вернуть понятную ошибку
            return str(error)
        finally:
            self.failed.disconnect(on_error)
        return errors[-1] if errors else ""

    def _run(self) -> None:
        # Общая блокировка для GUI и CLI-ярлыков. Если Start нажали повторно,
        # второй запуск ждёт завершения первого, после чего штатный код ниже
        # точно сопоставляет старый процесс, останавливает и запускает заново.
        with process_command_lock() as command_lock:
            self._run_locked(command_lock)

    def _run_locked(self, command_lock: ProcessCommandLock) -> None:
        p, s, reg = self.preset, self.settings, self.registry
        # get() возвращает None для мода, которого нет в реестре, — такие
        # отсеиваем сразу, дальше по коду список считается полным
        selected: list[ModInfo] = [m for m in (reg.get(n) for n in (p.mods + p.server_mods)) if m]

        # 1. Перепаковка устаревших локальных модов (только если включено в настройках)
        if s.repack_before_launch:
            plan = packer.stale_mods(selected)
            # весь список объявляем заранее — сколько PBO предстоит собрать
            # должно быть видно сразу, а не по мере готовности
            self.pack_plan.emit([packer.pbo_for_source(m, src).name for m, stale in plan for src in stale])
            for mod, stale in plan:
                mod_failed = False
                for src in stale:
                    name = packer.pbo_for_source(mod, src).name
                    self.pack_status.emit(name, "packing", -1, 0, 0)
                    t0 = time.monotonic()
                    ok, output = packer.pack_source_auto(s, mod, src)
                    w, e = packlog.counts(Path(src).name)
                    self.pack_status.emit(name, "ok" if ok else "fail", int((time.monotonic() - t0) * 1000), w, e)
                    if not ok:
                        if output:
                            self.log.emit(output[-4000:], "error")
                        mod_failed = True
                        break
                if mod_failed:
                    self.failed.emit(tr("launch.pack_failed", "Ошибка запаковки {mod}. Запуск отменён.", mod=mod.name))
                    return

        # 2. Перезапускаем только точное совпадение: полный EXE, роль и
        #    идентифицирующие аргументы выбранного пресета.
        kinds = {kind for kind, enabled in (("server", p.launch_server), ("client", p.launch_client)) if enabled}
        victims = matching_processes(p, s, self.branch, reg, kinds)
        stopped = stop_processes(victims, force=self.force_restart)
        if stopped:
            self.log.emit(
                tr("launch.killed", "Завершено старых процессов: {n}", n=stopped),
                "info",
            )

        if p.clean_logs:
            removed = clear_launch_logs(p, s, self.branch, kinds)
            self.log.emit(
                tr("launch.logs_cleared", "Удалено файлов логов: {n}", n=removed),
                "info",
            )

        # 3. Junction для модов
        roots = [s.server_root(self.branch)]
        for mod in selected:
            for root in roots:
                # серверные моды в корень клиента не обязательны, но не мешают
                ok, err = reg.ensure_available(mod, root)
                if not ok:
                    self.failed.emit(
                        tr("launch.junction_failed", "Не удалось подключить мод {mod}: {err}", mod=mod.name, err=err)
                    )
                    return

        # 4. Ключи для dedicated
        if p.mode != MODE_DIAG:
            for mod in selected:
                reg.copy_keys(mod, s.server_root(self.branch))

        # 4.5. TimeLogin/TimeLogout в db/globals.xml миссии — общее значение
        #      (применяется перед запуском, переживает пересоздание миссии)
        if p.time_login >= 0:
            from pathlib import Path as _P
            from .layout import resolve_mission
            from .missions import set_global_var

            mission_path = resolve_mission(p.mission, s, self.branch, p.mode)
            if mission_path and _P(mission_path).is_dir():
                # молча: значение задано в пресете, и повторять его в журнале
                # при каждом запуске незачем
                set_global_var(_P(mission_path), "TimeLogin", str(p.time_login))
                set_global_var(_P(mission_path), "TimeLogout", str(p.time_login))

        # 4.6. Права админок (COT/VPP) в папке профиля — до старта сервера,
        #      иначе мод создаст свои файлы с заглушкой и перечитает их только
        #      при следующем запуске
        from .admin_tools import apply as apply_admin_rights, sync_vpp_password_flag
        from .layout import resolve_profiles as _rp

        if s.admin_steamids or s.admin_password:
            profile_dir = _rp(p.profiles, s, self.branch, p.mode)
            for tool, added in apply_admin_rights(profile_dir, selected, s.admin_steamids, s.admin_password):
                if added:
                    self.log.emit(
                        tr("launch.admin_rights", "{tool}: выданы права админа ({n})", tool=tool.title, n=len(added)),
                        "info",
                    )

        # 4.7. vppDisablePassword в cfg — по факту наличия пароля в настройках
        from .layout import resolve_config as _rc

        flag = sync_vpp_password_flag(_rc(p.server_config, s, self.branch, p.mode), s.admin_password)
        if flag is not None:
            self.log.emit(tr("launch.vpp_password_flag", "serverDZ.cfg: vppDisablePassword = {v}", v=flag), "info")

        # 5. Сервер
        server_proc = None
        if p.launch_server:
            # командную строку в журнал не пишем: она длиннее ширины окна,
            # обрезается на середине и вытесняет всё остальное
            exe, args, cwd = build_server_command(p, s, self.branch, reg)
            # снимок логов до старта: ждать готовности надо по файлу этой
            # сессии, иначе прошлый лог с 5_Mission засчитается сразу
            from .layout import resolve_profiles as _rp2

            prof_dir = _rp2(p.profiles, s, self.branch, p.mode)
            server_logs = _script_logs(prof_dir)
            # Способ первый: просим Windows не показывать окно. Выполняется
            # на усмотрение самой программы, поэтому ниже есть и второй.
            hide = getattr(s, "hide_server_window", False)
            server_proc = subprocess.Popen([exe] + args, cwd=cwd, startupinfo=winhide.startupinfo() if hide else None)
            self.server_started.emit(server_proc.pid)
            # PID уже существует и следующий ярлык может безопасно найти его
            # по EXE/CFG/порту. Не держим mutex во время ожидания порта и
            # 5_Mission, иначе повторный Start не сможет прервать запуск.
            command_lock.release()
            if hide:
                # Способ второй: найти окно по процессу и скрыть. По тому,
                # нашлось ли что скрывать, видно, сработал ли первый.
                n, secs = winhide.hide(server_proc.pid)
                self.log.emit(
                    tr("launch.window_hidden", "Окно сервера скрыто (окон: {n}, через {t:.1f} с)", n=n, t=secs)
                    if n
                    else tr("launch.window_never_shown", "Окно сервера не появилось — хватило просьбы при запуске"),
                    "info",
                )

            # 6. Ожидание готовности сервера.
            #    Клиент не должен стартовать раньше: он тут же полезет
            #    подключаться, а сервер в это время ещё компилирует скрипты.
            #    Готовность — та же, по которой красятся индикаторы: занятый
            #    порт И скомпилированный слой 5_Mission (он последний).
            ps_proc = psutil.Process(server_proc.pid)
            t0 = time.monotonic()
            port_ok = mission_ok = False
            while time.monotonic() - t0 < READY_TIMEOUT:
                if server_proc.poll() is not None:
                    self.failed.emit(
                        tr(
                            "launch.server_died",
                            "Сервер завершился при запуске (код {code}). Смотрите RPT-лог.",
                            code=server_proc.returncode,
                        )
                    )
                    return
                port_ok = port_ok or _server_ready(ps_proc, p.port)
                mission_ok = mission_ok or scripts_ready(server_logs, prof_dir)
                if port_ok and mission_ok:
                    break
                time.sleep(0.5)
            # Сигналим в обоих случаях: процесс жив (иначе вышли бы по failed),
            # клиент всё равно запускается — кнопке незачем висеть в «Запускается».
            self.server_ready.emit()
            # про успех молчим — он виден по строке статуса «[запущен]»;
            # сообщаем только про нештатный случай
            if not (port_ok and mission_ok):
                missing = (
                    tr("launch.wait_port", "не занял порт")
                    if not port_ok
                    else tr("launch.wait_scripts", "не собрал скрипты миссии")
                )
                self.log.emit(
                    tr(
                        "launch.server_slow",
                        "Сервер {what} за {sec} с — запускаю клиент на свой страх.",
                        what=missing,
                        sec=READY_TIMEOUT,
                    ),
                    "warning",
                )

        # 7. Клиент
        if p.launch_client:
            # После ожидания сервера снова сериализуем изменение процессов.
            # Если другой ярлык уже перезапустил этот сервер, старый запуск не
            # должен продолжиться и запустить лишний клиент.
            command_lock.acquire()
            if server_proc is not None and server_proc.poll() is not None:
                self.failed.emit(
                    tr(
                        "launch.server_restarted",
                        "Предыдущий запуск сервера был заменён новой командой.",
                    )
                )
                return
            runtime_command = build_client_command(p, s, self.branch, reg)
            launch_exe, args, cwd = build_client_launch_command(p, s, self.branch, reg)
            runtime_exe = runtime_command[0]
            if _path_key(launch_exe) == _path_key(runtime_exe):
                client_proc = subprocess.Popen([launch_exe] + args, cwd=cwd)
                client_pid = client_proc.pid
            else:
                # BattlEye — промежуточный процесс. Запоминаем все прежние
                # процессы ожидаемого EXE, чтобы после запуска получить PID именно нового
                # DayZ_x64, а не случайно подхватить старый экземпляр.
                previous = _runtime_process_pids("client", runtime_command)
                battleye = subprocess.Popen([launch_exe] + args, cwd=cwd)
                client_proc = _wait_for_matching_process("client", runtime_command, previous)
                if client_proc is None:
                    try:
                        if battleye.poll() is None:
                            battleye.terminate()
                    except OSError:
                        pass
                    self.failed.emit(
                        tr(
                            "launch.client_be_failed",
                            "Не удалось определить запущенный DayZ_x64 за {sec} с. Проверьте окно игры.",
                            sec=CLIENT_SPAWN_TIMEOUT,
                        )
                    )
                    return
                client_pid = client_proc.pid
            self.client_started.emit(client_pid)

        self.finished_ok.emit()
