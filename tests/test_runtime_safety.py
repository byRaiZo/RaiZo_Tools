from pathlib import Path
from typing import cast

from core import adopt, launcher
from core.launcher import clear_launch_logs, matching_processes, stop_processes
from core.mods import ModRegistry
from core.presets import MODE_DEDICATED, ServerPreset
from core.settings import Settings


class EmptyRegistry:
    def get(self, _name):
        return None


class FakeProcess:
    def __init__(self, pid: int, exe: Path, args: list[str], cwd: Path):
        self.pid = pid
        self.info = {"name": exe.name}
        self._exe = str(exe)
        self._args = args
        self._cwd = str(cwd)
        self.killed = False

    def name(self):
        return Path(self._exe).name

    def exe(self):
        return self._exe

    def cmdline(self):
        return list(self._args)

    def cwd(self):
        return self._cwd

    def create_time(self):
        return 1.0

    def kill(self):
        self.killed = True

    def wait(self, timeout):
        del timeout


class StoppableProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_process_matching_does_not_select_other_port(monkeypatch, tmp_path):
    server_root = tmp_path / "DayZServer"
    settings = Settings(
        client_stable=str(tmp_path / "DayZ"),
        server_stable=str(server_root),
    )
    preset = ServerPreset(
        mode=MODE_DEDICATED,
        server_config="serverDZ.cfg",
        mission="dayzOffline.chernarusplus",
        profiles="profiles",
        port=2302,
    )
    exe = server_root / "DayZServer_x64.exe"
    target = FakeProcess(
        10,
        exe,
        ["DayZServer_x64.exe", "-config=serverDZ.cfg", "-profiles=profiles", "-port=2302"],
        server_root,
    )
    foreign = FakeProcess(
        11,
        exe,
        ["DayZServer_x64.exe", "-config=serverDZ.cfg", "-profiles=profiles", "-port=2402"],
        server_root,
    )
    other_install = FakeProcess(
        12,
        tmp_path / "OtherServer" / "DayZServer_x64.exe",
        ["DayZServer_x64.exe", "-config=serverDZ.cfg", "-profiles=profiles", "-port=2302"],
        tmp_path / "OtherServer",
    )
    monkeypatch.setattr(
        launcher.psutil,
        "process_iter",
        lambda _attrs: [target, foreign, other_install],
    )

    found = matching_processes(
        preset,
        settings,
        "stable",
        cast(ModRegistry, EmptyRegistry()),
        {"server"},
    )
    assert [process.pid for process in found] == [10]


def test_soft_stop_posts_wm_close_before_force(monkeypatch):
    process = StoppableProcess(30)
    closed = []
    monkeypatch.setattr(launcher.winhide, "ask_close", lambda pid: closed.append(pid) or 1)
    monkeypatch.setattr(
        launcher.psutil,
        "wait_procs",
        lambda processes, timeout: (list(processes), []),
    )

    assert (
        stop_processes(
            [cast(launcher.psutil.Process, process)],
            timeout=15,
        )
        == 1
    )
    assert closed == [30]
    assert not process.terminated
    assert not process.killed


def test_force_restart_kills_immediately_without_wm_close(monkeypatch):
    process = StoppableProcess(31)
    closed = []
    monkeypatch.setattr(launcher.winhide, "ask_close", lambda pid: closed.append(pid) or 1)
    monkeypatch.setattr(
        launcher.psutil,
        "wait_procs",
        lambda processes, timeout: (list(processes), []),
    )

    assert stop_processes([cast(launcher.psutil.Process, process)], force=True) == 1
    assert closed == []
    assert process.killed
    assert not process.terminated


def test_server_command_lock_is_released_before_readiness_wait(monkeypatch, tmp_path):
    events: list[str] = []

    class FakeCommandLock:
        acquired = True

        def release(self) -> None:
            events.append("release")
            self.acquired = False

        def acquire(self) -> None:
            events.append("acquire")
            self.acquired = True

    class SpawnedServer:
        pid = 4321
        returncode = None

        def poll(self):
            return None

    settings = Settings(
        client_stable=str(tmp_path / "DayZ"),
        server_stable=str(tmp_path / "DayZServer"),
        repack_before_launch=False,
    )
    preset = ServerPreset(
        mode=MODE_DEDICATED,
        server_config="serverDZ.cfg",
        mission="dayzOffline.chernarusplus",
        profiles="profiles",
        launch_server=True,
        launch_client=False,
    )
    command_lock = FakeCommandLock()

    monkeypatch.setattr(launcher, "matching_processes", lambda *_args: [])
    monkeypatch.setattr(launcher, "stop_processes", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        launcher,
        "build_server_command",
        lambda *_args: (str(tmp_path / "DayZServer_x64.exe"), [], str(tmp_path)),
    )
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *_args, **_kwargs: events.append("spawn") or SpawnedServer()
    )
    monkeypatch.setattr(launcher.psutil, "Process", lambda _pid: object())

    def ready(_process, _port):
        assert command_lock.acquired is False
        events.append("ready")
        return True

    monkeypatch.setattr(launcher, "_server_ready", ready)
    monkeypatch.setattr(launcher, "scripts_ready", lambda *_args: True)

    worker = launcher.LaunchWorker(preset, settings, "stable", cast(ModRegistry, EmptyRegistry()))
    worker._run_locked(cast(launcher.ProcessCommandLock, command_lock))

    assert events[:3] == ["spawn", "release", "ready"]


def test_shared_profiles_adoption_uses_cfg_port_and_exe(monkeypatch, tmp_path):
    server_root = tmp_path / "DayZServer"
    exe = server_root / "DayZServer_x64.exe"
    process = FakeProcess(
        20,
        exe,
        ["DayZServer_x64.exe", "-config=serverDZ_B.cfg", "-profiles=profiles", "-port=2402"],
        server_root,
    )
    monkeypatch.setattr(adopt, "_processes", lambda: [process])

    profiles = {
        "A": str(server_root / "profiles"),
        "B": str(server_root / "profiles"),
    }
    identities = {
        "A": (str(server_root / "serverDZ_A.cfg"), 2302, str(exe)),
        "B": (str(server_root / "serverDZ_B.cfg"), 2402, str(exe)),
    }
    found = adopt.find(profiles, identities)
    assert len(found) == 1
    assert found[0].preset == "B"


def test_recursive_log_cleanup_preserves_mods_missions_and_storage(tmp_path):
    server_root = tmp_path / "DayZServer"
    nested_log = server_root / "profiles" / "CodeLock" / "Logs" / "codelock.log"
    dump = server_root / "profiles" / "crash.mdmp"
    mission_log = server_root / "mpmissions" / "dayzOffline.chernarusplus" / "storage_1" / "keep.log"
    mod_log = server_root / "MODS" / "@SL" / "keep.log"
    key_log = server_root / "keys" / "keep.log"
    for path in (nested_log, dump, mission_log, mod_log, key_log):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    settings = Settings(
        client_stable=str(tmp_path / "DayZ"),
        server_stable=str(server_root),
    )
    removed = clear_launch_logs(ServerPreset(), settings, "stable", {"server"})

    assert removed == 2
    assert not nested_log.exists()
    assert not dump.exists()
    assert mission_log.exists()
    assert mod_log.exists()
    assert key_log.exists()


def test_windows_extra_arguments_preserve_quotes_unicode_and_empty_values():
    args = launcher.parse_extra_args(
        '-profiles="C:\\DayZ Server\\Профиль" -name="Тестовый сервер" -token=abc=123 -empty="" ""'
    )

    assert args == [
        "-profiles=C:\\DayZ Server\\Профиль",
        "-name=Тестовый сервер",
        "-token=abc=123",
        "-empty=",
        "",
    ]


def test_kill_pid_rejects_reused_pid(monkeypatch, tmp_path):
    process = FakeProcess(
        55,
        tmp_path / "DayZServer_x64.exe",
        ["DayZServer_x64.exe", "-config=serverDZ.cfg", "-port=2302"],
        tmp_path,
    )
    identity = launcher.ProcessIdentity(
        pid=55,
        create_time=0.5,
        exe=launcher._path_key(process.exe()),
        kind="server",
        config=launcher._arg_path(process.cmdline(), "-config=", process.cwd()),
        port="2302",
        connect="",
    )
    monkeypatch.setattr(launcher.psutil, "Process", lambda _pid: process)

    assert launcher.kill_pid(identity) is False
    assert process.killed is False
