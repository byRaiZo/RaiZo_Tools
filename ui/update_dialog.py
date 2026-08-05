"""Окно обновления: что нового и что с этим делать.

При первом обнаружении новой версии открывается автоматически. После этого
остаётся доступным из пункта в панели навигации, но само повторно не всплывает.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QTextBrowser
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    BodyLabel,
    StrongBodyLabel,
    CaptionLabel,
    ProgressBar,
    IndeterminateProgressRing,
    FluentIcon as FIF,
    isDarkTheme,
)

from core.i18n import tr
from core.updater import Release
from core.version import VERSION
from ui.theme import ThemedDialog


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.0f} МБ" if n else ""


class UpdateDialog(ThemedDialog):
    """Описание релиза, кнопка загрузки и её ход.

    Окно не закрывается по клику на «Скачать»: 68 мегабайт идут не мгновенно, и
    исчезнувшее окно выглядит так, будто нажатие ничего не сделало. Ход виден
    здесь же — крутящийся индикатор и проценты прямо на кнопке. Закрыть можно
    в любой момент: загрузка продолжится, о готовности скажет пункт в навигации.
    """

    download_requested = Signal()
    restart_requested = Signal()

    def __init__(
        self, rel: Release, downloading: bool = False, ready: bool = False, mandatory: bool = False, parent=None
    ):
        super().__init__(parent)
        self.rel = rel
        self.action = ""  # что выбрал пользователь: download | restart
        self.mandatory = mandatory
        self.setWindowTitle(tr("upd.title", "Обновление"))
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(tr("upd.head", "Версия {new}", new=rel.version)))
        layout.addWidget(CaptionLabel(tr("upd.current", "У вас установлена {cur}", cur=VERSION)))
        if mandatory:
            why = BodyLabel(
                tr(
                    "upd.must_body",
                    "Программа ещё не настроена, поэтому обновиться нужно сейчас. "
                    "Настройки, сделанные на старой версии, новая может не понять, "
                    "а первый запуск — то место, где ошибки старых версий заметнее "
                    "всего.",
                )
            )
            why.setWordWrap(True)
            layout.addWidget(why)

        self.notes = QTextBrowser(self)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(rel.changelog or tr("upd.no_notes", "Автор не оставил описания изменений."))
        # тёмный текст на светлой теме и наоборот — QTextBrowser своего фона
        # от qfluentwidgets не наследует
        bg, fg = ("#2b2b2b", "#d4d4d4") if isDarkTheme() else ("#ffffff", "#202020")
        self.notes.setStyleSheet(
            f"QTextBrowser{{background:{bg};color:{fg};border:1px solid #444;border-radius:6px;padding:6px;}}"
        )
        layout.addWidget(self.notes, 1)

        self.bar = ProgressBar(self)
        self.bar.setVisible(downloading)
        layout.addWidget(self.bar)
        self.status = CaptionLabel("")
        layout.addWidget(self.status)

        btns = QHBoxLayout()
        b_page = PushButton(FIF.LINK, tr("upd.page", "Страница релиза"))
        b_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.page)))
        b_page.setEnabled(bool(rel.page))
        # На первом запуске отложить нечего: либо обновляемся, либо выходим.
        b_later = PushButton(tr("upd.quit", "Выйти") if mandatory else tr("upd.later", "Позже"))
        b_later.clicked.connect(self.reject)
        btns.addWidget(b_page)
        btns.addStretch(1)
        btns.addWidget(b_later)

        # крутится, пока идёт загрузка: проценты говорят «сколько осталось»,
        # а вращение — «процесс жив», даже если счётчик замер на плохой сети
        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(18, 18)
        self.spinner.setStrokeWidth(3)
        self.spinner.setVisible(False)
        btns.addWidget(self.spinner)

        if ready:
            self.b_main = PrimaryPushButton(FIF.SYNC, tr("upd.restart", "Перезапустить и установить"))
            self.b_main.clicked.connect(lambda: self._choose("restart"))
        else:
            size = _size(rel.asset_size)
            text = tr("upd.download_size", "Скачать ({s})", s=size) if size else tr("upd.download", "Скачать")
            self.b_main = PrimaryPushButton(FIF.DOWNLOAD, text)
            self.b_main.clicked.connect(lambda: self._choose("download"))
            # нечего качать — релиз без приложенного архива
            if not rel.downloadable:
                self.b_main.setEnabled(False)
                self.status.setText(
                    tr("upd.no_asset", "К релизу не приложен файл сборки — скачайте со страницы релиза.")
                )
        btns.addWidget(self.b_main)
        layout.addLayout(btns)

        if downloading:
            self.set_downloading()

    def _choose(self, what: str) -> None:
        """Загрузка окно не закрывает — оно и есть индикатор. Перезапуск
        закрывает: дальше приложение всё равно уходит."""
        self.action = what
        if what == "restart":
            self.restart_requested.emit()
            self.accept()
            return
        self.set_downloading()
        self.download_requested.emit()

    def set_downloading(self) -> None:
        self.spinner.setVisible(True)
        self.bar.setVisible(True)
        self.b_main.setEnabled(False)
        self.b_main.setText(tr("upd.downloading", "Скачивание…"))
        self.status.setText("")

    def set_progress(self, got: int, total: int) -> None:
        self.spinner.setVisible(True)
        self.bar.setVisible(True)
        self.b_main.setEnabled(False)
        if total:
            pct = int(got * 100 / total)
            self.bar.setValue(pct)
            self.b_main.setText(tr("upd.downloading_pct", "Скачивание… {p}%", p=pct))
        self.status.setText(tr("upd.progress", "Скачано {a} из {b}", a=_size(got), b=_size(total)))

    def set_ready(self) -> None:
        """Загрузка кончилась — кнопка превращается в «перезапустить»."""
        self.spinner.setVisible(False)
        self.bar.setValue(100)
        self.status.setText("")
        self.b_main.setEnabled(True)
        self.b_main.setIcon(FIF.SYNC)
        self.b_main.setText(tr("upd.restart", "Перезапустить и установить"))
        try:
            self.b_main.clicked.disconnect()
        except RuntimeError:
            pass
        self.b_main.clicked.connect(lambda: self._choose("restart"))

    def set_failed(self, msg: str) -> None:
        self.spinner.setVisible(False)
        self.bar.setVisible(False)
        self.b_main.setEnabled(True)
        self.b_main.setText(tr("upd.retry", "Повторить"))
        self.status.setText(tr("upd.failed_body", "Не удалось скачать: {m}", m=msg))


class InstallDialog(ThemedDialog):
    """Распаковка обновления перед перезапуском.

    Закрыть нельзя: дальше идёт замена файлов программы, и бросить это на
    середине — получить установку из половины старой версии и половины новой.
    Распаковка укладывается в десяток секунд, ждать недолго.
    """

    def __init__(self, rel: Release, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("upd.install_title", "Установка обновления"))
        self.resize(420, 160)
        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(tr("upd.install_head", "Подготовка версии {v}", v=rel.version)))
        note = BodyLabel(tr("upd.install_body", "Программа закроется и запустится заново сама."))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.bar = ProgressBar(self)
        layout.addWidget(self.bar)
        self.status = CaptionLabel("")
        layout.addWidget(self.status)

    def set_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setValue(int(done * 100 / total))
        self.status.setText(tr("upd.install_progress", "Распаковано {a} из {b} файлов", a=done, b=total))

    def set_failed(self, msg: str) -> None:
        self.status.setText(tr("upd.install_error", "Не удалось: {m}", m=msg))

    def reject(self) -> None:
        """Escape и крестик не работают, пока идёт распаковка."""


class RestartDialog(ThemedDialog):
    """Обновление скачано — предложение перезапуститься."""

    def __init__(self, rel: Release, parent=None):
        super().__init__(parent)
        self.restart_now = False
        self.setWindowTitle(tr("upd.ready_title", "Обновление готово"))
        self.resize(420, 170)
        layout = QVBoxLayout(self)
        layout.addWidget(StrongBodyLabel(tr("upd.ready_head", "Версия {v} скачана", v=rel.version)))
        note = BodyLabel(
            tr(
                "upd.ready_body",
                "Файлы приложения будут заменены при перезапуске. Запущенные сервер и клиент это не затронет.",
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_later = PushButton(tr("upd.later", "Позже"))
        b_later.clicked.connect(self.reject)
        b_now = PrimaryPushButton(FIF.SYNC, tr("upd.restart_now", "Перезапустить сейчас"))
        b_now.clicked.connect(self._now)
        btns.addWidget(b_later)
        btns.addWidget(b_now)
        layout.addLayout(btns)

    def _now(self) -> None:
        self.restart_now = True
        self.accept()
