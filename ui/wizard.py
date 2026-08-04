"""Мастер первого запуска: язык, пути (автопоиск), Steam-настройки."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWizardPage,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QFileDialog,
)
from qfluentwidgets import (
    ComboBox,
    LineEdit,
    PushButton,
    ToolButton,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
)

from core import autodetect, i18n
from core.i18n import tr, AVAILABLE
from core.settings import Settings, check_path
from core.steam_urls import SETTINGS_APPS
from ui.settings_page import make_install_button
from ui.steam_watch import SteamWatcher, status_text
from ui.steamid_list import SteamIdList
from ui.theme import ThemedWizard


class FirstRunWizard(ThemedWizard):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("wizard.title", "RaiZo Tools — первая настройка"))
        self.resize(720, 560)

        # --- Шаг 1: язык + префикс проекта
        p1 = QWizardPage()
        p1.setTitle(tr("wizard.lang_title", "Язык / Language / Sprache"))
        l1 = QVBoxLayout(p1)
        self.lang = ComboBox()
        for code, label in AVAILABLE.items():
            self.lang.addItem(label, userData=code)
        idx = list(AVAILABLE).index(settings.language) if settings.language in AVAILABLE else 0
        self.lang.setCurrentIndex(idx)
        l1.addWidget(self.lang)

        l1.addWidget(BodyLabel(tr("wizard.prefix_label", "Название проекта / префикс мододела")))
        self.project_prefix = LineEdit()
        self.project_prefix.setText(settings.project_prefix)
        self.project_prefix.setPlaceholderText(tr("wizard.prefix_ph", "Например: KR"))
        l1.addWidget(self.project_prefix)
        prefix_hint = CaptionLabel(
            tr(
                "wizard.prefix_hint",
                "Будет подставляться в hostname создаваемых серверов — "
                "не придётся вводить его вручную каждый раз. "
                "Изменить можно позже в настройках.",
            )
        )
        prefix_hint.setWordWrap(True)
        l1.addWidget(prefix_hint)
        p1.registerField("prefix*", self.project_prefix)

        l1.addStretch(1)
        self.addPage(p1)

        # --- Шаг 2: пути (автопоиск уже выполнен)
        p2 = QWizardPage()
        p2.setTitle(tr("wizard.paths_title", "Пути"))
        p2.setSubTitle(
            tr(
                "wizard.paths_sub",
                "Пути найдены автоматически по реестру Steam. Проверьте и поправьте при необходимости.",
            )
        )
        l2v = QVBoxLayout(p2)
        paths_help = CaptionLabel(
            tr(
                "wizard.paths_help",
                "Ничего страшного, если что-то не найдено или не установлено — поле можно "
                "оставить пустым и заполнить позже в «Настройках», когда всё будет готово. "
                "Красная рамка означает, что путь указан, но по нему нет папки или в ней "
                "нет самой программы (например, игру удалили, а папка осталась, или в "
                "реестре остался след от старой установки). DayZ, Experimental-версия и "
                "выделенный сервер и DayZ Tools устанавливаются и обновляются через Steam. "
                "Дополнительный PBO-паковщик устанавливать не нужно: он встроен.",
            )
        )
        paths_help.setWordWrap(True)
        l2v.addWidget(paths_help)
        l2 = QFormLayout()
        l2v.addLayout(l2)
        det = autodetect.detect_all()
        self.paths: dict[str, LineEdit] = {}

        self.path_status: dict[str, CaptionLabel] = {}

        def row(key: str, label: str, value: str):
            box = QVBoxLayout()
            box.setSpacing(2)
            h = QHBoxLayout()
            edit = LineEdit()
            edit.setText(value)
            # проверка та же, что в «Настройках»: для клиента и сервера мало
            # существования папки — нужен исполняемый файл
            edit.setError(bool(check_path(key, value)))
            edit.textChanged.connect(lambda t, e=edit, k=key: e.setError(bool(check_path(k, t.strip()))))
            btn = ToolButton(FIF.FOLDER)
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            h.addWidget(edit, 1)
            h.addWidget(btn)
            # не установлено — предлагаем взять недостающее, не уходя из мастера
            b_inst = make_install_button(self, key)
            if b_inst is not None:
                b_inst.setVisible(not value.strip())
                edit.textChanged.connect(lambda t, b=b_inst: b.setVisible(not t.strip()))
                h.addWidget(b_inst)
            box.addLayout(h)
            # состояние загрузки Steam: заполняется наблюдателем, пока пусто — скрыто
            st = CaptionLabel("")
            st.setWordWrap(True)
            st.hide()
            box.addWidget(st)
            l2.addRow(label, box)
            self.paths[key] = edit
            self.path_status[key] = st

        row("client_stable", tr("settings.client", "DayZ"), settings.client_stable or det["client_stable"])
        row("server_stable", tr("settings.server", "DayZ Server"), settings.server_stable or det["server_stable"])
        row("client_exp", tr("settings.client_exp", "DayZ Experimental"), settings.client_exp or det["client_exp"])
        row(
            "server_exp",
            tr("settings.server_exp", "DayZ Server Experimental"),
            settings.server_exp or det["server_exp"],
        )
        row("dayz_tools", tr("settings.dayz_tools", "DayZ Tools"), settings.dayz_tools or det["dayz_tools"])
        row(
            "dayz_tools_exp",
            tr("settings.dayz_tools_exp", "DayZ Tools Experimental"),
            settings.dayz_tools_exp or det["dayz_tools_exp"],
        )
        self._workshop_dirs = settings.workshop_dirs or det["workshop_dirs"]
        self.ws_label = CaptionLabel(
            "\n".join(self._workshop_dirs)
            or tr("wizard.no_workshop", "Workshop не найден (можно указать в настройках)")
        )
        l2.addRow(tr("settings.workshop", "Steam Workshop"), self.ws_label)

        # повторный автопоиск: пригодится, если пользователь доустановил
        # что-то мимо наших кнопок, не закрывая мастер
        b_detect = PushButton(FIF.SEARCH, tr("wizard.redetect", "Найти пути автоматически"))
        b_detect.setToolTip(tr("wizard.redetect_tip", "Перечитывает библиотеки Steam и заполняет пустые поля."))
        b_detect.clicked.connect(self._redetect)
        l2v.addWidget(b_detect)
        self.addPage(p2)

        # --- Шаг 3: Steam — SteamID админов
        #     API-ключ сюда намеренно не вынесен: он нигде не обязателен
        #     (везде есть безключевой путь) — его место в «Настройках».
        p_steam = QWizardPage()
        p_steam.setTitle(tr("wizard.steam_title", "Steam"))
        p_steam.setSubTitle(
            tr(
                "wizard.steam_sub",
                "Поле необязательное и легко заполняется позже в «Настройках» — но про него проще не забыть сразу.",
            )
        )
        l_steam = QFormLayout(p_steam)
        self.admin_ids = SteamIdList(list(settings.admin_steamids), lambda: self.settings.steam_api_key)
        l_steam.addRow(tr("settings.admins", "Админские SteamID"), self.admin_ids)
        admin_hint = CaptionLabel(
            tr(
                "wizard.admin_hint",
                "Используется модами-админками (COT, VPPAdminTools, LBmaster) для выдачи "
                "прав. Проще всего — нажать «+» и вставить ссылку на свой профиль "
                "Steam, SteamID64 определится сам.",
            )
        )
        admin_hint.setWordWrap(True)
        l_steam.addRow("", admin_hint)
        self.addPage(p_steam)

        # --- Шаг 4: финиш
        p4 = QWizardPage()
        p4.setTitle(tr("common.done", "Готово"))
        l4 = QVBoxLayout(p4)
        l4.addWidget(
            BodyLabel(
                tr(
                    "wizard.done_text",
                    "Настройка завершена. Всё можно изменить позже в «Настройках».\n\n"
                    "Дальше: создайте или выберите пресет, подключите моды на вкладке «Моды»\n"
                    "и нажмите «Запустить».",
                )
            )
        )
        self.addPage(p4)

        # Кнопка установки отправляет пользователя в Steam, и дальше мастер
        # ничего бы о загрузке не знал — поэтому следим за ней сами и
        # подставляем путь, как только компонент установится.
        self.watcher = SteamWatcher(self)
        self.watcher.watch_apps(self.paths)
        self.watcher.app_changed.connect(self._steam_app_changed)
        self.watcher.app_installed.connect(self._steam_app_installed)
        self.watcher.start()

    # ------------------------------------------------------- загрузки Steam

    def _steam_app_changed(self, key: str, st) -> None:
        label = self.path_status.get(key)
        if label is None:
            return
        text = status_text(st)
        label.setText(text)
        label.setVisible(bool(text))

    def _steam_app_installed(self, key: str, path: str) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition

        edit = self.paths.get(key)
        label = self.path_status.get(key)
        if label is not None:
            label.setVisible(False)
        if edit is None or not path:
            return
        title = SETTINGS_APPS.get(key, ("", key))[1]
        if edit.text().strip():
            return  # путь уже задан — вероятно, вручную, не перетираем
        edit.setText(path)
        InfoBar.success(
            title=tr("steam.dl_done", "«{n}» установлен", n=title),
            content=tr("steam.dl_path_set_wizard", "Путь подставлен автоматически."),
            parent=self,
            duration=8000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _redetect(self) -> None:
        """Повторный автопоиск — заполняет только пустые поля."""
        from qfluentwidgets import InfoBar, InfoBarPosition

        det = autodetect.detect_all()
        filled = 0
        for key, edit in self.paths.items():
            if not edit.text().strip() and det.get(key):
                edit.setText(det[key])
                filled += 1
        if not self._workshop_dirs and det["workshop_dirs"]:
            self._workshop_dirs = det["workshop_dirs"]
            self.ws_label.setText("\n".join(self._workshop_dirs))
            filled += 1
        InfoBar.info(
            title=tr("settings.detected", "Заполнено полей: {n}", n=filled),
            content="",
            parent=self,
            duration=4000,
            position=InfoBarPosition.TOP_RIGHT,
        )

    def _browse(self, edit: LineEdit) -> None:
        p = QFileDialog.getExistingDirectory(self, "", edit.text())
        if p:
            edit.setText(p)

    def accept(self) -> None:
        s = self.settings
        s.language = str(self.lang.currentData() or "auto")
        s.project_prefix = self.project_prefix.text().strip()
        for key, edit in self.paths.items():
            setattr(s, key, edit.text().strip())
        s.workshop_dirs = self._workshop_dirs
        s.admin_steamids = self.admin_ids.values()
        s.first_run_done = True
        s.save()
        i18n.load(s.language)

        super().accept()
