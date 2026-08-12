"""Опознание уже запущенных клиента и сервера DayZ.

Менеджер можно закрыть и открыть заново, а сервер живёт своей жизнью — это
сделано намеренно, отдельный процесс не должен умирать вместе с окном. Но
новый экземпляр менеджера про него ничего не знал: показывал «остановлен»,
предлагал запустить и молчал про занятый порт. Человек либо поднимал второй
сервер поверх первого, либо шёл убивать процесс через диспетчер задач.

Опознаём по командной строке. Она читается у процессов того же пользователя —
а сервер и клиент запускает само приложение, — и содержит всё нужное:

    -server -config=serverDZ.cfg -profiles=profiles -port=2302
    -connect=127.0.0.1:2302

Пути в ней могут быть относительными, считать их надо от рабочей папки
процесса. Сервер опознаётся по совокупности EXE, CFG, profiles и порта; по
порту найденного сервера — клиент, который к нему подключён.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# Имена, под которыми DayZ работает клиентом или сервером. Diag-сборка служит и
# тем и другим, отличается флагом -server.
_EXE_NAMES = {"dayz_x64.exe", "dayzdiag_x64.exe", "dayzserver_x64.exe"}

SERVER, CLIENT = "server", "client"


@dataclass
class Running:
    """Найденный процесс DayZ."""

    pid: int
    side: str  # SERVER | CLIENT
    exe: str = ""
    started: float = 0.0
    port: int = 0
    profiles: str = ""  # абсолютный путь, если удалось вычислить
    preset: str = ""  # имя пресета, если опознан
    args: list[str] = field(default_factory=list)

    @property
    def mine(self) -> bool:
        """Наш ли это процесс — то есть нашлось ли, к какому пресету он относится."""
        return bool(self.preset)


def _arg(args: list[str], prefix: str) -> str:
    for a in args:
        if a.lower().startswith(prefix):
            return a[len(prefix) :]
    return ""


def _processes() -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in _EXE_NAMES:
            out.append(p)
    return out


def _path_key(value: str, cwd: str = "") -> str:
    path = Path(value)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return os.path.normcase(os.path.abspath(str(path)))


def find(
    preset_profiles: dict[str, str] | None = None,
    preset_identities: dict[str, tuple[str, int, str]] | None = None,
    client_preset: str = "",
) -> list[Running]:
    """Все живые процессы DayZ; опознанные помечены именем пресета.

    При общем profiles одного пути недостаточно. Поэтому сервер сопоставляется
    одновременно по профилю, CFG, порту и полному пути EXE.

    preset_identities: {имя: (абсолютный CFG, порт, абсолютный EXE)}.
    Клиент можно привязать к выбранному пресету без чтения его аргументов:
    BattlEye закрывает ``cmdline`` уже после успешного запуска DayZ_x64.
    """
    profile_names: dict[str, set[str]] = {}
    for name, path in (preset_profiles or {}).items():
        if path:
            profile_names.setdefault(_path_key(path), set()).add(name)
    identities = preset_identities or {}
    config_names: dict[str, set[str]] = {}
    for name, (config, _port, _exe) in identities.items():
        if config:
            config_names.setdefault(_path_key(config), set()).add(name)
    all_names = set(identities)
    for names in profile_names.values():
        all_names.update(names)

    out: list[Running] = []
    for p in _processes():
        try:
            args = p.cmdline()
            cwd = p.cwd()
            exe = p.exe()
            started = p.create_time()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            # BattlEye закрывает cmdline/cwd обычного DayZ_x64. По имени EXE
            # клиент всё равно определяется однозначно; Diag без аргументов
            # остаётся сервером, поскольку там роль задаёт только -server.
            with contextlib.suppress(psutil.Error):
                process_name = (p.info["name"] or "").lower()
                side = CLIENT if process_name == "dayz_x64.exe" else SERVER
                out.append(Running(pid=p.pid, side=side, exe=(p.info["name"] or "")))
            continue

        name = Path(exe).name.lower()
        is_server = "-server" in (a.lower() for a in args) or name == "dayzserver_x64.exe"
        rec = Running(pid=p.pid, side=SERVER if is_server else CLIENT, exe=exe, started=started, args=args)

        if is_server:
            candidates = set(all_names)
            raw_profiles = _arg(args, "-profiles=")
            if raw_profiles:
                # путь в командной строке относительный — от рабочей папки
                full = Path(raw_profiles) if Path(raw_profiles).is_absolute() else Path(cwd) / raw_profiles
                rec.profiles = str(full)
            with contextlib.suppress(ValueError):
                rec.port = int(_arg(args, "-port=") or 0)

            if profile_names:
                candidates &= profile_names.get(_path_key(raw_profiles, cwd), set())
            if config_names:
                raw_config = _arg(args, "-config=")
                candidates &= config_names.get(_path_key(raw_config, cwd), set())
            if identities:
                candidates = {
                    preset_name
                    for preset_name in candidates
                    if identities[preset_name][1] == rec.port
                    and _path_key(identities[preset_name][2]) == _path_key(exe)
                }
            if len(candidates) == 1:
                rec.preset = next(iter(candidates))
        else:
            conn = _arg(args, "-connect=")
            with contextlib.suppress(ValueError):
                rec.port = int(conn.rsplit(":", 1)[-1]) if ":" in conn else 0
        out.append(rec)

    # Клиента опознаём не по пресету с таким портом, а по нашему же серверу на
    # этом порту. Разница существенна: порт 2302 стоит у всех пресетов по
    # умолчанию, и «нашёлся пресет с таким портом» не значит ровно ничего.
    # А вот «клиент подключён туда, где работает опознанный нами сервер» —
    # значит; заодно клиент достаётся тому же пресету, что и сервер.
    by_port = {r.port: r.preset for r in out if r.side == SERVER and r.preset and r.port}
    fallback_used = False
    for r in out:
        if r.side == CLIENT:
            matched = by_port.get(r.port, "")
            if matched:
                r.preset = matched
            elif client_preset and not fallback_used:
                # Обычный клиент может работать без запущенного нами сервера.
                # Пользователь допускает подхват единственного DayZ-клиента.
                r.preset = client_preset
                fallback_used = True
    return out
