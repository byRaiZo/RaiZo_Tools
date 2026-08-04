"""Пресеты сервера и пресеты модов."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .settings import PRESETS_DIR, MOD_PRESETS_DIR, STABLE, atomic_write_json

MODE_DEDICATED = "dedicated"
MODE_DIAG = "diag"


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return s or "preset"


@dataclass
class ServerPreset:
    name: str = "Новый пресет"
    mode: str = MODE_DIAG  # dedicated | diag
    branch: str = STABLE  # ветка по умолчанию
    client_use_diag: bool = False  # в dedicated-режиме клиент = DayZDiag

    # Пути (относительно корня клиента или абсолютные)
    server_config: str = ""
    mission: str = ""
    profiles: str = ""
    server_ip: str = "127.0.0.1"
    port: int = 2302
    time_login: int = -1  # TimeLogin в db/globals.xml миссии; -1 — не трогать
    clean_logs: bool = False

    # Параметры запуска: имя -> значение (только явно выставленные)
    params_server: dict = field(default_factory=dict)
    params_client: dict = field(default_factory=dict)
    extra_server: str = ""  # доп. аргументы свободным текстом
    extra_client: str = ""

    # Моды: имена из реестра модов; порядок = порядок загрузки
    mods: list[str] = field(default_factory=list)  # -mod (клиент + сервер)
    server_mods: list[str] = field(default_factory=list)  # -serverMod

    # Состояние галок запуска
    launch_server: bool = True
    launch_client: bool = True

    @property
    def world(self) -> str:
        return self.mission.rsplit(".", 1)[1] if "." in self.mission else ""

    def file_stem(self) -> str:
        """Имя файла пресета: <имя>_<карта> — одно имя допустимо на разных картах."""
        return _slug(f"{self.name}_{self.world}" if self.world else self.name)

    def path(self) -> Path:
        return PRESETS_DIR / f"{self.file_stem()}.json"

    def save(self) -> None:
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        new_path = self.path()
        atomic_write_json(new_path, asdict(self))
        # имя или карта изменились — файл переехал, старый убираем
        src = getattr(self, "_src", None)
        if src and Path(src) != new_path:
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass
        self._src = new_path

    def delete(self) -> None:
        try:
            Path(getattr(self, "_src", self.path())).unlink(missing_ok=True)
        except OSError:
            pass

    @classmethod
    def from_dict(cls, data: dict) -> ServerPreset:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load_all(cls) -> list[ServerPreset]:
        out = []
        if PRESETS_DIR.is_dir():
            for f in sorted(PRESETS_DIR.glob("*.json")):
                try:
                    p = cls.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    p._src = f  # откуда загружен — для переезда файла при переименовании
                    out.append(p)
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
        return out


@dataclass
class ModPreset:
    """Именованный набор модов — шаблон для быстрого применения к пресету сервера."""

    name: str = "Набор модов"
    mods: list[str] = field(default_factory=list)
    server_mods: list[str] = field(default_factory=list)

    def save(self) -> None:
        MOD_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(MOD_PRESETS_DIR / f"{_slug(self.name)}.json", asdict(self))

    @classmethod
    def load_all(cls) -> list[ModPreset]:
        out = []
        if MOD_PRESETS_DIR.is_dir():
            for f in sorted(MOD_PRESETS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    out.append(
                        cls(
                            name=data.get("name", f.stem),
                            mods=data.get("mods", []),
                            server_mods=data.get("server_mods", []),
                        )
                    )
                except (OSError, json.JSONDecodeError):
                    continue
        return out


def _same_mod(a: str, b: str) -> bool:
    """Один ли это мод. Сравниваем как реестр: с «@» впереди и без регистра —
    в пресетах имя могло быть записано и так и так."""

    def norm(s: str) -> str:
        s = s.strip()
        return (s if s.startswith("@") else "@" + s).lower()

    return norm(a) == norm(b)


def apply_server_flag(mod_name: str, is_server: bool) -> list[str]:
    """Раскладывает мод по строкам запуска во всех пресетах. Возвращает имена
    тех, где что-то изменилось.

    Признак «серверный» — свойство самого мода, а не пресета, но подключён мод
    в пресете списком: -mod или -serverMod. Раньше метку меняли, а подключённые
    экземпляры оставались где были — мод продолжал уходить не в ту строку
    запуска, и человек видел ту же ошибку, ради которой метку и ставил.

    Затрагиваются только пресеты, где мод уже подключён: молча добавлять его
    туда, где его не было, нельзя.
    """
    changed: list[str] = []
    for p in ServerPreset.load_all():
        src, dst = (p.mods, p.server_mods) if is_server else (p.server_mods, p.mods)
        moved = [n for n in src if _same_mod(n, mod_name)]
        if not moved:
            continue
        src[:] = [n for n in src if not _same_mod(n, mod_name)]
        for n in moved:
            if not any(_same_mod(x, n) for x in dst):
                dst.append(n)
        p.save()
        changed.append(p.name)
    return changed
