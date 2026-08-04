from pathlib import Path

import pytest

from core.pbobuilder.cli import build_cli_settings, build_parser, derive_output_from_pack_target, is_cli_invocation
from core.settings import Settings


def test_detects_original_cli_markers() -> None:
    assert is_cli_invocation(["-pack", "src", "out"])
    assert is_cli_invocation(["-binarizeP3D"])
    assert is_cli_invocation(["--install-pbo-context-menu"])
    assert is_cli_invocation(["--no-wait"])
    assert not is_cli_invocation([])


def test_derives_original_pbo_manager_output() -> None:
    output_root, pbo_name = derive_output_from_pack_target(
        r"F:\Steam\steamapps\common\DayZServer\@RaiZoClient_Main\Addons\RZ_Weapons.pbo"
    )

    assert output_root == r"F:\Steam\steamapps\common\DayZServer\@RaiZoClient_Main"
    assert pbo_name == "RZ_Weapons"


def test_original_flags_default_to_disabled(tmp_path: Path) -> None:
    source = tmp_path / "RZ_Weapons"
    source.mkdir()
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    output = tmp_path / "@Client" / "Addons" / "RZ_Weapons.pbo"
    args = build_parser().parse_args(["-pack", str(source), str(output)])

    config = build_cli_settings(args, Settings())

    assert not config.use_binarize
    assert not config.convert_config
    assert not config.force_rebuild
    assert not config.sign_pbos
    assert not config.protect_p3d
    assert not config.preflight_before_build


def test_saved_options_are_used_by_context_menu(tmp_path: Path) -> None:
    source = tmp_path / "RZ_Weapons"
    source.mkdir()
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    output = tmp_path / "@Client"
    settings = Settings(
        pbo_last_output_root=str(output),
        pack_use_binarize=True,
        pack_convert_config=True,
        pack_preflight=True,
        pack_engine="full",
    )
    args = build_parser().parse_args(["--pack-folder", str(source), "--saved-options"])

    config = build_cli_settings(args, settings)

    assert config.output_root_dir == str(output)
    assert config.use_binarize
    assert config.convert_config
    assert config.preflight_before_build
    assert config.force_rebuild


def test_explicit_flags_override_saved_options(tmp_path: Path) -> None:
    source = tmp_path / "Addon"
    source.mkdir()
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    settings = Settings(pbo_last_output_root=str(tmp_path / "out"), pack_use_binarize=True)
    args = build_parser().parse_args(
        ["--pack-folder", str(source), "--saved-options", "--no-binarize", "-forceRebuild"]
    )

    config = build_cli_settings(args, settings)

    assert not config.use_binarize
    assert config.force_rebuild


def test_pack_folder_requires_saved_or_explicit_output(tmp_path: Path) -> None:
    source = tmp_path / "Addon"
    source.mkdir()
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="utf-8")
    args = build_parser().parse_args(["--pack-folder", str(source)])

    with pytest.raises(Exception, match="Output root"):
        build_cli_settings(args, Settings())
