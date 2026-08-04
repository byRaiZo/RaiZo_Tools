"""Компактное окно поверх остальных — то, с чем работают во время отладки мода.

Главное окно нужно для настройки, а в цикле «поправил скрипт — перезапустил
сервер» от него требуется одна кнопка. Поэтому по крестику главное окно
уходит в трей, а на экране остаётся это: кнопка запуска, два кружка-индикатора
(сервер и клиент) и — под раскрывашкой — быстрые переключатели того, что
запускать. Подписей нет: они раздували бы окно, назначение поясняют подсказки.

Своей логики запуска здесь нет: все кнопки дёргают методы главного окна,
иначе поведение двух окон неизбежно разъехалось бы.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel
from qfluentwidgets import (
    PrimaryToolButton,
    PushButton,
    TransparentToolButton,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    isDarkTheme,
    qconfig,
)

from core.i18n import tr

# Окно должно занимать минимум места: в свёрнутом виде это кнопка, два
# индикатора и имя пресета. В развёрнутом появляются подписи галок — под них
# окно расширяется и вправо, и вниз.
_COLLAPSED = (100, 42)
_EXPANDED = (244, 186)
_DOT = 8
_RUN_BTN = 30


class MiniWindow(QWidget):
    """Мини-панель управления сервером.

    Окно беcрамочное: системный заголовок на Windows не подчиняется тёмной
    теме, а рядом с остальным интерфейсом это бросается в глаза. Взамен —
    свой заголовок с именем пресета, перетаскивание за него и крестик,
    который уводит обратно в трей, а не закрывает приложение.
    """

    def __init__(self, main_window):
        super().__init__(
            None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.mw = main_window
        self._drag_from: QPoint | None = None
        self._syncing = False  # защита от петли при зеркалении списка
        # Окно беcрамочное и со скруглёнными углами: без прозрачного фона
        # вокруг карточки просвечивает системный фон QWidget (#f0f0f0) —
        # получается светлая обводка, особенно заметная в тёмной теме.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # рамка нужна именно потому, что окно беcрамочное: без неё оно
        # сливается с тем, поверх чего висит
        self.card = QFrame(self)
        self.card.setObjectName("miniCard")
        root.addWidget(self.card)
        box = QVBoxLayout(self.card)
        box.setContentsMargins(6, 5, 3, 5)
        box.setSpacing(4)

        # Всё управление — одной строкой: индикаторы, кнопка, имя пресета и
        # служебные кнопки. Раскладка в несколько строк оставляла бы половину
        # окна пустой, а оно должно занимать минимум места на экране.
        main_row = QHBoxLayout()
        main_row.setSpacing(4)

        dots = QVBoxLayout()
        dots.setSpacing(4)
        self.dot_server = self._make_dot(tr("common.server", "Сервер"))
        self.dot_client = self._make_dot(tr("common.client", "Клиент"))
        dots.addStretch(1)
        dots.addWidget(self.dot_server, 0, Qt.AlignmentFlag.AlignHCenter)
        dots.addWidget(self.dot_client, 0, Qt.AlignmentFlag.AlignHCenter)
        dots.addStretch(1)
        main_row.addLayout(dots)

        self.b_run = PrimaryToolButton(FIF.PLAY)
        self.b_run.setFixedSize(_RUN_BTN, _RUN_BTN)
        self.b_run.setIconSize(QSize(14, 14))
        self.b_run.clicked.connect(self._toggle_run)
        main_row.addWidget(self.b_run)

        main_row.addStretch(1)

        self.b_expand = TransparentToolButton(FIF.CHEVRON_DOWN_MED)
        self.b_expand.setFixedSize(20, 20)
        self.b_expand.setIconSize(QSize(10, 10))
        self.b_expand.setToolTip(tr("mini.expand", "Быстрые настройки"))
        self.b_expand.clicked.connect(self._toggle_panel)
        main_row.addWidget(self.b_expand)

        b_hide = TransparentToolButton(FIF.CLOSE)
        b_hide.setFixedSize(20, 20)
        b_hide.setIconSize(QSize(9, 9))
        b_hide.setToolTip(tr("mini.to_tray", "Свернуть в трей"))
        b_hide.clicked.connect(self.hide)
        main_row.addWidget(b_hide)
        box.addLayout(main_row)

        # --- раскрывающаяся часть: дубли переключателей главного окна
        self.panel = QWidget(self.card)
        pbox = QVBoxLayout(self.panel)
        pbox.setContentsMargins(0, 0, 0, 0)
        pbox.setSpacing(4)
        # выбор пресета — здесь, а не в свёрнутой строке: там он занимал бы
        # больше места, чем все кнопки вместе
        self.preset_combo = ComboBox()
        self.preset_combo.setFixedHeight(26)
        self.preset_combo.currentIndexChanged.connect(self._preset_picked)
        pbox.addWidget(self.preset_combo)
        row = QHBoxLayout()
        self.chk_server = CheckBox(tr("common.server", "Сервер"))
        self.chk_client = CheckBox(tr("common.client", "Клиент"))
        row.addWidget(self.chk_server)
        row.addWidget(self.chk_client)
        row.addStretch(1)
        pbox.addLayout(row)
        self.chk_repack = CheckBox(tr("mini.repack", "Перепаковывать моды"))
        pbox.addWidget(self.chk_repack)
        self.b_logs = PushButton(FIF.DOCUMENT, tr("main.show_logs", "Показать логи"))
        self.b_logs.clicked.connect(self.mw._show_logs)
        pbox.addWidget(self.b_logs)
        self.b_restore = PushButton(FIF.VIEW, tr("tray.restore", "Развернуть"))
        self.b_restore.setToolTip(tr("mini.restore_tip", "Вернуть главное окно приложения"))
        self.b_restore.clicked.connect(self.mw.restore_from_tray)
        pbox.addWidget(self.b_restore)
        box.addWidget(self.panel)
        self.panel.hide()
        self.setFixedSize(*_COLLAPSED)

        self.chk_server.toggled.connect(self._flags_changed)
        self.chk_client.toggled.connect(self._flags_changed)
        self.chk_repack.toggled.connect(self._repack_changed)

        self._apply_bg()
        qconfig.themeChanged.connect(self._apply_bg)

    # ----------------------------------------------------------------- вид

    def _apply_bg(self) -> None:
        """Фон и рамка: обычный QWidget сам под тему не красится (см. LogWindow)."""
        dark = isDarkTheme()
        bg = "rgb(43, 43, 43)" if dark else "white"
        border = "rgba(255,255,255,0.10)" if dark else "rgba(0,0,0,0.13)"
        self.setStyleSheet(f"QFrame#miniCard{{background-color:{bg};border:1px solid {border};border-radius:8px;}}")

    def _toggle_panel(self) -> None:
        opening = self.panel.isHidden()
        self.panel.setVisible(opening)
        self.b_expand.setIcon(FIF.UP if opening else FIF.CHEVRON_DOWN_MED)
        self.setFixedSize(*(_EXPANDED if opening else _COLLAPSED))

    # перетаскивание за любое свободное место: своего заголовка окна нет
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_from is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:
        self._drag_from = None
        self.mw.settings.mini_pos = [self.x(), self.y()]
        self.mw.settings.save()

    # -------------------------------------------------------------- данные

    def sync(self) -> None:
        """Подтягивает состояние из главного окна. Зовётся при каждом показе:
        пока мини-окно скрыто, пресет и галки могли поменяться."""
        p = self.mw.current
        self._preset_name = p.name if p else tr("main.no_preset_short", "Нет пресета")
        # список зеркалим с главного окна, чтобы не дублировать его наполнение
        main = self.mw.launch_page.preset_combo
        self._syncing = True
        self.preset_combo.clear()
        for i in range(main.count()):
            self.preset_combo.addItem(main.itemText(i), userData=main.itemData(i))
        self.preset_combo.setCurrentIndex(main.currentIndex())
        self._syncing = False
        self.b_run.setEnabled(p is not None)
        for cb, value in (
            (self.chk_server, bool(p and p.launch_server)),
            (self.chk_client, bool(p and p.launch_client)),
        ):
            cb.blockSignals(True)
            cb.setChecked(value)
            cb.blockSignals(False)
        self.chk_repack.blockSignals(True)
        self.chk_repack.setChecked(self.mw.settings.repack_before_launch)
        self.chk_repack.blockSignals(False)
        self.refresh_status()

    def _preset_picked(self, idx: int) -> None:
        """Переключение отдаём главному окну — там вся обвязка (перечитать
        конфиг, моды, доступность веток), дублировать её здесь нельзя."""
        if self._syncing or idx < 0:
            return
        self.mw.launch_page.preset_combo.setCurrentIndex(idx)
        self.sync()

    def set_update_mark(self, ready: bool) -> None:
        """Метка на «Развернуть», когда обновление ждёт перезапуска.

        Места на текст в мини-окне нет, а знать надо: в развёрнутом окне
        подробности покажет пункт в панели навигации.
        """
        self.b_restore.setText(tr("tray.restore", "Развернуть") + (" ●" if ready else ""))
        self.b_restore.setToolTip(
            tr("mini.update_ready", "Скачано обновление — нужен перезапуск")
            if ready
            else tr("mini.restore_tip", "Вернуть основное окно")
        )

    def _make_dot(self, name: str) -> QLabel:
        dot = QLabel(self)
        dot.setFixedSize(_DOT, _DOT)
        dot.setToolTip(name)
        return dot

    def _set_dot(self, dot: QLabel, state: str) -> None:
        color = self.mw.STATE_COLORS[state]
        dot.setStyleSheet(f"background:{color};border-radius:{_DOT // 2}px;")

    def refresh_status(self) -> None:
        """Кружки и иконка кнопки — вызывается таймером главного окна."""
        # состояние берём у главного окна, а не считаем своё: правило на все
        # индикаторы одно, см. MainWindow.side_state
        from ui.launch_status import SERVER, CLIENT

        self._set_dot(self.dot_server, self.mw.side_state(SERVER))
        self._set_dot(self.dot_client, self.mw.side_state(CLIENT))
        state = self.mw.launch_state()
        # POWER_BUTTON, а не CLOSE: крестик уже занят кнопкой «свернуть в трей»
        # в шапке, и два одинаковых значка рядом читались бы как одно действие
        icon, action = {
            self.mw.LB_LAUNCH: (FIF.PLAY, tr("main.launch_btn", "Запустить")),
            self.mw.LB_STARTING: (FIF.SYNC, tr("main.starting_btn", "Запускается")),
            self.mw.LB_STOP: (FIF.POWER_BUTTON, tr("main.stop_btn", "Остановить")),
        }[state]
        self.b_run.setIcon(icon)
        busy = state == self.mw.LB_STARTING
        self.b_run.setEnabled(not busy and self.mw.current is not None)
        # те же галки, что и на главной странице, — блокируем их так же
        self.chk_server.setEnabled(not busy)
        self.chk_client.setEnabled(not busy)
        # перепаковка при живой игре невозможна — PBO заняты
        self.chk_repack.setEnabled(not self.mw.busy_with_processes())
        # имя пресета в свёрнутом виде не показано — дублируем в подсказке
        self.b_run.setToolTip(f"{action} — {getattr(self, '_preset_name', '')}".strip(" —"))

    # ------------------------------------------------------------ действия

    def _toggle_run(self) -> None:
        """Та же кнопка, что и на главной странице, — логика общая."""
        self.mw.launch_button_clicked()
        self.refresh_status()

    def _flags_changed(self) -> None:
        """Галки — те же поля пресета, что и на главной странице."""
        lp = self.mw.launch_page
        lp.chk_server.setChecked(self.chk_server.isChecked())
        lp.chk_client.setChecked(self.chk_client.isChecked())

    def _repack_changed(self, on: bool) -> None:
        """Способ запаковки не трогаем — он выбирается в главном окне, здесь
        только включение. При включении берём последний выбранный."""
        lp = self.mw.launch_page
        engine = self.mw.settings.pack_engine if on else ""
        idx = lp.pack_engine.findData(engine)
        if idx < 0:  # выбранный способ стал недоступен
            idx = 0
        lp.pack_engine.setCurrentIndex(idx)

    def show_at_saved_pos(self) -> None:
        pos = self.mw.settings.mini_pos
        if isinstance(pos, list) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
        self.sync()
        self.show()
        self.raise_()
