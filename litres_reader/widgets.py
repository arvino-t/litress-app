"""Элементы интерфейса в стиле libadwaita: заголовок окна, уведомления, карточки книг и т.п."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer,
                            Signal, Property)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLayout, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import style


def cls(widget, *names):
    """Задать «CSS-классы» виджету (как add_css_class в GTK)."""
    current = widget.property("cls") or []
    widget.setProperty("cls", list(dict.fromkeys([*current, *names])))
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def uncls(widget, *names):
    current = [n for n in (widget.property("cls") or []) if n not in names]
    widget.setProperty("cls", current)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


class IconButton(QToolButton):
    """Кнопка со значком Adwaita; значок перекрашивается при смене темы."""

    def __init__(self, icon_name, tooltip="", flat=True, circular=False, size=16, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._size = size
        self._color = None
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(size, size))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if flat:
            cls(self, "flat")
        if circular:
            cls(self, "circular")
        self.refresh_icon()

    def set_icon_name(self, name, color=None):
        self._icon_name = name
        self._color = color
        self.refresh_icon()

    def refresh_icon(self):
        self.setIcon(style.icon(self._icon_name, self._color, self._size))


def label(text="", *classes, wrap=False, align=None):
    lbl = QLabel(text)
    if classes:
        cls(lbl, *classes)
    lbl.setWordWrap(wrap)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


class HeaderBar(QFrame):
    """Заголовок окна в духе Adw.HeaderBar: слева/справа кнопки, в центре название.

    Окно без системной рамки: заголовок служит полосой для перетаскивания,
    двойной щелчок разворачивает окно, справа — круглые кнопки окна.
    """

    def __init__(self, window, title="", subtitle="", show_controls=True):
        super().__init__()
        self.setObjectName("headerbar")
        self._window = window
        self.setFixedHeight(47)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.start = QHBoxLayout()
        self.start.setSpacing(6)
        self.end = QHBoxLayout()
        self.end.setSpacing(6)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.title = label(title, align=Qt.AlignmentFlag.AlignCenter)
        self.title.setObjectName("title")
        self.subtitle = label(subtitle, align=Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setVisible(bool(subtitle))
        for w in (self.title, self.subtitle):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cl.addStretch()
        cl.addWidget(self.title)
        cl.addWidget(self.subtitle)
        cl.addStretch()
        center.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Центр всегда ровно посередине: слева и справа одинаковые по ширине блоки
        self._left = QWidget()
        self._left.setLayout(self.start)
        self._right = QWidget()
        self._right.setLayout(self.end)
        self.start.setContentsMargins(0, 0, 0, 0)
        self.end.setContentsMargins(0, 0, 0, 0)
        self.start.addStretch(0)
        lay.addWidget(self._left)
        lay.addWidget(center, 1)
        lay.addWidget(self._right)

        self.controls = []
        if show_controls:
            self.end.addSpacing(6)
            for name, tip, slot in (("window-minimize", "Свернуть", window.showMinimized),
                                    ("window-maximize", "Развернуть", self._toggle_max),
                                    ("window-close", "Закрыть", window.close)):
                b = IconButton(name, tip, flat=False)
                cls(b, "wincontrol")
                b.clicked.connect(slot)
                self.end.addWidget(b)
                self.controls.append(b)

    def set_title(self, title, subtitle=None):
        self.title.setText(title)
        if subtitle is not None:
            self.subtitle.setText(subtitle)
            self.subtitle.setVisible(bool(subtitle))

    def pack_start(self, w):
        self.start.insertWidget(self.start.count() - 1, w)
        self._balance()
        return w

    def pack_end(self, w):
        # Кнопки окна всегда крайние справа
        pos = self.end.count() - (len(self.controls) + 1 if self.controls else 0)
        self.end.insertWidget(max(0, pos), w)
        self._balance()
        return w

    def _balance(self):
        w = max(self._left.sizeHint().width(), self._right.sizeHint().width())
        self._left.setMinimumWidth(w)
        self._right.setMinimumWidth(w)

    def showEvent(self, e):
        self._balance()
        super().showEvent(e)

    def refresh_icons(self):
        for b in self.findChildren(IconButton):
            b.refresh_icon()

    def _toggle_max(self):
        w = self._window
        w.showNormal() if w.isMaximized() else w.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()


class Toast(QFrame):
    """Всплывающее уведомление внизу окна (Adw.Toast), с необязательной кнопкой."""

    def __init__(self, parent, text, button=None, on_button=None, timeout=4000):
        super().__init__(parent)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 10 if button else 18, 8)
        lay.setSpacing(8)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        if button:
            b = QPushButton(button)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda: (on_button and on_button(), self.dismiss()))
            lay.addWidget(b)
        self.setMaximumWidth(520)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        QTimer.singleShot(timeout, self.dismiss)

    def show_in(self):
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def reposition(self):
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 24)

    def dismiss(self):
        if not self.isVisible():
            return
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


class FlowLayout(QLayout):
    """Раскладка «потоком» с одинаковыми ячейками (как Gtk.FlowBox homogeneous)."""

    def __init__(self, parent=None, spacing=12, margin=12):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        visible = [it for it in self._items if not it.widget() or it.widget().isVisibleTo(self.parentWidget())]
        if not visible:
            return m.top() + m.bottom()
        cell_w = max(it.sizeHint().width() for it in visible)
        cols = max(1, (r.width() + self._spacing) // (cell_w + self._spacing))
        # Растягиваем промежутки, чтобы ряд заполнял ширину
        extra = r.width() - cols * cell_w
        gap = extra / (cols - 1) if cols > 1 else 0
        gap = min(gap, cell_w * 0.6) if cols > 1 else 0
        x0 = r.x() + (r.width() - (cols * cell_w + (cols - 1) * gap)) / 2 if cols > 1 else r.x()
        y = r.y()
        row_h = 0
        for i, it in enumerate(visible):
            col = i % cols
            if col == 0 and i:
                y += row_h + self._spacing
                row_h = 0
            h = it.heightForWidth(cell_w) if it.hasHeightForWidth() else it.sizeHint().height()
            if not test_only:
                it.setGeometry(QRect(int(x0 + col * (cell_w + gap)), y, cell_w, h))
            row_h = max(row_h, h)
        return y + row_h - rect.y() + m.bottom()


class Badge(QLabel):
    """Метка поверх обложки: «42%», «Новая», «✓»."""

    def __init__(self, parent, color=None):
        super().__init__(parent)
        self._bg = color or QColor(0, 0, 0, 166)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: white; font-size: 8pt; font-weight: bold; padding: 2px 8px;")

    def set_bg(self, color):
        self._bg = QColor(color)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._bg)
        r = self.rect()
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()
        super().paintEvent(e)


class IconBadge(Badge):
    def __init__(self, parent, icon_name, tooltip=""):
        super().__init__(parent)
        self._icon_name = icon_name
        self.setToolTip(tooltip)
        self.setFixedSize(26, 22)
        self.refresh_icon()

    def refresh_icon(self):
        self.setPixmap(style.icon(self._icon_name, "#ffffff", 14).pixmap(14, 14))


class Cover(QWidget):
    """Обложка со скруглёнными углами; без картинки — название на цветном фоне."""

    W, H = 132, 192

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self._pix: QPixmap | None = None
        self._text = ""
        self._progress: float | None = None

    def set_cover(self, path, text):
        self._pix = QPixmap(str(path)) if path else None
        if self._pix is not None and self._pix.isNull():
            self._pix = None
        self._text = text
        self.update()

    def set_progress(self, fraction):
        self._progress = fraction
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 8, 8)
        p.setClipPath(path)
        if self._pix:
            scaled = self._pix.scaled(self.size() * self.devicePixelRatioF(),
                                      Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(self.devicePixelRatioF())
            sw = scaled.width() / scaled.devicePixelRatio()
            sh = scaled.height() / scaled.devicePixelRatio()
            p.drawPixmap(QPoint(int((self.width() - sw) / 2), int((self.height() - sh) / 2)), scaled)
        else:
            p.fillRect(self.rect(), QColor(53, 132, 228, 46))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.setPen(style.solid_fg())
            p.drawText(self.rect().adjusted(12, 12, -12, -12),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._text)
        if self._progress is not None:
            r = QRect(8, self.height() - 14, self.width() - 16, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(r, 3, 3)
            p.setBrush(QColor(style.ACCENT))
            p.drawRoundedRect(QRect(r.x(), r.y(), max(6, int(r.width() * self._progress)), r.height()), 3, 3)
        p.end()


class BookCard(QFrame):
    """Карточка книги в сетке библиотеки."""

    activated = Signal(str)
    menu_requested = Signal(str, QPoint)

    def __init__(self, book_id):
        super().__init__()
        self.book_id = book_id
        self.setObjectName("bookcard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(Cover.W + 24)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        self.cover = Cover()
        lay.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label("", wrap=True, align=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.title.setObjectName("booktitle")
        self.author = label("", "dim", "caption", align=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.title)
        lay.addWidget(self.author)
        lay.addStretch()

        self.badge = Badge(self.cover)
        self.cloud = IconBadge(self.cover, "folder-download", "Не скачана — нажмите, чтобы скачать")
        self.cloud.move(6, 6)
        self.audio = IconBadge(self.cover, "audio-headphones", "Аудиокнига")
        self.audio.move(Cover.W - 32, Cover.H - 28)

        self._press_timer = QTimer(self, singleShot=True, interval=550)
        self._press_timer.timeout.connect(self._long_press)
        self._long_pressed = False
        self.grabGesture(Qt.GestureType.TapAndHoldGesture)

    def update_book(self, book, lib):
        title = book.get("title") or ""
        fm = self.title.fontMetrics()
        # Не больше двух строк, как в GTK-версии
        elided = title
        if fm.boundingRect(QRect(0, 0, Cover.W, 1000), Qt.TextFlag.TextWordWrap, title).height() > fm.lineSpacing() * 2 + 2:
            while elided and fm.boundingRect(QRect(0, 0, Cover.W, 1000), Qt.TextFlag.TextWordWrap,
                                             elided + "…").height() > fm.lineSpacing() * 2 + 2:
                elided = elided[:-1]
            elided = elided.rstrip() + "…"
        self.title.setText(elided)
        self.title.setToolTip(title if elided != title else "")
        authors = ", ".join(book.get("authors") or [])
        self.author.setText(self.author.fontMetrics().elidedText(authors, Qt.TextElideMode.ElideRight, Cover.W))
        self.cover.set_cover(lib.cover_path(book), title)

        downloaded = lib.file_path(book) is not None
        status = lib.status(book)
        self.badge.set_bg(QColor(0, 0, 0, 166))
        self.badge.setToolTip("")
        if status == "finished":
            self.badge.setText("✓")
            self.badge.setToolTip("Прочитано")
            self.badge.set_bg(QColor(38, 162, 105, 230))
        elif status == "reading":
            pct = lib.percent(book)
            self.badge.setText(f"{pct}%" if pct else "Читаю")
        else:
            self.badge.setText("Новая")
        self.badge.adjustSize()
        self.badge.move(Cover.W - self.badge.width() - 6, 6)
        self.badge.setVisible(downloaded or status != "unread")
        self.cloud.setVisible(not downloaded)
        self.audio.setVisible(bool(book.get("is_audio")))

    def set_download_progress(self, fraction):
        self.cover.set_progress(None if fraction is None else max(0.02, fraction))

    def refresh_icons(self):
        self.cloud.refresh_icon()
        self.audio.refresh_icon()

    # --- нажатия: короткое — открыть, долгое или правая кнопка — меню

    def mousePressEvent(self, e):
        self._long_pressed = False
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_timer.start()
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(self.book_id, e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self._press_timer.stop()
        if e.button() == Qt.MouseButton.LeftButton and not self._long_pressed \
                and self.rect().contains(e.position().toPoint()):
            self.activated.emit(self.book_id)

    def _long_press(self):
        self._long_pressed = True
        self.menu_requested.emit(self.book_id, self.mapToGlobal(self.rect().center()))

    def event(self, e):
        if e.type() == e.Type.Gesture:
            g = e.gesture(Qt.GestureType.TapAndHoldGesture)
            if g and g.state() == Qt.GestureState.GestureFinished:
                self._long_press()
                return True
        return super().event(e)


class Switch(QAbstractButton):
    """Переключатель как в GNOME (Gtk.Switch)."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 26)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        off = QColor(255, 255, 255, 38) if style.is_dark() else QColor(0, 0, 6, 38)
        on = QColor(style.ACCENT)
        bg = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
            int(off.alpha() + (255 - off.alpha()) * self._pos))
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), 13, 13)
        p.setBrush(QColor("#ffffff"))
        x = 3 + (self.width() - 26) * self._pos
        p.drawEllipse(int(x), 3, 20, 20)
        p.end()

    def sizeHint(self):
        return QSize(48, 26)


class Popover(QFrame):
    """Всплывающая панель под кнопкой (Gtk.Popover)."""

    def __init__(self, content: QWidget):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("popover")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.addWidget(content)
        outer.addWidget(frame)

    def popup_under(self, button: QWidget):
        self.adjustSize()
        g = button.mapToGlobal(QPoint(button.width() // 2, button.height() + 4))
        x = g.x() - self.width() // 2
        screen = button.screen().availableGeometry()
        x = max(screen.left() + 4, min(x, screen.right() - self.width() - 4))
        self.move(x, g.y())
        self.show()


def attach_popover(button: QToolButton, popover: Popover):
    button.clicked.connect(lambda: popover.popup_under(button))
    return popover
