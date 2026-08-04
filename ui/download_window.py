"""Модальное окно загрузки миссии: прогресс, объём, таймер, ссылка на источник."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    BodyLabel,
    CaptionLabel,
)

from core.downloader import MissionDownloadWorker
from core.i18n import tr
from core.missions import CatalogEntry
from ui.theme import ThemedDialog, link_html


def _fmt_size(n: int) -> str:
    mb = n / (1024 * 1024)
    return f"{mb:.1f} МБ" if mb < 1024 else f"{mb / 1024:.2f} ГБ"


def _fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


class DownloadWindow(ThemedDialog):
    """Модальное (блокирует приложение) и поверх всех окон; загрузка идёт в потоке."""

    finished_ok = Signal(str)  # путь установленной миссии

    def __init__(
        self,
        entry: CatalogEntry,
        target_dir: Path,
        target_name: str,
        replace: bool = False,
        keep_storage: bool = True,
        mods_dir: Path | None = None,
        parent=None,
    ):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(tr("dl.title", "Загрузка миссии: {n}", n=target_name))
        self.resize(480, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(StrongBodyLabel(f"{entry.title}  →  {target_name}"))

        link = BodyLabel(
            tr("dl.source", "Источник: ") + link_html(f"https://github.com/{entry.repo}", f"github.com/{entry.repo}")
        )
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        self.status = BodyLabel(tr("dl.starting", "Подготовка…"))
        layout.addWidget(self.status)

        self.bar = ProgressBar()
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        row = QHBoxLayout()
        self.stats = CaptionLabel("")
        self.btn_cancel = PushButton(tr("common.cancel", "Отмена"))
        self.btn_cancel.clicked.connect(self._cancel)
        row.addWidget(self.stats, 1)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        self.worker = MissionDownloadWorker(
            entry, target_dir, target_name, replace=replace, keep_storage=keep_storage, mods_dir=mods_dir
        )
        self.worker.status.connect(self.status.setText)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _progress(self, got: int, total: int, elapsed: float, is_estimate: bool) -> None:
        self._last = (got, elapsed)
        speed = got / elapsed / (1024 * 1024) if elapsed > 0 else 0
        if total > 0:
            # оценочный объём не даём доползти до конца — 100% только по факту
            cap = 99 if is_estimate else 100
            self.bar.setValue(min(cap, int(got * 100 / total)))
            mark = "~" if is_estimate else ""
            self.stats.setText(
                tr(
                    "dl.stats_total",
                    "{got} из {mark}{total}   •   {spd:.1f} МБ/с   •   {t}",
                    got=_fmt_size(got),
                    total=_fmt_size(total),
                    mark=mark,
                    spd=speed,
                    t=_fmt_time(elapsed),
                )
            )
        else:
            # объёма нет даже оценочно: полоска ползёт асимптотически, не доходя до конца
            self.bar.setValue(min(99, int(got / (got + 60 * 1024 * 1024) * 100)))
            self.stats.setText(
                tr(
                    "dl.stats",
                    "Скачано {got}   •   {spd:.1f} МБ/с   •   {t}",
                    got=_fmt_size(got),
                    spd=speed,
                    t=_fmt_time(elapsed),
                )
            )

    def _done(self, ok: bool, result: str) -> None:
        if ok:
            self.bar.setValue(100)
            self.status.setText(tr("dl.done", "Готово: {p}", p=result))
            if getattr(self, "_last", None):
                got, elapsed = self._last
                self.stats.setText(
                    tr("dl.stats_final", "Скачано {got} за {t}", got=_fmt_size(got), t=_fmt_time(elapsed))
                )
            self.finished_ok.emit(result)
        else:
            self.bar.error()
            self.status.setText(result)
        self.btn_cancel.setText(tr("dl.close", "Закрыть"))
        self.btn_cancel.clicked.disconnect()
        self.btn_cancel.clicked.connect(self.close)

    def _cancel(self) -> None:
        if self.worker.isRunning():
            self.worker.cancel()
            self.status.setText(tr("dl.cancelling", "Отмена…"))
        else:
            self.close()

    def closeEvent(self, event) -> None:  # имя метода задаёт Qt
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()
