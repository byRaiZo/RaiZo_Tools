"""Страница общих настроек (Fluent)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QFileDialog,
    QScrollArea,
)
from PySide6.QtCore import QUrl, QRegularExpression
from PySide6.QtGui import QDesktopServices, QRegularExpressionValidator
from qfluentwidgets import (
    LineEdit,
    PasswordLineEdit,
    PlainTextEdit,
    ComboBox,
    CheckBox,
    PushButton,
    PrimaryPushButton,
    ToolButton,
    BodyLabel,
    CaptionLabel,
    StrongBodyLabel,
    SimpleCardWidget,
    TransparentToolButton,
    TeachingTip,
    TeachingTipTailPosition,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
    setTheme,
    Theme,
)

from pathlib import Path

from core import autodetect, filepatch, steam_urls
from core.i18n import tr, AVAILABLE
from core.settings import (
    Settings,
    check_path,
    PATH_MISSING,
    PATH_NOT_INSTALLED,
)
from ui.theme import BRAND_WARNING
from ui.pboproject_dialog import PboProjectDialog
from ui.steamid_list import SteamIdList

_VPP_PASS_MAXLEN = 32

# Компоненты не из Steam: ключ настроек -> (страница загрузки, название).
# Ставятся вручную, так что можем только открыть страницу в браузере.
EXTERNAL_DOWNLOADS: dict[str, tuple[str, str]] = {}


class PathRow(QVBoxLayout):
    """Поле пути + обзор. Для устанавливаемых компонентов (settings_key задан)
    добавляется кнопка «взять недостающее» — видна, только пока путь не заполнен,
    и строка состояния под полем: пока Steam качает компонент, здесь виден
    прогресс, а по завершении путь подставляется сам."""

    def __init__(self, value: str, parent: QWidget, settings_key: str = ""):
        super().__init__()
        self.setSpacing(2)
        self.setContentsMargins(0, 0, 0, 0)
        self.settings_key = settings_key

        row = QHBoxLayout()
        self.edit = LineEdit()
        self.edit.setText(value)
        btn = ToolButton(FIF.FOLDER)

        def browse():
            p = QFileDialog.getExistingDirectory(parent, "", self.edit.text())
            if p:
                self.edit.setText(p)

        btn.clicked.connect(browse)
        row.addWidget(self.edit, 1)
        row.addWidget(btn)

        self.install_btn = make_install_button(parent, settings_key)
        if self.install_btn is not None:
            row.addWidget(self.install_btn)
        self.addLayout(row)

        self.status = CaptionLabel("")
        self.status.setWordWrap(True)
        self.status.hide()
        self.addWidget(self.status)

        self._dl_text = ""  # «Скачивание началось» от наблюдателя Steam
        self._problem = ""  # результат check_path
        self.edit.textChanged.connect(lambda _t: self.refresh_validity())
        self.refresh_validity()

    def refresh_validity(self) -> None:
        """Подсвечивает путь, если папки нет или программа из неё удалена.

        Сам путь не стираем: диск может быть временно недоступен, а терять
        из-за этого настройку нельзя.
        """
        self._problem = check_path(self.settings_key, self.edit.text().strip())
        self.edit.setError(bool(self._problem))
        if self.install_btn is not None:
            # кнопка установки нужна, пока компонента фактически нет
            self.install_btn.setVisible(not self.edit.text().strip() or self._problem == PATH_NOT_INSTALLED)
        self._render_status()

    def _render_status(self) -> None:
        if self._dl_text:
            text = self._dl_text  # идущая загрузка важнее старой ошибки
        elif self._problem == PATH_MISSING:
            text = tr("settings.path_missing", "Папки по этому пути нет.")
        elif self._problem == PATH_NOT_INSTALLED:
            # обычно живёт доли секунды: наблюдатель Steam в главном окне
            # увидит это и очистит путь сам. Видно, если приложение запущено
            # без главного окна (мастер) или программу удалили только что.
            text = tr("settings.path_not_installed", "Программы по этому пути нет — осталась только папка.")
        else:
            text = ""
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_status(self, text: str) -> None:
        """Статус загрузки Steam — от наблюдателя в главном окне."""
        self._dl_text = text
        self._render_status()

    def text(self) -> str:
        return self.edit.text().strip()


def install_via_steam(parent, appid: str, title: str) -> None:
    """Диалог установки в Steam — только после явного подтверждения:
    steam://install сразу начинает качать, отменять придётся уже в Steam.

    Отдельно проговариваем, что путь подставится сам: иначе непонятно, зачем
    приложение отправило в Steam и что делать после того, как тот докачает.
    """
    from qfluentwidgets import MessageBox

    box = MessageBox(
        tr("steam.install_title", "Установка через Steam"),
        tr(
            "steam.install_confirm",
            "Сейчас откроется Steam и начнётся скачивание «{n}» — он спросит, "
            "в какую библиотеку качать.\n\n"
            "Можно спокойно продолжать работу: приложение само отследит загрузку, "
            "подставит и сохранит путь, когда она завершится.\n\n"
            "Продолжить?",
            n=title,
        ),
        parent.window() if parent else None,
    )
    box.yesButton.setText(tr("common.yes", "Да"))
    box.cancelButton.setText(tr("common.no", "Нет"))
    if box.exec():
        QDesktopServices.openUrl(QUrl(steam_urls.install(appid)))


def make_install_button(parent, settings_key: str):
    """Кнопка «получить недостающее» для поля пути; None — компонент ставится
    вручную и подсказать нечем.

    Steam-компоненты ставятся прямо из приложения (с подтверждением — начнётся
    скачивание), сторонние — открытием страницы загрузки в браузере.
    """
    app = steam_urls.SETTINGS_APPS.get(settings_key)
    if app:
        appid, title = app
        btn = ToolButton(FIF.DOWNLOAD)
        btn.setToolTip(tr("settings.install_via_steam", "Установить «{n}» через Steam", n=title))
        btn.clicked.connect(lambda _=False, a=appid, t=title: install_via_steam(parent, a, t))
        return btn

    ext = EXTERNAL_DOWNLOADS.get(settings_key)
    if ext:
        url, title = ext
        btn = ToolButton(FIF.LINK)
        btn.setToolTip(tr("settings.open_download_page", "Открыть страницу загрузки «{n}»", n=title))
        btn.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        return btn
    return None


class SettingsPage(QScrollArea):
    def __init__(self, settings: Settings, on_saved=None):
        super().__init__()
        self.settings = settings
        self.on_saved = on_saved
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;} QWidget#settingsInner{background:transparent;}")

        inner = QWidget()
        inner.setObjectName("settingsInner")
        self.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        def section(title: str) -> QFormLayout:
            """Заголовок + обведённая рамкой карточка с полями секции."""
            layout.addWidget(StrongBodyLabel(title))
            card = SimpleCardWidget()
            inner_box = QVBoxLayout(card)
            inner_box.setContentsMargins(16, 12, 16, 12)
            f = QFormLayout()
            f.setSpacing(8)
            inner_box.addLayout(f)
            layout.addWidget(card)
            layout.addSpacing(6)
            return f

        # ------------------------------------------------------------ Общее
        form_general = section(tr("settings.section_general", "Общее"))
        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        codes = list(AVAILABLE)
        self.lang.setCurrentIndex(codes.index(settings.language) if settings.language in codes else 0)
        form_general.addRow(BodyLabel(tr("settings.language", "Язык (нужен перезапуск)")), self.lang)

        self.project_prefix = LineEdit()
        self.project_prefix.setText(settings.project_prefix)
        self.project_prefix.setPlaceholderText(tr("settings.prefix_ph", "Например: KR"))
        self.project_prefix.setToolTip(tr("settings.prefix_tip", "Подставляется в hostname создаваемых серверов."))
        form_general.addRow(BodyLabel(tr("settings.prefix_label", "Префикс проекта")), self.project_prefix)

        self.theme = ComboBox()
        self.theme.addItem(tr("settings.theme_auto", "Как в системе"), userData="auto")
        self.theme.addItem(tr("settings.theme_light", "Светлая"), userData="light")
        self.theme.addItem(tr("settings.theme_dark", "Тёмная"), userData="dark")
        theme_codes = ["auto", "light", "dark"]
        self.theme.setCurrentIndex(theme_codes.index(settings.theme) if settings.theme in theme_codes else 0)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form_general.addRow(BodyLabel(tr("settings.theme_label", "Тема оформления")), self.theme)

        # Сетевой запрос при старте должен быть отключаемым: у части людей
        # рабочая машина без интернета, и молчаливый поход наружу их нервирует.
        upd_row = QHBoxLayout()
        self.check_updates = CheckBox(tr("settings.check_updates", "Проверять обновления при запуске"))
        self.check_updates.setChecked(settings.check_updates)
        b_check_now = PushButton(FIF.SYNC, tr("settings.check_now", "Проверить сейчас"))
        b_check_now.clicked.connect(self._check_updates_now)
        upd_row.addWidget(self.check_updates, 1)
        upd_row.addWidget(b_check_now)
        form_general.addRow(BodyLabel(tr("settings.updates_label", "Обновления")), upd_row)

        self.quit_on_close = CheckBox(tr("settings.quit_on_close", "Полностью закрывать программу по крестику"))
        self.quit_on_close.setChecked(settings.quit_on_close)
        self.quit_on_close.setToolTip(
            tr(
                "settings.quit_on_close_tip",
                "Если выключено, крестик сворачивает RaiZo Tools в системный трей.",
            )
        )
        form_general.addRow(BodyLabel(tr("settings.close_button", "Кнопка закрытия")), self.quit_on_close)

        # ------------------------------------------------- Клиент и сервер
        self.stop_method = ComboBox()
        self.stop_method.addItem(tr("settings.stop_soft", "Мягко — попросить закрыться"), userData="soft")
        self.stop_method.addItem(tr("settings.stop_hard", "Жёстко — завершить процесс"), userData="hard")
        idx = self.stop_method.findData(settings.stop_method)
        self.stop_method.setCurrentIndex(max(idx, 0))
        self.stop_method.setToolTip(
            tr(
                "settings.stop_method_tip",
                "Мягкий способ даёт серверу завершиться своим порядком и сохранить данные; жёсткий обрывает его сразу.",
            )
        )
        form_general.addRow(
            BodyLabel(tr("settings.stop_method", "Как останавливать сервер и клиент")), self.stop_method
        )

        form_paths = section(tr("settings.section_paths", "Клиент и сервер"))
        self.p_client = PathRow(settings.client_stable, self, "client_stable")
        self.p_client_exp = PathRow(settings.client_exp, self, "client_exp")
        self.p_server = PathRow(settings.server_stable, self, "server_stable")
        self.p_server_exp = PathRow(settings.server_exp, self, "server_exp")
        self.p_tools = PathRow(settings.dayz_tools, self, "dayz_tools")
        self.p_tools_exp = PathRow(settings.dayz_tools_exp, self, "dayz_tools_exp")
        form_paths.addRow(BodyLabel(tr("settings.client", "DayZ")), self.p_client)
        form_paths.addRow(BodyLabel(tr("settings.server", "DayZ Server")), self.p_server)
        form_paths.addRow(BodyLabel(tr("settings.client_exp", "DayZ Experimental")), self.p_client_exp)
        form_paths.addRow(BodyLabel(tr("settings.server_exp", "DayZ Server Experimental")), self.p_server_exp)

        self.workshop = PlainTextEdit()
        self.workshop.setPlainText("\n".join(settings.workshop_dirs))
        self.workshop.setMaximumHeight(64)
        self.workshop.setToolTip(
            tr("settings.workshop_tip", "Папки steamapps/workshop/content/221100 — по одной на строку.")
        )
        form_paths.addRow(BodyLabel(tr("settings.workshop", "Steam Workshop")), self.workshop)

        form_paths.addRow(BodyLabel(tr("settings.dayz_tools", "DayZ Tools")), self.p_tools)
        form_paths.addRow(BodyLabel(tr("settings.dayz_tools_exp", "DayZ Tools Experimental")), self.p_tools_exp)

        self.p_downloads = PathRow(settings.downloads_dir, self)
        self.p_downloads.edit.setPlaceholderText(tr("settings.downloads_ph", "<папка программы>\\downloads"))
        self.p_downloads.edit.setToolTip(
            tr(
                "settings.downloads_tip",
                "Общее хранилище скачанных модов карт; во все корни они подключаются junction-ссылками.",
            )
        )
        form_paths.addRow(BodyLabel(tr("settings.downloads", "Папка для загрузок")), self.p_downloads)

        # ------------------------------------------------------------ Steam
        form_steam = section(tr("settings.section_steam", "Steam"))
        # ключ берём с живого поля: его могли вписать только что, не сохранив
        self.admin_ids = SteamIdList(list(settings.admin_steamids), lambda: self.steam_key.text().strip())
        self.admin_ids.setToolTip(tr("settings.admins_tip", "SteamID64 админов. Используется модами-админками."))
        form_steam.addRow(BodyLabel(tr("settings.admins", "Админские SteamID")), self.admin_ids)

        self.admin_pass = PasswordLineEdit()
        self.admin_pass.setMaxLength(_VPP_PASS_MAXLEN)
        # только печатные ASCII без пробела и кавычки: пароль уходит в кавычках
        # в serverDZ.cfg, а кириллицу VPPAdminTools не понимает
        self.admin_pass.setValidator(
            QRegularExpressionValidator(QRegularExpression(rf"[!#-~]{{0,{_VPP_PASS_MAXLEN}}}"))
        )
        self.admin_pass.setText(settings.admin_password)
        self.admin_pass.setToolTip(
            tr(
                "settings.admin_pass_tip",
                "До 32 символов, латиница/цифры/знаки — без кириллицы и "
                "пробелов. Пустое поле — вход в админку без пароля "
                "(vppDisablePassword = 1 в serverDZ.cfg).",
            )
        )
        form_steam.addRow(BodyLabel(tr("settings.admin_pass", "Пароль VPPA (необязательно)")), self.admin_pass)

        steam_row = QHBoxLayout()
        self.steam_key = PasswordLineEdit()
        self.steam_key.setText(settings.steam_api_key)
        btn_get_key = PushButton(FIF.LINK, tr("settings.steam_key_get", "Получить"))
        btn_get_key.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://steamcommunity.com/dev/apikey")))
        steam_row.addWidget(self.steam_key, 1)
        steam_row.addWidget(btn_get_key)
        form_steam.addRow(BodyLabel(tr("settings.steam_key", "Steam API-ключ (необязательно)")), steam_row)
        steam_hint = CaptionLabel(
            tr(
                "settings.steam_key_hint",
                "Не обязателен: зависимости модов и SteamID по ссылке определяются и без него — "
                "чтением страниц Steam. Ключ делает это быстрее и надёжнее (страницы Valve может "
                "в любой момент переверстать, а контракт API стабилен). Как получить: нажмите "
                "«Получить», войдите в Steam, в поле «Domain Name» впишите что угодно "
                "(например, localhost), согласитесь с условиями и скопируйте ключ сюда.",
            )
        )
        steam_hint.setWordWrap(True)
        form_steam.addRow("", steam_hint)

        # ------------------------------------------------------ Автоперепаковка
        form_pack = section(tr("settings.section_pack", "Автоперепаковка модов"))
        self._pack_flags = settings.pack_flags
        self._clean_meta = settings.clean_meta

        self.b_pbo_settings = PushButton(FIF.SETTING, tr("settings.pbo_settings", "Общие параметры сборки PBO"))
        self.b_pbo_settings.clicked.connect(self._open_pbo_settings)
        form_pack.addRow(BodyLabel(tr("settings.pbo_settings_label", "Этапы и инструменты")), self.b_pbo_settings)

        self.pack_engine = ComboBox()
        self.pack_engine.addItem(
            tr("settings.engine_normal", "Быстрая — собирать только изменённое"), userData="normal"
        )
        self.pack_engine.addItem(
            tr("settings.engine_full", "Полная — очистить temp и пересобрать всё"), userData="full"
        )
        self.pack_engine.setCurrentIndex(1 if settings.pack_engine == "full" else 0)
        self.pack_engine.setToolTip(
            tr(
                "settings.engine_tip",
                "Быстрая использует инкрементальный кеш; полная очищает временные файлы и пересобирает всё.",
            )
        )
        form_pack.addRow(BodyLabel(tr("settings.engine_label", "Режим автоперепаковки")), self.pack_engine)

        self.p_tools.edit.textChanged.connect(self._update_pbo_button_state)
        self._update_pbo_button_state()

        # ---------------------------------------------------- Filepatching
        form_fp = section(tr("settings.section_filepatch", "Filepatching"))
        fp_row = QHBoxLayout()
        self.b_fp_add = PushButton(FIF.LINK, tr("filepatch.add", "Создать симлинк"))
        self.b_fp_add.clicked.connect(self._filepatch_add)
        self.b_fp_help = TransparentToolButton(FIF.HELP)
        self.b_fp_help.setToolTip(tr("filepatch.help_tip", "Для чего это нужно"))
        self.b_fp_help.clicked.connect(self._show_filepatch_help)
        fp_row.addWidget(self.b_fp_add)
        fp_row.addWidget(self.b_fp_help)
        fp_row.addStretch(1)
        form_fp.addRow("", fp_row)

        fp_row2 = QHBoxLayout()
        self.b_fp_sync = PushButton(FIF.SYNC, tr("filepatch.sync", "Актуализировать Simlink"))
        self.b_fp_sync.setToolTip(
            tr(
                "filepatch.sync_tip",
                "Досоздаёт недостающие ссылки во всех корнях и убирает те, чья папка на диске P: пропала.",
            )
        )
        self.b_fp_sync.clicked.connect(self._filepatch_sync)
        self.b_fp_clear = PushButton(FIF.DELETE, tr("filepatch.clear", "Удалить все Simlink"))
        self.b_fp_clear.setToolTip(
            tr(
                "filepatch.clear_tip",
                "Снимает только ссылки, созданные этой кнопкой. Моды и прочее содержимое каталогов не трогает.",
            )
        )
        self.b_fp_clear.clicked.connect(self._filepatch_clear)
        fp_row2.addWidget(self.b_fp_sync)
        fp_row2.addWidget(self.b_fp_clear)
        fp_row2.addStretch(1)
        form_fp.addRow("", fp_row2)

        self.fp_status = CaptionLabel("")
        self.fp_status.setWordWrap(True)
        form_fp.addRow("", self.fp_status)
        self._update_filepatch_status()

        btns = QHBoxLayout()
        btn_detect = PushButton(FIF.SEARCH, tr("settings.autodetect", "Автопоиск незаполненных путей"))
        btn_detect.clicked.connect(self._autodetect)
        btn_save = PrimaryPushButton(FIF.SAVE, tr("common.save", "Сохранить"))
        btn_save.clicked.connect(self._save)
        self.unsaved = BodyLabel(tr("settings.unsaved", "Есть несохранённые изменения"))
        self.unsaved.setStyleSheet(f"color:{BRAND_WARNING};")
        self.unsaved.hide()
        btns.addWidget(btn_detect)
        btns.addStretch(1)
        btns.addWidget(self.unsaved)
        btns.addWidget(btn_save)
        layout.addLayout(btns)

        self.note = CaptionLabel("")
        layout.addWidget(self.note)
        layout.addStretch(1)

        # Подписываемся на все поля разом: перечислять сигналы по одному —
        # верный способ забыть новое поле и получить молча неверный индикатор.
        for widget in (self.lang, self.pack_engine, self.theme, self.stop_method):
            widget.currentIndexChanged.connect(lambda _i: self._refresh_dirty())
        for widget in (self.project_prefix, self.admin_pass, self.steam_key):
            widget.textChanged.connect(lambda _t: self._refresh_dirty())
        self.workshop.textChanged.connect(self._refresh_dirty)
        self.admin_ids.changed.connect(lambda: self._refresh_dirty())
        for row in (
            self.p_client,
            self.p_client_exp,
            self.p_server,
            self.p_server_exp,
            self.p_tools,
            self.p_tools_exp,
            self.p_downloads,
        ):
            row.edit.textChanged.connect(lambda _t: self._refresh_dirty())
        self._refresh_dirty()

        # Слежением за загрузками Steam владеет главное окно: качать можно
        # несколько компонентов сразу и уйти с этой страницы, а уведомление и
        # запись пути должны прийти всё равно. Здесь только отображение.
        self._path_rows = {
            "client_stable": self.p_client,
            "client_exp": self.p_client_exp,
            "server_stable": self.p_server,
            "server_exp": self.p_server_exp,
            "dayz_tools": self.p_tools,
            "dayz_tools_exp": self.p_tools_exp,
        }

    # ------------------------------------------------------- загрузки Steam

    def set_path_status(self, key: str, text: str) -> None:
        """Подпись под полем пути («Скачивание началось» либо пусто).

        Заодно перепроверяем сам путь: сигнал приходит и когда компонент
        удалили из Steam — тогда поле должно подсветиться, а кнопка установки
        вернуться.
        """
        row = self._path_rows.get(key)
        if row is not None:
            row.set_status(text)
            row.refresh_validity()

    def set_path_value(self, key: str, path: str, force: bool = False) -> None:
        """Подставляет путь, если поле пустое. Заполненное не трогаем — там мог
        быть ручной путь; force перезаписывает (компонент удалён — чистим поле).

        Нужно даже когда страница не открыта: иначе следующее нажатие
        «Сохранить» перезаписало бы значение тем, что осталось в виджете.
        """
        row = self._path_rows.get(key)
        if row is None or (not path and not force):
            return
        row.set_status("")
        if force or not row.text():
            row.edit.setText(path)

    def _check_updates_now(self) -> None:
        """Проверка по кнопке — идёт через главное окно: там же живёт пункт
        в навигации, который надо обновить, и уже скачанное состояние."""
        win = self.window()
        callback = getattr(win, "check_updates_now", None)
        if callable(callback):
            callback()

    def _theme_changed(self, _idx: int) -> None:
        code = str(self.theme.currentData() or "auto")
        setTheme({"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}.get(code, Theme.AUTO))
        self.settings.theme = code
        self.settings.save()

    def _autodetect(self) -> None:
        det = autodetect.detect_all()
        pairs = [
            (self.p_client, det["client_stable"]),
            (self.p_client_exp, det["client_exp"]),
            (self.p_server, det["server_stable"]),
            (self.p_server_exp, det["server_exp"]),
            (self.p_tools, det["dayz_tools"]),
            (self.p_tools_exp, det["dayz_tools_exp"]),
        ]
        filled = 0
        for row, val in pairs:
            if not row.text() and val:
                row.edit.setText(val)
                filled += 1
        if not self.workshop.toPlainText().strip() and det["workshop_dirs"]:
            self.workshop.setPlainText("\n".join(det["workshop_dirs"]))
            filled += 1
        self.note.setText(tr("settings.detected", "Заполнено полей: {n}", n=filled))

    def _update_pbo_button_state(self) -> None:
        """Встроенный packer доступен всегда; DayZ Tools нужны по выбранным опциям."""
        self.b_pbo_settings.setEnabled(True)
        self.b_pbo_settings.setToolTip(
            tr(
                "settings.pbo_settings_tip",
                "Общие параметры автоперепаковки и отдельной вкладки PBO Builder.",
            )
        )
        for i in range(self.pack_engine.count()):
            self.pack_engine.setItemEnabled(i, True)
        self.pack_engine.setToolTip(
            tr(
                "settings.engine_tip",
                "Быстрая использует инкрементальный кеш; полная очищает временные файлы и пересобирает всё.",
            )
        )

    def _show_filepatch_help(self) -> None:
        TeachingTip.create(
            target=self.b_fp_help,
            icon=FIF.HELP,
            title=tr("settings.section_filepatch", "Filepatching"),
            content=tr(
                "filepatch.help",
                "Симлинк нужен для корректной работы filepatching. Filepatching "
                "позволяет подтягивать скрипты без перепаковки PBO — достаточно "
                "перезапустить клиент и сервер.\n\n"
                "Для подключения укажите папку скриптов вашего мода на диске P:. "
                "Дальше ссылки создадутся автоматически везде, где это требуется — "
                "в клиенте и сервере, stable и Experimental.",
            ),
            isClosable=True,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=self,
        )

    def _update_filepatch_status(self) -> None:
        lines = filepatch.status_lines(self.settings)
        self.fp_status.setText("\n".join(lines) if lines else tr("filepatch.none", "Симлинки не подключены."))

    def _filepatch_report(self, rep, title: str) -> None:
        """Показывает итог операции. Ошибки важнее — их показываем отдельно."""
        parts = []
        if rep.created:
            parts.append(tr("filepatch.n_created", "создано: {n}", n=len(rep.created)))
        if rep.removed:
            parts.append(tr("filepatch.n_removed", "удалено: {n}", n=len(rep.removed)))
        if rep.kept:
            parts.append(tr("filepatch.n_kept", "уже было: {n}", n=len(rep.kept)))
        if rep.stale:
            parts.append(tr("filepatch.n_stale", "пропавших папок: {n}", n=len(rep.stale)))
        body = ", ".join(parts)

        if rep.failed:
            InfoBar.warning(
                title=title,
                content=(body + "\n" if body else "") + "\n".join(rep.failed),
                parent=self,
                duration=12000,
                position=InfoBarPosition.TOP_RIGHT,
            )
        else:
            InfoBar.success(
                title=title,
                content=body or tr("filepatch.nothing", "Изменений нет."),
                parent=self,
                duration=6000,
                position=InfoBarPosition.TOP_RIGHT,
            )
        self._update_filepatch_status()

    def _filepatch_add(self) -> None:
        # стартуем прямо с P: — оттуда всё равно только и можно выбирать
        start = "P:\\" if Path("P:\\").is_dir() else ""
        path = QFileDialog.getExistingDirectory(self, tr("filepatch.pick", "Папка скриптов мода на диске P:"), start)
        if not path:
            return
        rep, err = filepatch.add(self.settings, path)
        if err:
            InfoBar.error(
                title=tr("filepatch.add", "Создать симлинк"),
                content=err,
                parent=self,
                duration=10000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self._filepatch_report(rep, tr("filepatch.added", "Симлинк подключён"))

    def _filepatch_sync(self) -> None:
        self._filepatch_report(filepatch.sync(self.settings), tr("filepatch.synced", "Симлинки актуализированы"))

    def _filepatch_clear(self) -> None:
        if not self.settings.filepatch_links:
            InfoBar.info(
                title=tr("filepatch.none", "Симлинки не подключены."),
                content="",
                parent=self,
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        from qfluentwidgets import MessageBox

        box = MessageBox(
            tr("filepatch.clear", "Удалить все Simlink"),
            tr(
                "filepatch.clear_confirm",
                "Снять все ссылки filepatching во всех корнях?\n\n"
                "Сами папки со скриптами на диске P: останутся нетронутыми — "
                "удаляются только ссылки на них.",
            ),
            self.window(),
        )
        box.yesButton.setText(tr("common.yes", "Да"))
        box.cancelButton.setText(tr("common.no", "Нет"))
        if not box.exec():
            return
        self._filepatch_report(filepatch.remove_all(self.settings), tr("filepatch.cleared", "Симлинки удалены"))

    def _open_pbo_settings(self) -> None:
        dlg = PboProjectDialog(self.settings, self)
        if dlg.exec():
            self._clean_meta = False
            self._refresh_dirty()  # диалог сигналов полей не шлёт

    def _form_values(self) -> dict:
        """Что сейчас введено в форме — в терминах полей Settings.

        Один источник и для сохранения, и для проверки несохранённых изменений:
        иначе индикатор рано или поздно разойдётся с тем, что реально пишется.
        local_mods_dirs здесь нет намеренно — это поле редактируется на вкладке
        «Моды», страница настроек его не трогает.
        """
        return {
            "language": self.lang.currentData(),
            "check_updates": self.check_updates.isChecked(),
            "quit_on_close": self.quit_on_close.isChecked(),
            "stop_method": self.stop_method.currentData(),
            "project_prefix": self.project_prefix.text().strip(),
            "client_stable": self.p_client.text(),
            "client_exp": self.p_client_exp.text(),
            "server_stable": self.p_server.text(),
            "server_exp": self.p_server_exp.text(),
            "dayz_tools": self.p_tools.text(),
            "dayz_tools_exp": self.p_tools_exp.text(),
            "workshop_dirs": [x.strip() for x in self.workshop.toPlainText().splitlines() if x.strip()],
            "admin_steamids": self.admin_ids.values(),
            "admin_password": self.admin_pass.text(),
            "steam_api_key": self.steam_key.text().strip(),
            "downloads_dir": self.p_downloads.text(),
            "pack_flags": self._pack_flags,
            "clean_meta": self._clean_meta,
            "pack_engine": self.pack_engine.currentData(),
        }

    def reload_pack_flags(self) -> None:
        """Подхватывает флаги, изменённые снаружи (окно настроек запаковки с
        главной страницы). Без этого «Сохранить» здесь вернуло бы старое
        значение из своей копии."""
        self._pack_flags = self.settings.pack_flags
        self._clean_meta = self.settings.clean_meta
        self._refresh_dirty()

    def is_dirty(self) -> bool:
        return any(getattr(self.settings, k) != v for k, v in self._form_values().items())

    def _refresh_dirty(self) -> None:
        """Подсказка рядом с «Сохранить»: настройки применяются только по ней,
        а диалог PBO Builder закрывается по OK и выглядит применённым —
        без этой пометки правки молча терялись при выходе."""
        self.unsaved.setVisible(self.is_dirty())

    def _save(self) -> None:
        s = self.settings
        for key, value in self._form_values().items():
            setattr(s, key, value)
        s.save()
        self._refresh_dirty()
        if self.on_saved:
            self.on_saved()
