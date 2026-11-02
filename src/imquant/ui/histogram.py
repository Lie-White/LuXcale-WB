"""A log histogram with two draggable handles for a display range: the confocal channel cards and
the WB window's brightness (docs/PLAN.md §4-63). Only the screen changes; numbers never use it."""

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from imquant.ui import theme

BINS = 256


def channel_histogram(proj_channel: np.ndarray, valid: np.ndarray, top: float) -> tuple[np.ndarray, np.ndarray]:
    """Counts and bin edges over [0, top + 1) in 256 bins, valid pixels only."""
    return np.histogram(proj_channel[valid], bins=BINS, range=(0.0, float(top) + 1.0))


class HistogramStrip(QWidget):
    rangeChanged = Signal(float, float)

    def __init__(self, color: str, parent=None, inverted: bool = False):
        super().__init__(parent)
        self.color = QColor(color)
        self.inverted = inverted  # low values shown light, high dark (a WB blot): the ramp falls
        self.counts = np.zeros(BINS)
        self.top = 4095.0
        self.black, self.white = 0.0, 4095.0
        self._grab: str | None = None
        self.setMinimumHeight(44)
        self.setMouseTracking(True)

    def set_data(self, counts: np.ndarray, top: float) -> None:
        self.counts, self.top = counts, top
        self.update()

    def set_range(self, black: float, white: float) -> None:
        self.black, self.white = black, white
        self.update()

    def _x(self, value: float) -> float:
        return 4 + (self.width() - 8) * min(max(value / self.top, 0.0), 1.0)

    def _value(self, x: float) -> float:
        return round(min(max((x - 4) / (self.width() - 8), 0.0), 1.0) * self.top)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        logc = np.log1p(self.counts.astype(np.float64))
        if logc.max() > 0:
            logc = logc / logc.max()
            path = QPainterPath(QPointF(4, h - 2))
            for i, v in enumerate(logc):
                path.lineTo(QPointF(4 + (w - 8) * i / (BINS - 1), h - 2 - (h - 8) * v))
            path.lineTo(QPointF(w - 4, h - 2))
            fill = QColor(self.color)
            fill.setAlpha(110)
            p.fillPath(path, fill)
        # The display ramp from the lower handle to the upper one.
        p.setPen(QPen(QColor(theme.TEXT_STRONG), 1))
        bx, wx = self._x(self.black), self._x(self.white)
        low, high = (4, h - 2) if self.inverted else (h - 2, 4)
        p.drawLine(QPointF(bx, low), QPointF(wx, high))
        for x in (bx, wx):
            p.setPen(QPen(QColor(theme.TEXT_STRONG), 2))
            p.drawLine(QPointF(x, 2), QPointF(x, h - 2))
        p.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
        p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))

    def mousePressEvent(self, event) -> None:
        x = event.position().x()
        self._grab = "black" if abs(x - self._x(self.black)) <= abs(x - self._x(self.white)) else "white"
        self._move(x)

    def mouseMoveEvent(self, event) -> None:
        if self._grab:
            self._move(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._grab = None

    def _move(self, x: float) -> None:
        v = self._value(x)
        if self._grab == "black":
            self.black = min(v, self.white - 1)
        else:
            self.white = max(v, self.black + 1)
        self.update()
        self.rangeChanged.emit(self.black, self.white)
