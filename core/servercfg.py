"""Работа с serverDZ.cfg: чтение/точечная правка значений, кодировка UTF-8 без BOM.

Файл правится минимально: меняются только значения существующих переменных,
комментарии и неизвестные параметры не трогаются.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from pathlib import Path

# Известные переменные: имя -> (тип, ключ подсказки задаётся в UI через i18n)
KNOWN_VARS: dict[str, str] = {
    "hostname": "str",
    "password": "str",
    "passwordAdmin": "str",
    "maxPlayers": "int",
    "verifySignatures": "int",
    "forceSameBuild": "int",
    "disableVoN": "int",
    "vonCodecQuality": "int",
    "disable3rdPerson": "int",
    "disableCrosshair": "int",
    "serverTime": "str",
    "serverTimeAcceleration": "int",
    "serverNightTimeAcceleration": "int",
    "serverTimePersistent": "int",
    "guaranteedUpdates": "int",
    "loginQueueConcurrentPlayers": "int",
    "loginQueueMaxPlayers": "int",
    "instanceId": "int",
    "storageAutoFix": "int",
    "steamQueryPort": "int",
    "respawnTime": "int",
    "motdInterval": "int",
    "timeStampFormat": "str",
    "logAverageFps": "int",
    "logMemory": "int",
    "logPlayers": "int",
    "logFile": "str",
    "adminLogPlayerHitsOnly": "int",
    "adminLogPlacement": "int",
    "adminLogBuildActions": "int",
    "adminLogPlayerList": "int",
    "lightingConfig": "int",
    "disablePersonalLight": "int",
    "disableBaseDamage": "int",
    "disableContainerDamage": "int",
    "disableRespawnDialog": "int",
    "enableDebugMonitor": "int",
    "allowFilePatching": "int",
    "simulatedPlayersBatch": "int",
    "multithreadedReplication": "int",
    "speedhackDetection": "int",
    "networkRangeClose": "int",
    "networkRangeNear": "int",
    "networkRangeFar": "int",
    "networkRangeDistantEffect": "int",
    "defaultVisibility": "int",
    "defaultObjectViewDistance": "int",
    # по официальной вики (community.bistudio.com/wiki/DayZ:Server_Configuration)
    "description": "str",
    "enableWhitelist": "int",
    "disableBanlist": "str",
    "disablePrioritylist": "str",
    "disableMultiAccountMitigation": "str",
    "pingWarning": "int",
    "pingCritical": "int",
    "MaxPing": "int",
    "serverFpsWarning": "int",
    "shotValidation": "int",
    "clientPort": "int",
    "template": "str",
    "networkObjectBatchLogSlow": "int",
    "networkObjectBatchEnforceBandwidthLimits": "int",
    "networkObjectBatchUseEstimatedBandwidth": "int",
    "networkObjectBatchUseDynamicMaximumBandwidth": "int",
    "networkObjectBatchBandwidthLimit": "str",
    "networkObjectBatchCompute": "int",
    "networkObjectBatchSendCreate": "int",
    "networkObjectBatchSendDelete": "int",
}

_VAR_RE = re.compile(r'^(\s*)([A-Za-z_]\w*)\s*=\s*(".*?"|[^;/]*?)\s*;', re.MULTILINE)
_MISSION_TEMPLATE_RE = re.compile(
    r'^(\s*template\s*=\s*)(".*?"|[^;/]*?)(\s*;)',
    re.MULTILINE | re.IGNORECASE,
)


@dataclass
class CfgVar:
    name: str
    value: str  # без кавычек
    quoted: bool
    span: tuple[int, int]  # позиция значения в тексте
    known: bool


def read_text_any(path: Path) -> tuple[str, str]:
    """Читает cfg, возвращает (текст, исходная кодировка)."""
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8) :].decode("utf-8", errors="replace"), "utf-8-bom"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace"), "cp1251"


def write_utf8_no_bom(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def needs_reencode(path: Path) -> bool:
    try:
        _, enc = read_text_any(path)
        return enc != "utf-8"
    except OSError:
        return False


class ServerCfg:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text, self.encoding = read_text_any(path)

    def variables(self) -> list[CfgVar]:
        out = []
        for m in _VAR_RE.finditer(self.text):
            name, raw = m.group(2), m.group(3).strip()
            quoted = raw.startswith('"') and raw.endswith('"')
            value = raw[1:-1] if quoted else raw
            out.append(
                CfgVar(
                    name=name,
                    value=value,
                    quoted=quoted,
                    span=(m.start(3), m.end(3)),
                    known=name in KNOWN_VARS,
                )
            )
        return out

    def set_values(self, new_values: dict[str, str]) -> None:
        """Меняет значения переменных точечно, справа налево (чтобы не сбить позиции)."""
        cfg_vars = [v for v in self.variables() if v.name in new_values]
        for v in sorted(cfg_vars, key=lambda x: x.span[0], reverse=True):
            nv = new_values[v.name]
            raw = f'"{nv}"' if v.quoted else nv
            self.text = self.text[: v.span[0]] + raw + self.text[v.span[1] :]

    def set_mission_template(self, mission: str) -> bool:
        """Синхронизирует первую миссию CFG, не меняя остальной текст."""
        mission = mission.strip()
        if not mission:
            return False
        match = _MISSION_TEMPLATE_RE.search(self.text)
        if match:
            raw = match.group(2).strip()
            current = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
            if current == mission:
                return False
            self.text = self.text[: match.start(2)] + f'"{mission}"' + self.text[match.end(2) :]
            return True

        newline = "\r\n" if "\r\n" in self.text else "\n"
        if not self.text:
            separator = ""
        elif self.text.endswith(("\r\n", "\n")):
            separator = newline
        else:
            separator = newline * 2
        self.text += separator + newline.join(
            (
                "class Missions",
                "{",
                "    class DayZ",
                "    {",
                f'        template = "{mission}";',
                "    };",
                "};",
                "",
            )
        )
        return True

    def save(self) -> None:
        """Сохраняет всегда в UTF-8 без BOM (перекодирует при необходимости)."""
        write_utf8_no_bom(self.path, self.text)
        self.encoding = "utf-8"


def sync_mission_for_launch(path: Path, mission: str) -> tuple[bool, bool]:
    """Синхронизирует mission template и кодировку перед запуском сервера."""
    cfg = ServerCfg(path)
    reencoded = cfg.encoding != "utf-8"
    changed = cfg.set_mission_template(mission)
    if changed or reencoded:
        cfg.save()
    return changed, reencoded
