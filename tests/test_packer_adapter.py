from core import packer
from core.mods import ModInfo, SOURCE_LOCAL
from core.settings import Settings


def test_adapter_uses_byraizo_backend(monkeypatch, tmp_path):
    source = tmp_path / "source" / "MyAddon"
    source.mkdir(parents=True)
    mod_root = tmp_path / "@MyMod"
    (mod_root / "addons").mkdir(parents=True)
    mod = ModInfo(
        name="@MyMod",
        path=str(mod_root),
        source=SOURCE_LOCAL,
        sources=[str(source)],
    )
    settings = Settings(
        dayz_tools=str(tmp_path / "DayZ Tools"),
        pack_use_binarize=False,
        pack_convert_config=False,
        pack_preflight=True,
        pbo_last_project_root="P:",
    )
    captured = {}

    def fake_build(build_settings, log, progress):
        captured.update(build_settings)
        output = mod_root / "addons" / "MyAddon.pbo"
        output.write_bytes(b"PBO")
        log("Build finished")
        progress(1, 1)

    monkeypatch.setattr(packer, "build_all", fake_build)
    monkeypatch.setattr(packer, "get_logs_dir", lambda: tmp_path / "appdata" / "pbo" / "logs")
    monkeypatch.setattr(packer, "get_app_data_dir", lambda: tmp_path / "appdata" / "pbo")

    ok, error = packer.pack_source(settings, mod, str(source))
    assert ok, error
    assert captured["selected_addons"] == ["MyAddon"]
    assert captured["preflight_before_build"] is True
    assert captured["project_root"] == "P:"
    assert captured["output_root_dir"] == str(mod_root)
    assert (tmp_path / "appdata" / "pbo" / "logs" / "MyAddon.packing.log").is_file()


def test_build_config_prefers_explicit_builder_tools(monkeypatch, tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "@Output"
    source.mkdir()
    explicit_binarize = tmp_path / "custom" / "binarize.exe"
    explicit_cfgconvert = tmp_path / "custom" / "CfgConvert.exe"
    explicit_obfuscator = tmp_path / "custom" / "P3DObfuscator.exe"
    explicit_sign = tmp_path / "custom" / "DSSignFile.exe"
    settings = Settings(
        dayz_tools=str(tmp_path / "DayZ Tools"),
        pack_protect_p3d=True,
        pack_binarize_exe=str(explicit_binarize),
        pack_cfgconvert_exe=str(explicit_cfgconvert),
        pack_p3d_obfuscator_exe=str(explicit_obfuscator),
        pack_dssignfile_exe=str(explicit_sign),
        pack_temp_dir=str(tmp_path / "builder-temp"),
        pack_preflight_checks={"preflight_check_prefix": False},
    )

    config = packer.build_config(settings, source, output, ("Addon",))

    assert config.protect_p3d is True
    assert config.binarize_exe == str(explicit_binarize)
    assert config.cfgconvert_exe == str(explicit_cfgconvert)
    assert config.p3d_obfuscator_exe == str(explicit_obfuscator)
    assert config.dssignfile_exe == str(explicit_sign)
    assert config.temp_dir == str(tmp_path / "builder-temp")
    assert config["preflight_check_prefix"] is False
