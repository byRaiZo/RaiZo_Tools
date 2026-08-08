from pathlib import Path
from typing import cast

from core.launcher import build_client_command, build_client_launch_command, build_server_command
from core.preflight import run_checks
from core.layout import (
    create_server_config,
    ensure_layout,
    mods_link_dir,
    resolve_config,
    resolve_mission,
    resolve_profiles,
    server_configs,
)
from core.presets import MODE_DEDICATED, MODE_DIAG, ServerPreset
from core.mods import ModRegistry
from core.settings import Settings


class EmptyRegistry:
    def get(self, _name):
        return None


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        client_stable=str(tmp_path / "DayZ"),
        server_stable=str(tmp_path / "DayZServer"),
    )


def test_only_mods_is_created(tmp_path):
    root = tmp_path / "DayZServer"
    ensure_layout(root)
    assert (root / "MODS").is_dir()
    assert not (root / "profiles").exists()
    assert not (root / "mpmissions").exists()


def test_paths_resolve_directly_in_server_root(tmp_path):
    settings = settings_for(tmp_path)
    assert resolve_config("serverDZ.cfg", settings, "stable", MODE_DIAG) == str(
        tmp_path / "DayZServer" / "serverDZ.cfg"
    )
    assert resolve_profiles("legacy-profile", settings, "stable", MODE_DIAG) == str(
        tmp_path / "DayZServer" / "profiles"
    )
    assert resolve_mission("dayzOffline.chernarusplus", settings, "stable", MODE_DIAG) == str(
        tmp_path / "DayZServer" / "mpmissions" / "dayzOffline.chernarusplus"
    )
    assert mods_link_dir(settings.server_stable) == tmp_path / "DayZServer" / "MODS"


def test_existing_cfg_can_be_reused_and_new_cfg_is_explicit(tmp_path):
    settings = settings_for(tmp_path)
    root = tmp_path / "DayZServer"
    root.mkdir()
    shared = root / "serverDZ.cfg"
    shared.write_text("shared", encoding="utf-8")
    (root / "z_custom.cfg").write_text("custom", encoding="utf-8")
    (root / "ignore.txt").write_text("not cfg", encoding="utf-8")

    assert server_configs(settings, "stable", MODE_DIAG) == [
        "serverDZ.cfg",
        "z_custom.cfg",
    ]

    created = create_server_config(
        settings,
        "stable",
        MODE_DIAG,
        "NewPreset",
        "dayzOffline.chernarusplus",
    )
    assert created == "serverDZ_NewPreset_chernarusplus.cfg"
    assert (root / created).is_file()
    assert shared.read_text(encoding="utf-8") == "shared"


def test_preflight_uses_selected_mission_not_cfg_template(tmp_path):
    settings = settings_for(tmp_path)
    client = tmp_path / "DayZ"
    server = tmp_path / "DayZServer"
    mission = server / "mpmissions" / "dayzOffline.chernarusplus"
    client.mkdir()
    mission.mkdir(parents=True)
    (server / "DayZServer_x64.exe").touch()
    (server / "serverDZ_Diag_chernarusplus.cfg").write_text(
        'class Missions { class DayZ { template = "Diag.chernarusplus"; }; };',
        encoding="utf-8",
    )
    preset = ServerPreset(
        mode=MODE_DEDICATED,
        server_config="serverDZ_Diag_chernarusplus.cfg",
        mission="dayzOffline.chernarusplus",
        launch_client=False,
    )

    problems = run_checks(
        preset,
        settings,
        "stable",
        cast(ModRegistry, EmptyRegistry()),
    )

    assert "mission" not in {problem.check_id for problem in problems}
    assert "cfg_mission" not in {problem.check_id for problem in problems}


def test_relative_standard_and_diag_commands(tmp_path):
    settings = settings_for(tmp_path)
    registry = cast(ModRegistry, EmptyRegistry())
    preset = ServerPreset(
        mode=MODE_DEDICATED,
        server_config="serverDZ.cfg",
        mission="dayzOffline.chernarusplus",
        profiles="profiles",
        params_server={"filePatching": True},
        params_client={"filePatching": True},
        extra_server="-filePatching -filePatching=1",
        extra_client="-filePatching -filePatching=1",
        mods=["@SL"],
        launch_client=True,
    )
    _exe, args, _cwd = build_server_command(preset, settings, "stable", registry)
    assert "-config=serverDZ.cfg" in args
    assert "-profiles=profiles" in args
    assert "-mission=mpmissions\\dayzOffline.chernarusplus" in args
    assert "-mod=MODS\\@SL" in args
    assert not any(arg.lower().startswith("-filepatching") for arg in args)

    _exe, client_args, _cwd = build_client_command(preset, settings, "stable", registry)
    assert not any(arg.lower().startswith("-filepatching") for arg in client_args)

    preset.mode = MODE_DIAG
    preset.params_server = {}
    preset.params_client = {}
    preset.extra_server = ""
    preset.extra_client = ""
    _exe, diag_args, _cwd = build_server_command(preset, settings, "stable", registry)
    expected = str(tmp_path / "DayZServer" / "profiles")
    assert f"-profiles={expected}" in diag_args
    assert f"-mod={tmp_path / 'DayZServer' / 'MODS' / '@SL'}" in diag_args
    for expected_arg in (
        "-filePatching=1",
        "-battleye=0",
        "-newErrorsAreWarnings=1",
        "-doLogs",
        "-adminLog",
        "-netLog",
        "-noPause",
    ):
        assert expected_arg in diag_args

    _exe, client_args, _cwd = build_client_command(preset, settings, "stable", registry)
    assert client_args[0] == "-connect=127.0.0.1:2302"
    assert f"-mod={tmp_path / 'DayZServer' / 'MODS' / '@SL'}" in client_args
    assert ".." not in next(arg for arg in client_args if arg.startswith("-mod="))
    for expected_arg in (
        "-filePatching=1",
        "-battleye=0",
        "-newErrorsAreWarnings=1",
        "-noPause",
        "-window",
    ):
        assert expected_arg in client_args


def test_dedicated_client_starts_through_battleye_launcher(tmp_path):
    settings = settings_for(tmp_path)
    registry = cast(ModRegistry, EmptyRegistry())
    preset = ServerPreset(mode=MODE_DEDICATED, launch_server=False, launch_client=True)

    runtime_exe, runtime_args, runtime_cwd = build_client_command(preset, settings, "stable", registry)
    launch_exe, launch_args, launch_cwd = build_client_launch_command(preset, settings, "stable", registry)

    assert Path(runtime_exe).name == "DayZ_x64.exe"
    assert Path(launch_exe).name == "DayZ_BE.exe"
    assert launch_args == runtime_args
    assert launch_cwd == runtime_cwd

    preset.client_use_diag = True
    runtime_exe, _runtime_args, _runtime_cwd = build_client_command(preset, settings, "stable", registry)
    launch_exe, _launch_args, _launch_cwd = build_client_launch_command(preset, settings, "stable", registry)

    assert Path(runtime_exe).name == "DayZDiag_x64.exe"
    assert launch_exe == runtime_exe


def test_preflight_requires_battleye_launcher_for_dedicated_client(tmp_path):
    settings = settings_for(tmp_path)
    registry = cast(ModRegistry, EmptyRegistry())
    client = tmp_path / "DayZ"
    server = tmp_path / "DayZServer"
    mission = server / "mpmissions" / "dayzOffline.chernarusplus"
    client.mkdir()
    mission.mkdir(parents=True)
    (client / "DayZ_x64.exe").touch()
    (server / "DayZServer_x64.exe").touch()
    (server / "serverDZ.cfg").touch()
    preset = ServerPreset(
        mode=MODE_DEDICATED,
        server_config="serverDZ.cfg",
        mission="dayzOffline.chernarusplus",
        launch_server=False,
        launch_client=True,
    )

    problems = run_checks(preset, settings, "stable", registry)
    assert "client_be_exe" in {problem.check_id for problem in problems}

    (client / "DayZ_BE.exe").touch()
    problems = run_checks(preset, settings, "stable", registry)
    assert "client_be_exe" not in {problem.check_id for problem in problems}
