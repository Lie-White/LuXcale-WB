"""Buttons built to docs/UI-RULES.md: every button is an action, a toggle or the primary action."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy, QSplitter, QSplitterHandle

from imquant.ui import i18n, theme

ROLES = ("action", "toggle", "primary")


def button(role: str, key: str | None = None, text: str | None = None, tooltip: str | None = None) -> QPushButton:
    """`key` is an i18n key (text follows the language); `text` is fixed text."""
    if role not in ROLES:
        raise ValueError(f"unknown button role {role!r}")
    b = QPushButton()
    b.setProperty("role", role)
    b.setCheckable(role == "toggle")
    b.setCursor(b.cursor().shape().PointingHandCursor)
    b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    b.setMinimumHeight(30)
    if key:
        i18n.bind(b, key)
    elif text is not None:
        b.setText(text)
    if tooltip:
        b.setToolTip(tooltip)
    return b


class _GripHandle(QSplitterHandle):
    """A splitter handle you can see: a line with three grip dots, accent coloured while the
    mouse is over it or dragging it (docs/PLAN.md §4-16)."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.hot = False
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        self.hot = True
        self.update()

    def leaveEvent(self, event) -> None:
        self.hot = False
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        color = QColor(theme.ACCENT if self.hot else theme.BORDER_STRONG)
        w, h = self.width(), self.height()
        p.setPen(QPen(color, 2 if self.hot else 1))
        if self.orientation() == Qt.Orientation.Vertical:  # a horizontal line between stacked panels
            p.drawLine(QPointF(4, h / 2), QPointF(w - 4, h / 2))
            dots = [QPointF(w / 2 + dx, h / 2) for dx in (-8, 0, 8)]
        else:
            p.drawLine(QPointF(w / 2, 4), QPointF(w / 2, h - 4))
            dots = [QPointF(w / 2, h / 2 + dy) for dy in (-8, 0, 8)]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT if self.hot else theme.TEXT_MUTED))
        for d in dots:
            p.drawEllipse(d, 2.2, 2.2)


class Splitter(QSplitter):
    """QSplitter whose handles are visible and light up under the mouse."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setHandleWidth(10)

    def createHandle(self) -> QSplitterHandle:
        return _GripHandle(self.orientation(), self)
