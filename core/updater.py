"""Проверка и загрузка обновлений с GitHub Releases.

Версия берётся из тега релиза, описание изменений — из его текста, файл — из
приложенных ассетов. Ничего дополнительно публиковать не нужно: контрольную
сумму GitHub считает сам и отдаёт в поле digest, по нему и сверяем скачанное.

Устанавливать обновление на ходу нельзя: Windows не даёт переписать файлы
работающей программы. Поэтому скачанное складывается рядом с настройками и
ждёт перезапуска — см. pending() и core/updater_apply.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .settings import APP_DIR
from .version import VERSION, is_newer

REPO = "byRaiZo/RaiZo_Tools"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_UA = {"User-Agent": f"RaiZoTools/{VERSION} (github.com/{REPO})", "Accept": "application/vnd.github+json"}

UPDATE_DIR = APP_DIR / "update"
_PENDING = UPDATE_DIR / "pending.json"
_CHUNK = 256 * 1024


def _asset_path(name: str) -> Path:
    if not name or name != Path(name).name or ":" in name:
        raise ValueError("недопустимое имя release-ассета")
    return UPDATE_DIR / name


@dataclass
class Release:
    """Релиз с GitHub — ровно то, что нужно показать и скачать."""

    version: str  # 0.2.0, без «v»
    name: str  # заголовок релиза
    changelog: str  # его текст
    page: str  # страница релиза на GitHub
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    digest: str = ""  # «sha256:...», считает GitHub
    checksum_url: str = ""

    @property
    def downloadable(self) -> bool:
        return bool(self.asset_url and (self.digest or self.checksum_url))


def _pick_assets(assets: list[dict], version: str) -> tuple[dict | None, dict | None]:
    """Выбирает только архив и checksum с точным версионным именем."""
    archive_name = f"RaiZo_Tools-v{version}-win64.zip"
    checksum_name = archive_name + ".sha256"
    by_name = {str(asset.get("name") or "").casefold(): asset for asset in assets if isinstance(asset, dict)}
    return by_name.get(archive_name.casefold()), by_name.get(checksum_name.casefold())


def _digest_sha256(value: str) -> str:
    algorithm, separator, digest = value.strip().partition(":")
    if separator and algorithm.casefold() != "sha256":
        return ""
    candidate = digest if separator else algorithm
    return candidate.casefold() if re.fullmatch(r"[0-9a-fA-F]{64}", candidate) else ""


def _checksum_sha256(text: str, asset_name: str) -> str:
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?(.+))?", first_line)
    if not match:
        return ""
    listed_name = (match.group(2) or "").strip()
    if listed_name and listed_name.casefold() != asset_name.casefold():
        return ""
    return match.group(1).casefold()


def _expected_sha256(rel: Release, timeout: int = 15) -> str:
    digest = _digest_sha256(rel.digest)
    if digest:
        return digest
    if not rel.checksum_url:
        return ""
    req = urllib.request.Request(rel.checksum_url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read(4097)
    if len(text) > 4096:
        return ""
    return _checksum_sha256(text.decode("ascii", errors="strict"), rel.asset_name)


def fetch_latest(timeout: int = 15) -> Release | None:
    """Последний релиз либо None, если релизов нет, сеть недоступна или
    репозиторий закрыт. Отсутствие ответа — не ошибка: проверка обновлений не
    должна мешать работать.
    """
    try:
        req = urllib.request.Request(_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    rel = Release(
        version=tag.lstrip("vV"),
        name=str(data.get("name") or tag),
        changelog=str(data.get("body") or ""),
        page=str(data.get("html_url") or ""),
    )
    asset, checksum = _pick_assets(data.get("assets") or [], rel.version)
    if asset:
        rel.asset_name = str(asset.get("name") or "")
        rel.asset_url = str(asset.get("browser_download_url") or "")
        rel.asset_size = int(asset.get("size") or 0)
        rel.digest = str(asset.get("digest") or "")
        if checksum:
            rel.checksum_url = str(checksum.get("browser_download_url") or "")
    return rel


def is_update(rel: Release | None) -> bool:
    """Именно новее, а не «отличается»: сборка из исходников идёт впереди
    релиза, и предлагать откатиться на неё назад незачем."""
    return rel is not None and is_newer(rel.version)


# ------------------------------------------------------------ скачанное ждёт


def pending() -> Release | None:
    """Обновление, уже скачанное и ждущее перезапуска."""
    try:
        data = json.loads(_PENDING.read_text(encoding="utf-8"))
        rel = Release(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    # файл могли удалить руками — тогда ждать нечего
    try:
        archive = _asset_path(rel.asset_name)
    except ValueError:
        return None
    if not archive.is_file():
        return None
    return rel


def set_pending(rel: Release) -> None:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    _PENDING.write_text(json.dumps(asdict(rel), ensure_ascii=False, indent=2), encoding="utf-8")


def clear_pending() -> None:
    """Убирает и отметку, и сам архив: держать 150 МБ после установки незачем."""
    rel = pending()
    try:
        _PENDING.unlink(missing_ok=True)
        if rel:
            _asset_path(rel.asset_name).unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- воркеры


class CheckWorker(QThread):
    """Проверка версии в фоне: сеть при старте не должна задерживать окно."""

    done = Signal(object)  # Release либо None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        self.done.emit(fetch_latest())


class DownloadWorker(QThread):
    """Загрузка архива обновления со сверкой контрольной суммы."""

    progress = Signal(int, int)  # получено, всего
    done = Signal(str)  # путь к файлу
    failed = Signal(str)

    def __init__(self, rel: Release, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rel = rel
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        rel = self.rel
        try:
            expected = _expected_sha256(rel)
        except (UnicodeDecodeError, urllib.error.URLError, OSError, ValueError) as exc:
            self.failed.emit(f"не удалось получить контрольную сумму: {exc}")
            return
        if not expected:
            self.failed.emit("обновление заблокировано: отсутствует корректная SHA-256")
            return
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        # качаем во временное имя: оборванная загрузка не должна выглядеть
        # как готовый к установке файл
        try:
            dst = _asset_path(rel.asset_name)
        except ValueError as exc:
            self.failed.emit(str(exc))
            return
        tmp = dst.with_name(dst.name + ".part")
        sha = hashlib.sha256()
        got = 0
        try:
            req = urllib.request.Request(rel.asset_url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or rel.asset_size or 0)
                while True:
                    if self._cancel:
                        raise InterruptedError
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
        except InterruptedError:
            tmp.unlink(missing_ok=True)
            return
        except (urllib.error.URLError, OSError) as e:
            tmp.unlink(missing_ok=True)
            self.failed.emit(str(e))
            return

        if sha.hexdigest() != expected:
            # скачали не то: битая загрузка или подмена по пути
            tmp.unlink(missing_ok=True)
            self.failed.emit("контрольная сумма не совпала")
            return
        try:
            dst.unlink(missing_ok=True)
            tmp.rename(dst)
        except OSError as e:
            self.failed.emit(str(e))
            return
        set_pending(rel)
        self.done.emit(str(dst))
