"""Вкладка редактора serverDZ.cfg: переменная -> поле ввода, кодировка UTF-8 без BOM."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidgetItem,
    QHeaderView,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    TableWidget,
    BodyLabel,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    FluentIcon as FIF,
)

from core.i18n import tr
from core.servercfg import ServerCfg

# Подсказки к самым ходовым переменным
_HINTS_RU = {
    "hostname": "Название сервера в браузере серверов.",
    "password": "Пароль для входа на сервер (пусто — без пароля).",
    "passwordAdmin": "Пароль администратора (команды #login).",
    "maxPlayers": "Максимум игроков.",
    "verifySignatures": "Проверка подписей PBO: 2 — включена (нужны .bikey в keys), 0 — выключена (для разработки).",
    "forceSameBuild": "Пускать только клиентов с той же сборкой игры.",
    "disableVoN": "Отключить голосовой чат.",
    "vonCodecQuality": "Качество кодека голоса (0–30).",
    "disable3rdPerson": "Запретить вид от третьего лица.",
    "disableCrosshair": "Убрать прицел.",
    "serverTime": 'Стартовое время сервера: SystemTime или "YYYY/MM/DD/HH/MM".',
    "serverTimeAcceleration": "Ускорение игрового времени (множитель).",
    "serverNightTimeAcceleration": "Дополнительное ускорение ночи.",
    "serverTimePersistent": "Сохранять игровое время между рестартами.",
    "instanceId": "Идентификатор инстанса (папка storage_<id> в миссии).",
    "storageAutoFix": "Автопочинка битого persistence-файла.",
    "steamQueryPort": "Порт Steam Query (обычно порт+2).",
    "enableDebugMonitor": "Показать отладочный монитор игрокам.",
    "allowFilePatching": "Пускать клиентов с -filePatching (обязательно для отладки сорсов).",
    "lightingConfig": "Освещение ночи: 0 — яркая, 1 — тёмная, 2 — вариант Сахала.",
    "disableBaseDamage": "Отключить урон по базам (заборы, вышки).",
    "disableContainerDamage": "Отключить урон по контейнерам (палатки, бочки, ящики).",
    "disableRespawnDialog": "Скрыть диалог выбора точки респауна.",
    "description": "Описание сервера в браузере серверов (до 255 символов).",
    "enableWhitelist": "Включить вайтлист (0-1).",
    "disableBanlist": "Не использовать ban.txt (по умолчанию false).",
    "disablePrioritylist": "Не использовать priority.txt (по умолчанию false).",
    "disableMultiAccountMitigation": "Отключить защиту от мультиаккаунтов (консоли).",
    "pingWarning": "Пинг (мс), при котором показывается жёлтое предупреждение.",
    "pingCritical": "Пинг (мс), при котором показывается красное предупреждение.",
    "MaxPing": "Пинг (мс), при котором игрока кикает с сервера.",
    "serverFpsWarning": "FPS сервера, ниже которого показывается предупреждение (минимум 11).",
    "shotValidation": "Валидация выстрелов: 1 — включена, 0 — выключена.",
    "clientPort": "Принудительный порт для подключения клиентов.",
    "template": "Миссия сервера в формате <Миссия>.<Террейн> (class Missions).",
    "networkRangeClose": "Сетевой пузырь (м): ближние объекты с предметами внутри (рюкзаки). По умолчанию 20.",
    "networkRangeNear": "Сетевой пузырь (м): ближние предметы инвентаря. По умолчанию 150.",
    "networkRangeFar": "Сетевой пузырь (м): дальние объекты. По умолчанию 1000.",
    "networkRangeDistantEffect": "Сетевой пузырь (м): эффекты (звуки). По умолчанию 4000.",
    "defaultVisibility": "Максимальная дальность отрисовки террейна на сервере.",
    "defaultObjectViewDistance": "Максимальная дальность отрисовки объектов на сервере.",
    "guaranteedUpdates": "Протокол связи с сервером (только 1).",
    "loginQueueConcurrentPlayers": "Сколько игроков одновременно обрабатывается при входе.",
    "loginQueueMaxPlayers": "Максимум игроков в очереди на вход.",
    "respawnTime": "Задержка (сек) перед созданием нового персонажа после смерти.",
    "motdInterval": "Интервал (сек) между сообщениями motd.",
    "timeStampFormat": "Формат таймштампов в RPT: Full или Short.",
    "logAverageFps": "Писать средний FPS сервера каждые N секунд (нужен -doLogs).",
    "logMemory": "Писать потребление памяти каждые N секунд (нужен -doLogs).",
    "logPlayers": "Писать число игроков каждые N секунд (нужен -doLogs).",
    "logFile": "Файл консольного лога сервера в папке профиля.",
    "adminLogPlayerHitsOnly": "1 — только попадания по игрокам, 0 — все попадания.",
    "adminLogPlacement": "Логировать установку ловушек и палаток.",
    "adminLogBuildActions": "Логировать действия базостроения.",
    "adminLogPlayerList": "Периодический список игроков с позициями (раз в 5 минут).",
    "simulatedPlayersBatch": "Лимит игроков, симулируемых за один кадр сервера.",
    "multithreadedReplication": "Многопоточная репликация (число потоков — из dayzsettings.xml).",
    "speedhackDetection": "Детект спидхака: 1 — строгий … 10 — мягкий.",
    "disablePersonalLight": "Отключить персональную подсветку у всех клиентов.",
    "networkObjectBatchLogSlow": "Порог (сек): если обработка сетевого «пузыря» занимает дольше — пишется в лог.",
    "networkObjectBatchEnforceBandwidthLimits": "Ограничивать создание объектов по статистике использования канала.",
    "networkObjectBatchUseEstimatedBandwidth": "0 — реально отправленные данные за прошлый кадр, 1 — грубая оценка.",
    "networkObjectBatchUseDynamicMaximumBandwidth": "Лимит канала — доля от текущего максимума, а не жёсткое число.",
    "networkObjectBatchBandwidthLimit": "Сам лимит канала: доля [0,1] или число [1,∞) — смотря что выше.",
    "networkObjectBatchCompute": "Сколько объектов на создание/удаление проверяется за один кадр сервера.",
    "networkObjectBatchSendCreate": "Максимум объектов, отправляемых на создание за кадр.",
    "networkObjectBatchSendDelete": "Максимум объектов, отправляемых на удаление за кадр.",
}


class CfgEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: ServerCfg | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        top = QHBoxLayout()
        self.path_label = BodyLabel(tr("cfg.no_file", "Конфиг не загружен"))
        self.enc_label = BodyLabel("")
        self.enc_label.setStyleSheet("color:#b8860b;")
        btn_reload = PushButton(FIF.SYNC, tr("cfg.reload", "Перечитать"))
        btn_reload.clicked.connect(self.reload)
        btn_save = PrimaryPushButton(FIF.SAVE, tr("cfg.save", "Сохранить (UTF-8 без BOM)"))
        btn_save.clicked.connect(self.save)
        top.addWidget(self.path_label, 1)
        top.addWidget(self.enc_label)
        top.addWidget(btn_reload)
        top.addWidget(btn_save)
        layout.addLayout(top)

        self.table = TableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(
            [
                tr("cfg.var", "Переменная"),
                tr("cfg.value", "Значение"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        hint = CaptionLabel(tr("cfg.hint", "Меняются только значения — комментарии и структура файла сохраняются."))
        layout.addWidget(hint)

        self._path: Path | None = None

    def set_path(self, path: Path | None) -> None:
        self._path = path
        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        self.cfg = None
        self.enc_label.setText("")
        if not self._path or not self._path.is_file():
            self.path_label.setText(tr("cfg.no_file", "Конфиг не загружен"))
            return
        try:
            self.cfg = ServerCfg(self._path)
        except OSError as e:
            self.path_label.setText(str(e))
            return
        self.path_label.setText(str(self._path))
        if self.cfg.encoding != "utf-8":
            self.enc_label.setText(
                tr("cfg.bad_enc", "Кодировка {enc} — при сохранении станет UTF-8 без BOM", enc=self.cfg.encoding)
            )
        for v in self.cfg.variables():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(v.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            hint = _HINTS_RU.get(v.name)
            if hint:
                name_item.setToolTip(tr(f"cfgvar.{v.name}", hint))
            val_item = QTableWidgetItem(v.value)
            if hint:
                val_item.setToolTip(tr(f"cfgvar.{v.name}", hint))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, val_item)

    def save(self) -> None:
        if not self.cfg:
            return
        from core.launcher import dayz_running

        if dayz_running():
            InfoBar.warning(
                title=tr("cfg.save_busy", "Сервер запущен — сохранение отменено"),
                content=tr(
                    "cfg.save_busy_body",
                    "Остановите сервер: изменения cfg он всё равно не "
                    "подхватит на лету, а при выходе может перезаписать файл.",
                ),
                parent=self,
                duration=6000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        values = {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            values[name] = self.table.item(row, 1).text()
        try:
            self.cfg.set_values(values)
            self.cfg.save()
        except OSError as e:
            InfoBar.error(
                title=tr("cfg.save_err_title", "Ошибка сохранения"),
                content=str(e),
                parent=self,
                duration=5000,
                position=InfoBarPosition.TOP_RIGHT,
            )
            return
        self.enc_label.setText("")
        InfoBar.success(
            title=tr("cfg.saved", "Конфиг сохранён в UTF-8 без BOM."),
            content="",
            parent=self,
            duration=3000,
            position=InfoBarPosition.TOP_RIGHT,
        )
