from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

LogCallback = Callable[[object], None]
ProgressCallback = Callable[[int, int], None]


def _text(settings: Mapping[str, Any], key: str, default: str = "") -> str:
    value = settings.get(key, default)
    return str(value) if value is not None else default


@dataclass(frozen=True, slots=True)
class BuildConfig(Mapping[str, Any]):
    source_root: str
    output_root_dir: str
    temp_dir: str
    use_binarize: bool
    convert_config: bool
    sign_pbos: bool
    binarize_exe: str
    cfgconvert_exe: str
    dssignfile_exe: str
    private_key: str
    exclude_patterns: str
    project_root: str
    pbo_name: str
    max_processes: int
    selected_addons: tuple[str, ...]
    output_server_root_dir: str = ""
    protect_p3d: bool = False
    p3d_obfuscator_exe: str = ""
    force_rebuild: bool = False
    preflight_before_build: bool = False
    external_validator_exe: str = ""
    log_file: str = ""
    preflight_checks: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, settings: Mapping[str, Any]) -> BuildConfig:
        return cls(
            source_root=_text(settings, "source_root"),
            output_root_dir=_text(settings, "output_root_dir"),
            output_server_root_dir=_text(settings, "output_server_root_dir"),
            temp_dir=_text(settings, "temp_dir"),
            use_binarize=bool(settings.get("use_binarize", False)),
            protect_p3d=bool(settings.get("protect_p3d", False)),
            convert_config=bool(settings.get("convert_config", False)),
            sign_pbos=bool(settings.get("sign_pbos", False)),
            force_rebuild=bool(settings.get("force_rebuild", False)),
            preflight_before_build=bool(settings.get("preflight_before_build", False)),
            binarize_exe=_text(settings, "binarize_exe"),
            p3d_obfuscator_exe=_text(settings, "p3d_obfuscator_exe"),
            cfgconvert_exe=_text(settings, "cfgconvert_exe"),
            dssignfile_exe=_text(settings, "dssignfile_exe"),
            private_key=_text(settings, "private_key"),
            exclude_patterns=_text(settings, "exclude_patterns"),
            project_root=_text(settings, "project_root"),
            pbo_name=_text(settings, "pbo_name"),
            max_processes=max(1, int(settings.get("max_processes", 1))),
            selected_addons=tuple(str(item) for item in settings.get("selected_addons", ())),
            external_validator_exe=_text(settings, "external_validator_exe"),
            log_file=_text(settings, "log_file"),
            preflight_checks={
                str(key): bool(value) for key, value in dict(settings.get("preflight_checks", {})).items()
            },
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["selected_addons"] = list(self.selected_addons)
        data.update(self.preflight_checks)
        return data

    def __getitem__(self, key: str) -> Any:
        return self.as_legacy_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_legacy_dict())

    def __len__(self) -> int:
        return len(self.as_legacy_dict())


@dataclass(frozen=True, slots=True)
class BuildPaths:
    source_root: str
    output_client_root: str
    output_server_root: str
    output_client_addons: str
    output_client_keys: str
    output_server_addons: str
    output_server_keys: str
    temp_root: str


@dataclass(frozen=True, slots=True)
class BuildJob:
    folder_name: str
    folder_path: str
    output_pbo: str
    output_kind: str
    output_keys_dir: str
    sign_output: bool
    temp_output_pbo: str
    output_work_dir: str
    prefix: str
    pack_source: str
    folder_has_p3d: bool
    staging_dir: str
    binarized_dir: str
    binarize_source: str
    state_hash: str


@dataclass(slots=True)
class BuildResult:
    built: int = 0
    skipped: int = 0
    signed: int = 0
    failed: int = 0
    keys_copied: int = 0
    p3d_recovered: int = 0
    targets: int = 0
    log_file: str = ""
    elapsed: float = 0.0

    def as_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def normalized_paths(config: BuildConfig) -> BuildPaths:
    source = str(Path(config.source_root))
    client = str(Path(config.output_root_dir))
    server = str(Path(config.output_server_root_dir or client))
    return BuildPaths(
        source_root=source,
        output_client_root=client,
        output_server_root=server,
        output_client_addons=str(Path(client) / "Addons"),
        output_client_keys=str(Path(client) / "Keys"),
        output_server_addons=str(Path(server) / "Addons"),
        output_server_keys=str(Path(server) / "Keys"),
        temp_root=str(Path(config.temp_dir)),
    )
