import hashlib
import json
import os
from pathlib import Path

import pytest

from core.pbobuilder.errors import BuildError
from core.pbobuilder.build import build_all
from core.pbobuilder.models import BuildConfig, BuildResult
from core.pbobuilder.pbo import pack_pbo, replace_output_artifacts
from core.pbobuilder.validation import validate_pbo, validate_with_bankrev


def _log(_message: object) -> None:
    pass


def test_empty_pbo_has_valid_prefix_and_sha1(tmp_path):
    source = tmp_path / "empty"
    source.mkdir()
    output = tmp_path / "empty.pbo"

    pack_pbo(source, output, "RaiZo\\Empty", _log)
    report = validate_pbo(output, "RaiZo\\Empty")

    assert report.entries == ()
    assert len(report.sha1) == 40


def test_pbo_validator_reads_nested_entries_and_config_bin(tmp_path):
    source = tmp_path / "addon"
    nested = source / "scripts" / "5_Mission"
    nested.mkdir(parents=True)
    (source / "config.bin").write_bytes(b"\x00raP")
    (nested / "main.c").write_text("void main() {}", encoding="ascii")
    output = tmp_path / "addon.pbo"

    pack_pbo(source, output, "RaiZo\\Addon", _log)
    report = validate_pbo(output, "RaiZo\\Addon")

    assert [entry.name for entry in report.entries] == [
        "config.bin",
        "scripts\\5_Mission\\main.c",
    ]
    assert sum(entry.data_size for entry in report.entries) == 18


def test_pbo_validator_rejects_corrupt_sha1_footer(tmp_path):
    source = tmp_path / "addon"
    source.mkdir()
    (source / "data.bin").write_bytes(b"payload")
    output = tmp_path / "addon.pbo"
    pack_pbo(source, output, "RaiZo\\Addon", _log)
    data = bytearray(output.read_bytes())
    data[-1] ^= 0xFF
    output.write_bytes(data)

    with pytest.raises(BuildError, match="SHA1 footer mismatch"):
        validate_pbo(output)


def test_pbo_validator_rejects_case_insensitive_duplicate_entries(tmp_path):
    source = tmp_path / "addon"
    source.mkdir()
    (source / "a.bin").write_bytes(b"a")
    (source / "b.bin").write_bytes(b"b")
    output = tmp_path / "addon.pbo"
    pack_pbo(source, output, "RaiZo\\Addon", _log)
    data = output.read_bytes().replace(b"b.bin\0", b"A.bin\0", 1)
    output.write_bytes(data)

    with pytest.raises(BuildError, match="duplicate entry"):
        validate_pbo(output)


def test_packer_rejects_non_ascii_entry_names(tmp_path):
    source = tmp_path / "addon"
    source.mkdir()
    (source / "данные.bin").write_bytes(b"x")

    with pytest.raises(BuildError, match="File path"):
        pack_pbo(source, tmp_path / "addon.pbo", "RaiZo\\Addon", _log)


def test_publish_rolls_back_pbo_and_signature_on_failure(monkeypatch, tmp_path):
    final_dir = tmp_path / "published"
    work_dir = tmp_path / "work"
    final_dir.mkdir()
    work_dir.mkdir()
    final_pbo = final_dir / "addon.pbo"
    temp_pbo = work_dir / "addon.pbo"
    old_signature = final_dir / "addon.pbo.old.bisign"
    new_signature = work_dir / "addon.pbo.new.bisign"
    final_pbo.write_bytes(b"old-pbo")
    old_signature.write_bytes(b"old-signature")
    temp_pbo.write_bytes(b"new-pbo")
    new_signature.write_bytes(b"new-signature")
    real_replace = os.replace

    def fail_signature_publish(source, destination):
        if str(destination).endswith(".bisign"):
            raise OSError("locked signature")
        return real_replace(source, destination)

    monkeypatch.setattr("core.pbobuilder.pbo.os.replace", fail_signature_publish)

    with pytest.raises(BuildError, match="Output publish failed"):
        replace_output_artifacts(temp_pbo, final_pbo, True, _log)

    assert final_pbo.read_bytes() == b"old-pbo"
    assert old_signature.read_bytes() == b"old-signature"


def test_optional_bankrev_validator_uses_list_mode(monkeypatch, tmp_path):
    executable = tmp_path / "BankRev.exe"
    executable.touch()
    pbo = tmp_path / "addon.pbo"
    pbo.touch()
    calls = []

    class Result:
        returncode = 0
        stdout = "config.bin"

    monkeypatch.setattr(
        "core.pbobuilder.validation.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    assert validate_with_bankrev(pbo, str(executable), _log) is True
    assert calls[0][0] == [str(executable), "-l", str(pbo)]


def test_reference_pbo_matches_golden_manifest(tmp_path):
    manifest_path = Path(__file__).parent / "fixtures" / "pbo" / "reference_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = tmp_path / "reference"
    nested = source / "scripts" / "5_Mission"
    nested.mkdir(parents=True)
    files = {
        source / "config.bin": b"\x00raP-reference",
        nested / "main.c": b"void main() {}\n",
    }
    for path, content in files.items():
        path.write_bytes(content)
        os.utime(path, (1_700_000_000, 1_700_000_000))
    output = tmp_path / "reference.pbo"

    pack_pbo(source, output, manifest["prefix"], _log)
    report = validate_pbo(output, manifest["prefix"])

    assert [entry.name for entry in report.entries] == manifest["entries"]
    assert hashlib.sha256(output.read_bytes()).hexdigest() == manifest["sha256"]


def test_typed_pipeline_builds_and_validates_real_pbo(tmp_path):
    source = tmp_path / "MyAddon"
    source.mkdir()
    (source / "config.cpp").write_text("class CfgPatches {};", encoding="ascii")
    output = tmp_path / "@MyMod"
    config = BuildConfig(
        source_root=str(source),
        output_root_dir=str(output),
        output_server_root_dir=str(output),
        temp_dir=str(tmp_path / "temp"),
        use_binarize=False,
        convert_config=False,
        sign_pbos=False,
        binarize_exe="",
        cfgconvert_exe="",
        dssignfile_exe="",
        private_key="",
        exclude_patterns="",
        project_root=str(tmp_path),
        pbo_name="",
        max_processes=1,
        selected_addons=("MyAddon",),
        force_rebuild=True,
    )

    result = build_all(config, _log, lambda _done, _total: None)
    pbo = output / "Addons" / "MyAddon.pbo"

    assert isinstance(result, BuildResult)
    assert result.built == 1
    assert validate_pbo(pbo, "MyAddon").entries[0].name == "config.cpp"
