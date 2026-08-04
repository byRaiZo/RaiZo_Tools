"""Фоновая загрузка миссии: zip ветки с GitHub -> распаковка подпапки -> установка."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from . import missions
from .missions import CatalogEntry

_CHUNK = 256 * 1024


def safe_member(rel: str, root: Path) -> Path | None:
    """Путь распаковки для элемента архива либо None, если он выходит за корень.

    Имя внутри zip задаёт тот, кто собрал архив, а мы тянем архивы из чужих
    репозиториев — авторов карт. Имя вида «../../evil.txt» без проверки уводит
    запись куда угодно в пределах прав пользователя (Zip Slip): достаточно
    попасть в папку автозагрузки. Угнанного аккаунта одного автора хватило бы
    на всех, кто скачает эту карту.

    Сравниваем нормализованные пути, а не resolve(): resolve ходит на диск и
    разворачивает симлинки, а нам нужен ответ про имя, а не про то, что уже
    лежит на диске.
    """
    if not rel or rel.startswith(("/", "\\")) or ":" in rel:
        return None
    # Составляющая из одних точек: «..» очевиден, но и «....» опасен — сам по
    # себе он за корень не уводит, зато Windows режет точки в конце имён, и что
    # получится, решает уже она. Проверка не должна зависеть от таких тонкостей.
    # (одиночная «.» безобидна — это «текущая папка», её и пропускаем)
    if any(len(p) > 1 and set(p) == {"."} for p in rel.replace("\\", "/").split("/")):
        return None
    dest = Path(os.path.normpath(str(root / rel)))
    try:
        dest.relative_to(root)
    except ValueError:
        return None
    return dest


class MissionCopyWorker(QThread):
    """Локальное создание миссии из шаблона actual.<world> (без сети)."""

    done = Signal(bool, str)  # ok, целевой путь или ошибка

    def __init__(
        self, src: Path, dst: Path, replace: bool = False, keep_storage: bool = True, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.src = src
        self.dst = dst
        self.replace = replace
        self.keep_storage = keep_storage

    def run(self) -> None:
        from .i18n import tr
        from .missions import META_NAME

        try:
            storage_backup: list[tuple[Path, Path]] = []
            if self.dst.exists():
                if not self.replace:
                    raise RuntimeError(tr("dl.exists", "Папка уже существует: {p}", p=self.dst))
                if self.keep_storage:
                    import tempfile

                    for st in self.dst.glob("storage_*"):
                        bak = Path(tempfile.mkdtemp(prefix="krsm_storage_")) / st.name
                        shutil.move(str(st), str(bak))
                        storage_backup.append((bak, self.dst / st.name))
                shutil.rmtree(self.dst)
            shutil.copytree(self.src, self.dst)
            # копия — рабочая миссия пресета, метка шаблона ей не принадлежит
            (self.dst / META_NAME).unlink(missing_ok=True)
            for bak, dest in storage_backup:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.move(str(bak), str(dest))
            self.done.emit(True, str(self.dst))
        except Exception as e:  # noqa: BLE001 — всё в UI
            self.done.emit(False, str(e))


class MissionDownloadWorker(QThread):
    """Скачивает и устанавливает миссию из каталога.

    replace=True — обновление существующей папки; keep_storage управляет
    судьбой storage_* (персистентность) при обновлении.
    """

    progress = Signal(int, int, float, bool)  # байт скачано, всего, секунд, total оценочный?
    status = Signal(str)
    done = Signal(bool, str)  # ok, целевой путь или текст ошибки

    def __init__(
        self,
        entry: CatalogEntry,
        target_dir: Path,
        target_name: str,
        replace: bool = False,
        keep_storage: bool = True,
        mods_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.entry = entry
        self.target_dir = target_dir
        self.target_name = target_name
        self.replace = replace
        self.keep_storage = keep_storage
        self.mods_dir = mods_dir  # куда класть моды карты из того же репозитория
        self._cancel = False
        self._done_emitted = False

    @staticmethod
    def _extract_subtree(zf: zipfile.ZipFile, names: list[str], prefix: str, tmp_prefix: str) -> Path:
        extract_tmp = Path(tempfile.mkdtemp(prefix=tmp_prefix))
        skipped = 0
        for n in names:
            if not n.startswith(prefix):
                continue
            rel = n[len(prefix) :]
            if not rel:
                continue
            dest = safe_member(rel, extract_tmp)
            if dest is None:
                # молча пропустить нельзя: битый архив выглядел бы как «карта
                # скачалась, но чего-то не хватает»
                skipped += 1
                print(f"[downloader] пропущен элемент архива вне каталога: {n!r}")
                continue
            if n.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(n) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        if skipped:
            raise RuntimeError(
                f"Архив содержит {skipped} элемент(ов) с путями за пределами "
                f"своей папки — установка прервана. Сообщите автору карты."
            )
        return extract_tmp

    def cancel(self) -> None:
        self._cancel = True

    def _emit_done(self, ok: bool, message: str) -> None:
        if not self._done_emitted:
            self._done_emitted = True
            self.done.emit(ok, message)

    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — всё в UI
            self._emit_done(False, str(e))

    def _run(self) -> None:
        from .i18n import tr

        entry = self.entry
        target = self.target_dir / self.target_name

        self.status.emit(tr("dl.resolving", "Определение версии…"))
        sub_path = missions.resolve_entry_path(entry)
        sha = missions.latest_sha(entry, sub_path)
        # GitHub отдаёт zip потоком без Content-Length; оцениваем объём по размеру репозитория
        estimated = 0
        try:
            info = missions._api_json(f"https://api.github.com/repos/{entry.repo}")
            estimated = int(info.get("size", 0)) * 1024
        except Exception:  # noqa: BLE001 — оценка не обязательна
            pass
        if self._cancel:
            self._emit_done(False, tr("dl.cancelled", "Отменено"))
            return

        url = missions.zip_url(entry)
        self.status.emit(tr("dl.downloading", "Скачивание {repo}…", repo=entry.repo))
        fd, tmp_name = tempfile.mkstemp(suffix=".zip", prefix="krsm_")
        os.close(fd)  # mkstemp держит файл открытым — иначе Windows не даст его удалить
        tmp_zip = Path(tmp_name)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "RaiZoTools (github.com/byRaiZo/RaiZo_Tools)"})
            t0 = time.monotonic()
            got = 0
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_zip, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                is_estimate = total <= 0
                if is_estimate:
                    total = estimated
                while True:
                    if self._cancel:
                        self._emit_done(False, tr("dl.cancelled", "Отменено"))
                        return
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total, time.monotonic() - t0, is_estimate)

            self.status.emit(tr("dl.extracting", "Распаковка…"))
            # свежий большой zip может держать антивирус — пробуем открыть с паузами
            zf = None
            for attempt in range(10):
                try:
                    zf = zipfile.ZipFile(tmp_zip)
                    break
                except (OSError, PermissionError):
                    if attempt == 9:
                        raise
                    self.status.emit(tr("dl.locked", "Файл занят (антивирус?) — повтор {n}/10…", n=attempt + 2))
                    time.sleep(1.5)
            mods_tmp: list[tuple[str, Path]] = []  # (имя @папки, temp-каталог)
            # цикл попыток выше либо открыл архив, либо выбросил исключение —
            # None сюда не доходит, но проверяющему это неоткуда узнать
            assert zf is not None
            with zf:
                names = zf.namelist()
                if not names:
                    raise RuntimeError("Пустой архив")
                root = names[0].split("/", 1)[0]  # <repo>-<ветка>
                prefix = f"{root}/{sub_path}/"
                if not any(n.startswith(prefix) for n in names):
                    raise RuntimeError(tr("dl.no_path", "В архиве нет пути {p}", p=sub_path))
                extract_tmp = self._extract_subtree(zf, names, prefix, "krsm_mission_")

                # моды карты из того же архива (например @KR_BlankMap)
                if self.mods_dir:
                    for spec in getattr(entry, "mods", []):
                        mpath = spec.get("path", "")
                        mprefix = f"{root}/{mpath}/"
                        if not mpath or not any(n.startswith(mprefix) for n in names):
                            continue
                        self.status.emit(tr("dl.mod_extract", "Распаковка мода {m}…", m=Path(mpath).name))
                        mods_tmp.append((Path(mpath).name, self._extract_subtree(zf, names, mprefix, "krsm_mod_")))

            self.status.emit(tr("dl.installing", "Установка…"))
            self.target_dir.mkdir(parents=True, exist_ok=True)
            if target.exists() and not self.replace:
                raise RuntimeError(tr("dl.exists", "Папка уже существует: {p}", p=target))
            token = uuid.uuid4().hex
            staging = self.target_dir / f".{target.name}.raizo-staging-{token}"
            backup = self.target_dir / f".{target.name}.raizo-backup-{token}"
            shutil.copytree(extract_tmp, staging)
            had_target = target.exists()
            try:
                if had_target:
                    target.rename(backup)
                staging.rename(target)
                if had_target:
                    # Persistence сохраняется всегда, независимо от содержимого
                    # новой версии миссии.
                    for old_storage in backup.glob("storage_*"):
                        destination = target / old_storage.name
                        if destination.exists():
                            shutil.rmtree(destination)
                        old_storage.rename(destination)
                missions.write_meta(target, entry, sha, sub_path)
            except Exception:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    backup.rename(target)
                raise
            else:
                shutil.rmtree(backup, ignore_errors=True)
            finally:
                shutil.rmtree(staging, ignore_errors=True)

            # установка модов карты в пользовательское хранилище загрузок
            # mods_tmp наполняется только внутри ветки «if self.mods_dir»,
            # так что пустой список здесь означает, что папка не задана
            mods_dir = self.mods_dir
            for mod_name, tmp_dir in mods_tmp:
                assert mods_dir is not None
                self.status.emit(tr("dl.mod_install", "Установка мода {m}…", m=mod_name))
                mods_dir.mkdir(parents=True, exist_ok=True)
                mod_target = mods_dir / mod_name
                if mod_target.exists():
                    shutil.rmtree(mod_target)
                shutil.move(str(tmp_dir), str(mod_target))
                import json

                (mod_target / ".krsm_mod.json").write_text(
                    json.dumps(
                        {
                            "repo": entry.repo,
                            "branch": entry.branch,
                            "sha": sha or "",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            self._emit_done(True, str(target))
        finally:
            try:
                tmp_zip.unlink(missing_ok=True)
            except OSError:
                pass  # неудачная уборка temp-файла не должна выглядеть ошибкой загрузки
