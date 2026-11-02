"""The Western blot window (docs/PLAN.md §4-22, §4-24): open raw blots, set lanes and one or
more band windows on each, name the samples once, and read target ÷ loading control per lane
(engine: imquant.wb). The loading control is a band, so it may sit on the target's own blot."""

from dataclasses import asdict, replace
from datetime import datetime
import csv
import json
from pathlib import Path
import re

import numpy as np
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QAbstractSpinBox, QApplication, QDialog, QFormLayout, QListWidgetItem, QMainWindow, QMessageBox, QStyle, QStyleOptionSpinBox,
    QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from imquant import __version__, wb, wbfigure, wbstats, xlsx
from imquant.graphs import GraphStyle, dot_bar, preview
from imquant.recommend import candidate_statistics, recommendations
from imquant.ui import i18n, widgets
from imquant.ui.style_dialog import style_dialog

LANE = QColor(0, 170, 220)
SPLIT = QColor(230, 120, 0)
MARK = QColor(200, 0, 160)  # ladder marks (§4-37)
RESULT_COLUMNS = ("lane", "sample", "group", "replicate", "target", "loading", "ratio", "relative")


GRAB = 6  # widget px: how close the mouse must be to a line or edge to grab it
AXIS_LOCK = 5  # widget px a drag inside a lane moves before its axis (lanes or window) is fixed
LANE_KINDS = ("first", "last", "all")


class _BlotView(QWidget):
    """The blot with its lane boxes and band windows, which the mouse can drag (docs/PLAN.md
    §4-23, §4-24): first/last lane (ends), a middle lane (all), lane edges (width), a window's
    top, bottom and split lines. Dragging inside a lane moves the lanes sideways or that window
    up and down, whichever way the first 5 px went. A window with its own lanes (§4-51) is
    dragged alone. Elsewhere it pans; the wheel zooms at the cursor; double click fits. Arrow keys
    move the last thing clicked by 1 px (Shift: 10).
    While dragging only the boxes are redrawn; on release `committed(lanes, windows, k)` is called."""

    def __init__(self, committed, fit_clicked=None):
        super().__init__()
        self.committed = committed
        self.fit_clicked = fit_clicked  # while "Fit to a band" is on, a click goes here (§4-25)
        self.fit_mode = False
        self.points_clicked = None  # while set, clicks are collected for levelling (§4-27)
        self.points: list[tuple[float, float]] = []
        # Ladder marks (§4-37, §4-59): Ctrl+click adds one, a drag moves it, a right click removes
        # it, a double click edits its kDa; each callback gets the mark's index or position.
        self.mark_added = self.mark_moved = self.mark_removed = self.mark_edit = None
        self.marker: QImage | None = None  # the colour Marker picture, shown instead of the blot
        self.marks: list = []  # ladder marks [x, y, kDa] of the shown blot
        self.grey: np.ndarray | None = None
        self.key = None  # which blot is shown: a new one is fitted, a new contrast is not
        self.image: QImage | None = None
        self.lanes: wb.Lanes | None = None
        self.windows: list[wb.Window] = []
        self.selected = 0
        self.zoom = 1.0
        self.centre = (0.0, 0.0)
        self.drag: dict | None = None
        self.last: tuple | None = None  # what the arrow keys move
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumWidth(300)

    def show_blot(self, grey: np.ndarray | None, lanes=None, windows=(), selected: int = 0, key=None) -> None:
        if grey is not self.grey:
            self.grey = grey
            self.image = None if grey is None else QImage(grey.data, grey.shape[1], grey.shape[0], grey.shape[1],
                                                          QImage.Format.Format_Grayscale8).copy()
        if key != self.key:
            self.key = key
            self.last = None
            self.fit()
        self.lanes, self.windows, self.selected = lanes, list(windows), selected
        self.update()

    def fit(self) -> None:
        self.zoom = 1.0
        if self.grey is not None:
            self.centre = (self.grey.shape[1] / 2, self.grey.shape[0] / 2)
        self.update()

    def scale(self) -> float:
        h, w = self.grey.shape
        return min(self.width() / w, self.height() / h) * self.zoom

    def to_widget(self, x: float, y: float) -> tuple[float, float]:
        s = self.scale()
        return (x - self.centre[0]) * s + self.width() / 2, (y - self.centre[1]) * s + self.height() / 2

    def to_image(self, wx: float, wy: float) -> tuple[float, float]:
        s = self.scale()
        return (wx - self.width() / 2) / s + self.centre[0], (wy - self.height() / 2) / s + self.centre[1]

    # ---- drawing ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 255, 255))
        if self.image is None:
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, i18n.tr("wb.empty"))
            return
        s = self.scale()
        x0, y0 = self.to_widget(0, 0)
        painter.translate(x0, y0)
        painter.scale(s, s)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 2)
        painter.drawImage(0, 0, self.marker if self.marker is not None else self.image)
        mark_pen = QPen(MARK, 2)
        mark_pen.setCosmetic(True)
        painter.setPen(mark_pen)
        for x, y, _ in self.marks:
            painter.drawLine(int(x - 25), int(y), int(x + 25), int(y))
        if self.lanes is None:
            return
        for k, w in enumerate(self.windows):
            lanes = self.lanes_of(k)
            lane_pen = QPen(LANE, 2.5 if k == self.selected else 1.2)
            lane_pen.setCosmetic(True)
            painter.setPen(lane_pen)
            for i in range(lanes.count):
                a, b = lanes.columns(i)
                painter.drawRect(a, w.top, b - a, w.bottom - w.top)
            split_pen = QPen(SPLIT, 1.5)
            split_pen.setCosmetic(True)
            painter.setPen(split_pen)
            left, right = self.span(k)
            for y in w.splits:
                painter.drawLine(left, y, right, y)
        painter.resetTransform()
        painter.setPen(MARK)
        for x, y, kda in self.marks:
            px, py = self.to_widget(x - 25, y)
            painter.drawText(int(px) - 40, int(py) - 6, 36, 14, Qt.AlignmentFlag.AlignRight, f"{kda}" if kda else "?")
        painter.setPen(LANE)
        for k, w in enumerate(self.windows):
            px, py = self.to_widget(self.span(k)[1], w.top)
            painter.drawText(int(px) + 4, int(py) + 12, ", ".join(w.names))
        if self.windows:
            k = min(range(len(self.windows)), key=lambda j: self.windows[j].top)
            for i in range(self.lanes.count):
                px, py = self.to_widget(self.lanes_of(k).columns(i)[0], self.windows[k].top)
                painter.drawText(int(px) + 2, int(py) - 4, str(i + 1))

    def lanes_of(self, k: int) -> wb.Lanes:
        """Window k's lane boxes: its own (§4-51), else the blot's."""
        return self.windows[k].lanes or self.lanes

    def span(self, k: int) -> tuple[int, int]:
        """Window k's columns from its first lane's left edge to its last lane's right edge."""
        lanes = self.lanes_of(k)
        return lanes.columns(0)[0], lanes.columns(lanes.count - 1)[1]

    # ---- mouse ----

    def hit(self, wx: float, wy: float) -> tuple:
        """What the mouse at widget (wx, wy) would grab, nearest kind first; every kind but
        "pan" ends with the index of its window."""
        if self.lanes is None or not self.windows:
            return ("pan",)
        x, y = self.to_image(wx, wy)
        s = self.scale()

        def across(k: int) -> bool:
            left, right = self.span(k)
            return left - GRAB / s <= x <= right + GRAB / s

        order = [self.selected] + [k for k in range(len(self.windows)) if k != self.selected]
        for k in order:
            for j, row in enumerate(self.windows[k].splits):
                if across(k) and abs(y - row) * s <= GRAB:
                    return ("split", j, k)
        for k in order:
            w = self.windows[k]
            for kind, row in (("top", w.top), ("bottom", w.bottom)):
                if across(k) and abs(y - row) * s <= GRAB:
                    return (kind, k)
        for k in order:
            w, lanes = self.windows[k], self.lanes_of(k)
            if not w.top <= y <= w.bottom:
                continue
            for i in range(lanes.count):
                a, b = lanes.columns(i)
                for side, edge in ((-1, a), (1, b)):
                    if abs(x - edge) * s <= GRAB:
                        return ("edge", side, k)
            for i in range(lanes.count):
                a, b = lanes.columns(i)
                if a <= x < b:
                    if lanes.count == 1:
                        return ("all", k)
                    return ("first", k) if i == 0 else ("last", k) if i == lanes.count - 1 else ("all", k)
        return ("pan",)

    CURSORS = {"split": Qt.CursorShape.SplitVCursor, "top": Qt.CursorShape.SizeVerCursor,
               "bottom": Qt.CursorShape.SizeVerCursor, "edge": Qt.CursorShape.SizeHorCursor,
               "first": Qt.CursorShape.SizeAllCursor, "last": Qt.CursorShape.SizeAllCursor,
               "all": Qt.CursorShape.SizeAllCursor, "pan": Qt.CursorShape.OpenHandCursor}

    def hit_mark(self, wx: float, wy: float) -> int | None:
        """The ladder mark whose line is under widget (wx, wy)."""
        s = self.scale()
        for i, (x, y, _) in enumerate(self.marks):
            px, py = self.to_widget(x, y)
            if abs(wy - py) <= GRAB and abs(wx - px) <= 25 * s + GRAB:
                return i
        return None

    def mousePressEvent(self, event) -> None:
        if self.image is None:
            return
        p = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            i = self.hit_mark(p.x(), p.y())
            if i is not None and self.mark_removed is not None:
                self.mark_removed(i)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        if self.fit_mode and self.fit_clicked is not None:
            self.fit_clicked(*self.to_image(p.x(), p.y()))
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and self.mark_added is not None:
            self.mark_added(*self.to_image(p.x(), p.y()))
            return
        i = self.hit_mark(p.x(), p.y()) if self.points_clicked is None else None
        if i is not None:
            self.drag = {"what": ("mark", i), "start": (p.x(), p.y()), "mark": list(self.marks[i])}
            return
        if self.points_clicked is not None:
            self.points.append(self.to_image(p.x(), p.y()))
            if len(self.points) == 2:
                done, self.points = self.points, []
                self.points_clicked(*done)
            self.update()
            return
        what = self.hit(p.x(), p.y())
        if what[0] != "pan":
            self.last = what
            if what[-1] != self.selected:
                self.selected = what[-1]
                self.committed(self.lanes, self.windows, self.selected)
        self.drag = {"what": what, "start": (p.x(), p.y()), "lanes": self.lanes, "windows": list(self.windows),
                     "centre": self.centre, "axis": None}

    def mouseMoveEvent(self, event) -> None:
        if self.image is None:
            return
        p = event.position()
        if self.drag is None:
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                self.setCursor(Qt.CursorShape.CrossCursor)  # Ctrl+click adds a mark
            elif self.hit_mark(p.x(), p.y()) is not None:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(self.CURSORS[self.hit(p.x(), p.y())[0]])
            return
        d = self.drag
        wdx, wdy = p.x() - d["start"][0], p.y() - d["start"][1]
        s = self.scale()
        dx, dy = wdx / s, wdy / s
        what = d["what"]
        if what[0] == "mark":
            self.marks[what[1]] = [d["mark"][0] + dx, d["mark"][1] + dy, d["mark"][2]]
            self.update()
            return
        if what[0] == "pan":
            self.centre = (d["centre"][0] - dx, d["centre"][1] - dy)
            self.update()
            return
        if what[0] in LANE_KINDS:
            if d["axis"] is None:
                if max(abs(wdx), abs(wdy)) < AXIS_LOCK:
                    return
                d["axis"] = "x" if abs(wdx) >= abs(wdy) else "y"
            if d["axis"] == "y":
                what = ("move", what[-1])
        try:
            self.lanes, self.windows = self._moved(what, d["lanes"], d["windows"], dx, dy)
        except ValueError:
            return  # an invalid shape: keep the last valid one
        self.update()

    def _moved(self, what, lanes, windows, dx, dy):
        """New (lanes, windows) after moving `what` by (dx, dy) image px; ValueError if invalid.
        The lanes moved are window k's: the blot's when it has one window, else that window's own
        (§4-51), dropped again when they come back to the blot's."""
        h, w = self.grey.shape
        kind, k = what[0], what[-1]
        n = lambda v: int(round(v))  # noqa: E731
        win = windows[k]
        own = win.lanes or lanes
        first, last, width = own.first, own.last, own.width
        shifts, widths = list(own.shifts), list(own.widths)
        top, bottom, splits = win.top, win.bottom, list(win.splits)
        if kind == "first":
            first = n(first + dx)
        elif kind == "last":
            last = n(last + dx)
        elif kind == "all":
            first, last = n(first + dx), n(last + dx)
        elif kind == "edge":
            width = n(width + 2 * dx * what[1])
            widths = [n(v + 2 * dx * what[1]) for v in widths]
        elif kind == "top":
            top = n(top + dy)
        elif kind == "bottom":
            bottom = n(bottom + dy)
        elif kind == "split":
            splits[what[1]] = n(splits[what[1]] + dy)
        elif kind == "move":
            step = n(dy)
            top, bottom, splits = top + step, bottom + step, [s + step for s in splits]
        new_lanes = wb.Lanes(own.count, first, last, width, shifts, widths)
        if min([width] + widths) < 2 or (own.count > 1 and first >= last) or splits != sorted(splits):
            raise ValueError("invalid lanes")
        boxes = [new_lanes.columns(i) for i in range(own.count)]
        if any(a[1] > b[0] for a, b in zip(boxes, boxes[1:])):
            raise ValueError("lanes overlap")
        if boxes[0][0] < 0 or boxes[-1][1] > w or top < 0 or bottom > h:
            raise ValueError("off the image")
        if len(windows) == 1:
            return new_lanes, [wb.Window(list(win.names), top, bottom, splits)]
        new_window = wb.Window(list(win.names), top, bottom, splits, None if new_lanes == lanes else new_lanes)
        return lanes, [new_window if j == k else other for j, other in enumerate(windows)]

    def mouseReleaseEvent(self, event) -> None:
        if self.drag is None:
            return
        d, self.drag = self.drag, None
        if d["what"][0] == "mark":
            i = d["what"][1]
            if self.marks[i] != d["mark"] and self.mark_moved is not None:
                self.mark_moved(i, *self.marks[i][:2])
            return
        if d["what"][0] != "pan" and (self.lanes != d["lanes"] or self.windows != d["windows"]):
            self.committed(self.lanes, self.windows, self.selected)

    def keyPressEvent(self, event) -> None:
        """Arrows move the last thing clicked by 1 image px, Shift+arrows by 10."""
        if event.key() == Qt.Key.Key_Control and self.image is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() not in arrows or self.last is None or self.lanes is None:
            return super().keyPressEvent(event)
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        dx, dy = (v * step for v in arrows[event.key()])
        what = self.last
        if what[0] in LANE_KINDS and dy:
            what = ("move", what[-1])  # up/down on a lane moves its window, as a vertical drag does
        if (what[0] in ("top", "bottom", "split", "move") and not dy) or (what[0] in LANE_KINDS + ("edge",) and not dx):
            return
        try:
            self.lanes, self.windows = self._moved(what, self.lanes, self.windows, dx, dy)
        except ValueError:
            return
        self.update()
        self.committed(self.lanes, self.windows, self.selected)

    def mouseDoubleClickEvent(self, event) -> None:
        p = event.position()
        i = self.hit_mark(p.x(), p.y())
        if i is not None and self.mark_edit is not None:
            self.mark_edit(i)
            return
        self.fit()

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Control:
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if self.image is None:
            return
        p = event.position()
        x, y = self.to_image(p.x(), p.y())
        self.zoom = float(np.clip(self.zoom * 1.25 ** (event.angleDelta().y() / 120), 1.0, 40.0))
        s = self.scale()
        self.centre = (x - (p.x() - self.width() / 2) / s, y - (p.y() - self.height() / 2) / s)
        self.update()


# The measurement's warnings are English (they are saved with the results); on screen they are
# shown in the window's language (§4-46). An experiment's name may lead a warning ("2: …").
WARNINGS = [
    (re.compile(r"Loading control from a different gel: assumes the same amount was loaded on each gel"), "wb.warn.gel"),
    (re.compile(r"Saturated pixels in lanes (?P<lanes>.+): those values are underestimated"), "wb.warn.saturated"),
    (re.compile(r"Lane widths differ on (?P<blot>.+): check each box covers its whole band"), "wb.warn.widths"),
    (re.compile(r"pick its target band and loading control again \(left out\)"), "wb.warn.left_out"),
]


def warning_text(w: str) -> str:
    """One measurement warning in the window's language; unknown ones as they are."""
    for pattern, key in WARNINGS:
        m = pattern.fullmatch(w)
        if m:
            return i18n.tr(key, **m.groupdict())
    head, sep, rest = w.partition(": ")
    if sep and rest != w:
        said = warning_text(rest)
        if said != rest:
            return f"{head}: {said}"
    return w


def marker_image(path: Path) -> Path | None:
    """The imager's colour Marker picture next to a raw `…_Ch.tif`: `…_Ch+Marker.jpg` (marker and
    bands, easiest to read), else `…_Ch-Marker.jpg`; None if there is none."""
    path = Path(path)
    for suffix in ("+Marker.jpg", "-Marker.jpg"):
        candidate = path.with_name(path.stem + suffix)
        if candidate.exists():
            return candidate
    return None


class _Blot:
    """One opened blot: its lanes and one or more band windows, each of which may have its own
    lanes (§4-51; the lane count is the blot's)."""

    def __init__(self, path: Path, blot: wb.Blot):
        self.path, self.blot = path, blot
        # The blot's tilt (§4-43): `blot` is the raw image turned by `angle`; screen, fit and
        # numbers all use it, so lanes and windows are its rows and columns. `raw` stays as read.
        self.raw, self.angle = blot, 0.0
        h, w = blot.image.shape
        # "251103 HEK actin 2025.11.03_10.20.30_Ch" -> "HEK actin": no leading date, no imager time stamp
        words = (path.parent.name or path.stem).split(" 20")[0].split()
        dated = len(words) > 1 and words[0].isdigit() and len(words[0]) == 6
        self.name = " ".join(words[1:] if dated else words)
        self.base_name = self.name  # the name made from the folder, before any date is added (§4-39)
        self.date = words[0] if dated else ""
        shot = re.search(r" 20\d\d\.\d\d\.\d\d_(\d\d)\.(\d\d)", path.parent.name or path.stem)
        self.time = f"{shot[1]}:{shot[2]}" if shot else ""  # the imager's time stamp, when the name has it (§4-40)
        self.same_gel = False
        self.lanes = wb.Lanes(6, round(w * .3), round(w * .7), 40)
        self.windows = [wb.Window(["band"], h // 2 - 30, h // 2 + 30)]
        self.selected = 0
        # Per window, same order (§4-29): figure label, kDa and angle (None = auto-level from
        # that window); the whole turn from the raw image, not on top of the tilt.
        # lo/hi (§4-30): the strip's own white and black raw values, None = follow the screen.
        self.figure: list[dict] = [{"label": "", "kda": "", "angle": None, "lo": None, "hi": None}]
        self.ladder: list[list] = []  # [x, y, kDa text] in raw pixels (§4-37)
        self.marker_path = marker_image(path)
        self._marker: QImage | None = None
        self._turned_marker: tuple | None = None  # (angle, picture turned by it)
        self.set_display(0.0, blot.saturation)  # the whole raw range, as a picture viewer shows it (§4-59)

    def marker(self) -> QImage | None:
        """The colour Marker picture (same pixel grid as the raw image, §4-37), loaded once and
        turned with the blot's tilt."""
        if self._marker is None and self.marker_path is not None:
            image = QImage(str(self.marker_path))
            if not image.isNull() and (image.height(), image.width()) == self.raw.image.shape:
                self._marker = image.convertToFormat(QImage.Format.Format_RGB32)
        if self._marker is None or not self.angle:
            return self._marker
        if self._turned_marker is None or self._turned_marker[0] != self.angle:
            h, w = self.raw.image.shape
            bits = np.frombuffer(self._marker.constBits(), np.uint8).reshape(h, self._marker.bytesPerLine())
            rgb = bits[:, :4 * w].reshape(h, w, 4)
            out = np.stack([np.clip(np.round(wb.rotate(rgb[..., c], self.angle)), 0, 255).astype(np.uint8)
                            if c < 3 else rgb[..., c] for c in range(4)], axis=2)
            out = np.ascontiguousarray(out)
            self._turned_marker = (self.angle, QImage(out.data, w, h, 4 * w, QImage.Format.Format_RGB32).copy())
        return self._turned_marker[1]

    def turn(self, angle: float) -> None:
        """Level the blot by `angle` degrees (§4-43); 0 = the raw image as it is."""
        self.angle = round(float(angle), 2)
        self.blot = wb.turned(self.raw, self.angle)
        self.set_display(*self.display)

    def to_raw(self, points) -> np.ndarray:
        """Shown (turned) (x, y) points as raw image points."""
        return wbfigure.rotate_points(points, -self.angle, self.raw.image.shape)

    def from_raw(self, points) -> np.ndarray:
        """Raw (x, y) points (ladder marks) where they show on the turned blot."""
        return wbfigure.rotate_points(points, self.angle, self.raw.image.shape)

    def auto_range(self) -> tuple[float, float]:
        """The 1st and 99.5th percentiles of the (turned) blot: "Auto" on screen, and a figure
        strip's contrast until it gets its own (§4-59)."""
        if getattr(self, "_auto", (None,))[0] != self.angle:
            lo, hi = np.percentile(self.blot.image, (1, 99.5))
            self._auto = (self.angle, (float(lo), float(hi)))
        return self._auto[1]

    def auto_display(self) -> None:
        self.set_display(*self.auto_range())

    def set_display(self, lo: float, hi: float) -> None:
        """Display contrast only (docs/PLAN.md §4-24 MB9): raw `lo` shows white, `hi` black.
        The numbers always come from the raw image."""
        self.display = (lo, hi)
        shown = 255 * (1 - np.clip((self.blot.image - lo) / max(hi - lo, 1e-9), 0, 1))  # bands dark
        self.grey = np.ascontiguousarray(shown.astype(np.uint8))

    @property
    def window(self) -> wb.Window:
        return self.windows[self.selected]

    @window.setter
    def window(self, value: wb.Window) -> None:
        self.windows[self.selected] = value

    def lanes_of(self, k: int | None = None) -> wb.Lanes:
        """Window k's lanes (the picked window by default): its own, else the blot's."""
        return self.windows[self.selected if k is None else k].lanes or self.lanes

    def set_lanes(self, lanes: wb.Lanes) -> None:
        """New lanes for the picked window: the blot's when it has one window, else that window's
        own (none when they equal the blot's). A new lane count is every window's (one sample table)."""
        if len(self.windows) == 1:
            self.lanes, self.windows[0] = lanes, replace(self.windows[0], lanes=None)
            return
        if lanes.count != self.lanes.count:
            self.lanes = replace(self.lanes, count=lanes.count, shifts=[], widths=[])
            self.windows = [w if w.lanes is None else replace(w, lanes=replace(w.lanes, count=lanes.count, shifts=[],
                                                                                widths=[])) for w in self.windows]
        self.window = replace(self.window, lanes=None if lanes == self.lanes else lanes)

    def bands(self) -> list[str]:
        """Every band this blot gives: each window's bands, and its total when it has several."""
        return [name for w in self.windows for name in w.names + ([w.total_name] if len(w.names) > 1 else [])]

    def settings(self) -> dict:
        return {"path": str(self.path), "name": self.name, "same_gel": self.same_gel, "angle": self.angle,
                "lanes": asdict(self.lanes),  # a window's "lanes" only when it has its own (§4-51)
                "windows": [{k: v for k, v in asdict(w).items() if k != "lanes" or v} for w in self.windows],
                "ladder": [list(m) for m in self.ladder]}


class WBWindow(QMainWindow):
    def __init__(self, results_root, settings_path=None):
        super().__init__()
        self.results_root = results_root  # a function: the results folder (docs/PLAN.md §4-20)
        # A function: the project's settings.json, where the last chosen save folder is kept
        # ("wb_dir", §4-35); None keeps it for this window only.
        self.settings_path = settings_path
        self._wb_dir: Path | None = None
        self._style = GraphStyle()  # used when there is no settings file
        self._layout = wbfigure.FigureLayout()
        # Repeated experiments (§4-38): each has its own target, loading control, sample table and
        # reference; the widgets of ③ and ④ show the current one.
        self.experiments: list[dict] = [{"name": "1"}]
        self.exp_index = 0
        self.all_rows: list[dict] = []
        self.saved_to: Path | None = None
        self.blots: list[_Blot] = []
        self.rows: list[dict] = []
        self.warnings: list[str] = []
        self.overlay: dict = {}
        self.graph_png: bytes | None = None
        self.step_boxes: dict[str, QFrame] = {}  # i18n title key -> its box (§4-46)
        self.setWindowTitle(i18n.tr("wb.title"))
        self.resize(1400, 860)
        split = widgets.Splitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_blots())
        self.view = _BlotView(self._dragged, self.fit_at)
        self.view.mark_added, self.view.mark_moved = self.add_ladder_mark, self.move_ladder_mark
        self.view.mark_removed, self.view.mark_edit = self.remove_ladder_mark, self.edit_ladder_mark
        split.addWidget(self.view)
        split.addWidget(self._build_settings())
        split.setSizes([260, 640, 480])
        self.setCentralWidget(split)
        self.saved_label = QLabel()
        self.saved_label.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.saved_label)
        # No number box is squeezed below its widest value (§4-46 UI8): long buttons on the same
        # row would otherwise take the room and hide the digits in a narrow window.
        for spin in self.findChildren(QAbstractSpinBox):
            widest = max((spin.textFromValue(v) for v in (spin.minimum(), spin.maximum())), key=len)
            spin.setMinimumWidth(spin.fontMetrics().horizontalAdvance(widest + spin.suffix()) + 34)
        # The brightness boxes really show their widest value ("65535" from the start, §4-59), so
        # they get the arrows' real width from the style (48 px side by side here, not 34).
        for spin in (self.display_lo, self.display_hi):
            opt = QStyleOptionSpinBox()
            spin.initStyleOption(opt)
            arrows = sum(spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, part, spin).width()
                         for part in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown))
            spin.setMinimumWidth(spin.fontMetrics().horizontalAdvance("65535") + arrows + 16)
        self._load_widgets()
        i18n.on_change(self._retranslate)

    # ---- building ---------------------------------------------------------------------------

    def _build_blots(self) -> QWidget:
        """Left: the blots, how the shown one looks (never the numbers), and its size marks (§4-46)."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        body = self._step(lay, "wb.box_blot")
        row = QHBoxLayout()
        self.open_button = widgets.button("action", "wb.open")
        self.open_button.clicked.connect(self._ask_open)
        self.close_button = widgets.button("action", "wb.close", tooltip=i18n.tr("wb.close.tip"))
        self.close_button.clicked.connect(self.close_blot)
        self.close_all_button = widgets.button("action", "wb.close_all", tooltip=i18n.tr("wb.close_all.tip"))
        self.close_all_button.clicked.connect(lambda: self.close_all())
        row.addWidget(self.open_button, 1)
        row.addWidget(self.close_button)
        row.addWidget(self.close_all_button)
        body.addLayout(row)
        self.blot_list = QListWidget()
        self.blot_list.currentRowChanged.connect(lambda _: self._load_widgets())
        body.addWidget(self.blot_list, 1)
        row = QHBoxLayout()
        name_label = QLabel()
        i18n.bind(name_label, "wb.target_name")
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(lambda: self._set_blot(name=self.name_edit.text().strip()))
        row.addWidget(name_label)
        row.addWidget(self.name_edit, 1)
        body.addLayout(row)
        self.same_gel_box = QCheckBox()
        i18n.bind(self.same_gel_box, "wb.same_gel")
        self.same_gel_box.toggled.connect(lambda on: self._set_blot(same_gel=on))
        body.addWidget(self.same_gel_box)
        lay.setStretch(0, 1)
        body = self._step(lay, "wb.box_view")
        contrast_label = QLabel()
        i18n.bind(contrast_label, "wb.contrast")
        contrast_label.setToolTip(i18n.tr("wb.contrast.tip"))
        body.addWidget(contrast_label)
        row = QHBoxLayout()
        self.display_lo, self.display_hi = QSpinBox(), QSpinBox()
        for spin in (self.display_lo, self.display_hi):
            spin.setRange(0, 65535)
            spin.setSingleStep(100)
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            spin.valueChanged.connect(lambda _: self.set_display(self.display_lo.value(), self.display_hi.value()))
            row.addWidget(spin, 1)
        body.addLayout(row)
        row = QHBoxLayout()  # "Auto" on its own row: the two boxes need their room for "65535" (§4-59)
        self.display_auto = widgets.button("action", "wb.contrast_auto")
        self.display_auto.clicked.connect(self.auto_display)
        self.marker_toggle = widgets.button("toggle", "wb.marker", tooltip=i18n.tr("wb.marker.tip"))
        self.marker_toggle.toggled.connect(lambda _: self._draw())
        row.addWidget(self.display_auto)
        row.addWidget(self.marker_toggle, 1)
        body.addLayout(row)
        # Ladder marks (§4-37): the ladder only shows in the Marker picture, so show it and
        # Ctrl+click each ladder band; marks are dragged, removed and edited on the blot (§4-59).
        body = self._step(lay, "wb.ladder")
        body.addWidget(self._hint("wb.ladder_hint"))
        self.ladder_remove = widgets.button("action", "wb.ladder_remove")
        self.ladder_remove.clicked.connect(self.remove_ladder_mark)
        body.addWidget(self.ladder_remove)
        self.ladder_table = QTableWidget(0, 2)
        self.ladder_table.setMinimumHeight(110)
        self.ladder_table.verticalHeader().setVisible(False)
        self.ladder_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ladder_table.itemChanged.connect(self._ladder_edited)
        body.addWidget(self.ladder_table)
        return panel

    def set_display(self, lo: float, hi: float) -> None:
        """The current blot's display contrast; the numbers are not touched."""
        b = self.current()
        if b is None or hi <= lo:
            return
        b.set_display(lo, hi)
        self._load_widgets()

    def auto_display(self) -> None:
        b = self.current()
        if b is not None:
            b.auto_display()
            self._load_widgets()

    def set_tilt(self, angle: float) -> None:
        """Turn the current blot (§4-43): screen, auto-fit and numbers use the levelled image."""
        b = self.current()
        if b is None or round(float(angle), 2) == b.angle:
            return
        b.turn(angle)
        self._load_widgets()
        self.recompute()
        self._make_figure()

    def auto_tilt(self) -> None:
        """Add the tilt still left in the picked window's bands (measured as the figure's
        auto-level does) to the blot's tilt."""
        b = self.current()
        if b is None:
            return
        left = wbfigure.level_angle(b.blot.image, b.lanes_of(), b.window)
        if left == 0:
            self.statusBar().showMessage(i18n.tr("wb.tilt_none"), 10000)
            return
        self.tilt_spin.setValue(float(np.clip(b.angle + left, -20, 20)))

    def _tilt_points_mode(self, on: bool) -> None:
        if on and self.level_points.isChecked():
            self.level_points.setChecked(False)
        self.view.points = []
        self.view.points_clicked = self._tilt_two_points if on else None
        self.view.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def _tilt_two_points(self, p1, p2) -> None:
        """Two clicks along a band on the shown blot: that line becomes level."""
        self.tilt_points.setChecked(False)
        b = self.current()
        if b is not None:
            self.tilt_spin.setValue(float(np.clip(b.angle + wbfigure.two_point_angle(p1, p2), -20, 20)))

    def _step(self, lay: QVBoxLayout, key: str) -> QVBoxLayout:
        box = QFrame()
        box.setObjectName("step")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(10, 8, 10, 10)
        title = QLabel()
        title.setObjectName("section")
        i18n.bind(title, key)
        inner.addWidget(title)
        lay.addWidget(box)
        self.step_boxes[key] = box
        return inner

    def _spin(self, row: QHBoxLayout, key: str, top: int = 100000) -> QSpinBox:
        label = QLabel()
        i18n.bind(label, key)
        spin = QSpinBox()
        spin.setRange(0, top)
        spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        spin.valueChanged.connect(lambda _: self._read_widgets())
        row.addWidget(label)
        row.addWidget(spin, 1)
        return spin

    def _picker(self, row: QHBoxLayout, key: str) -> QComboBox:
        label = QLabel()
        i18n.bind(label, key)
        combo = QComboBox()
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        row.addWidget(label)
        row.addWidget(combo, 1)
        return combo

    def _build_settings(self) -> QWidget:
        scroll = self.settings_scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        # ① Tilt (§4-43): the blot is levelled before lanes and band areas are drawn on it.
        body = self._step(lay, "wb.step_tilt")
        row = QHBoxLayout()
        tilt_label = QLabel()
        i18n.bind(tilt_label, "wb.tilt")
        tilt_label.setToolTip(i18n.tr("wb.tilt.tip"))
        self.tilt_spin = QDoubleSpinBox()
        self.tilt_spin.setRange(-20, 20)
        self.tilt_spin.setDecimals(2)
        self.tilt_spin.setSingleStep(.25)
        self.tilt_spin.setSuffix(" °")
        self.tilt_spin.setKeyboardTracking(False)  # turn once the number is typed, not per digit
        self.tilt_spin.setToolTip(i18n.tr("wb.tilt.tip"))
        self.tilt_spin.valueChanged.connect(self.set_tilt)
        self.tilt_auto = widgets.button("action", "wb.tilt_auto", tooltip=i18n.tr("wb.tilt_auto.tip"))
        self.tilt_auto.clicked.connect(self.auto_tilt)
        self.tilt_points = widgets.button("toggle", "wb.points", tooltip=i18n.tr("wb.tilt_points.tip"))
        self.tilt_points.toggled.connect(self._tilt_points_mode)
        row.addWidget(tilt_label)
        row.addWidget(self.tilt_spin, 1)
        row.addWidget(self.tilt_auto)
        row.addWidget(self.tilt_points)
        body.addLayout(row)
        # ② Lanes; auto-detect sets the lanes and the picked band area, so it comes first
        body = self._step(lay, "wb.lanes")
        row = QHBoxLayout()
        self.fit_button = widgets.button("toggle", "wb.fit", tooltip=i18n.tr("wb.fit.tip"))
        self.fit_button.toggled.connect(self._fit_mode)
        row.addWidget(self.fit_button, 1)
        body.addLayout(row)
        row = QHBoxLayout()
        self.lane_count = self._spin(row, "wb.count", 30)
        self.lane_width = self._spin(row, "wb.width")
        body.addLayout(row)
        row = QHBoxLayout()
        self.lane_first = self._spin(row, "wb.first")
        self.lane_last = self._spin(row, "wb.last")
        body.addLayout(row)
        # ③ Band areas ("windows" in the code): pick one, add or remove; the fields below edit it
        body = self._step(lay, "wb.window")
        row = QHBoxLayout()
        self.win_pick = self._picker(row, "wb.window_pick")
        self.win_pick.currentIndexChanged.connect(self._pick_window)
        self.win_add = widgets.button("action", "wb.window_add", tooltip=i18n.tr("wb.window_add.tip"))
        self.win_add.clicked.connect(self.add_window)
        self.win_remove = widgets.button("action", "wb.window_remove", tooltip=i18n.tr("wb.window_remove.tip"))
        self.win_remove.clicked.connect(self.remove_window)
        row.addWidget(self.win_add)
        row.addWidget(self.win_remove)
        body.addLayout(row)
        row = QHBoxLayout()
        names_label, splits_label = QLabel(), QLabel()
        i18n.bind(names_label, "wb.names")
        i18n.bind(splits_label, "wb.splits")
        # How many bands the window holds (§4-42): the split lines start evenly spaced and are
        # then dragged on the blot; a count is easier than typing their rows.
        self.win_names, self.win_bands = QLineEdit(), QSpinBox()
        self.win_bands.setRange(1, 6)
        self.win_names.editingFinished.connect(self._read_widgets)
        self.win_bands.valueChanged.connect(self._read_widgets)
        row.addWidget(names_label)
        row.addWidget(self.win_names, 1)
        row.addWidget(splits_label)
        row.addWidget(self.win_bands)
        body.addLayout(row)
        row = QHBoxLayout()
        self.win_top = self._spin(row, "wb.top")
        self.win_bottom = self._spin(row, "wb.bottom")
        body.addLayout(row)
        hint = QLabel()
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        i18n.bind(hint, "wb.drag_hint")
        hint.setToolTip(i18n.tr("wb.drag_hint.tip"))
        body.addWidget(hint)
        # ④ Samples, one row per lane, shared by every blot
        body = self._step(lay, "wb.samples")
        row = QHBoxLayout()
        exp_label = QLabel()
        i18n.bind(exp_label, "wb.experiment")
        self.exp_pick = QComboBox()
        self.exp_pick.addItem("1")
        self.exp_pick.currentIndexChanged.connect(self.switch_experiment)
        exp_name_label = QLabel()
        i18n.bind(exp_name_label, "wb.experiment_name")
        self.exp_name = QLineEdit("1")
        self.exp_name.setToolTip(i18n.tr("wb.experiment_name.tip"))
        self.exp_name.editingFinished.connect(lambda: self.rename_experiment(self.exp_name.text()))
        self.exp_add = widgets.button("action", "wb.experiment_add", tooltip=i18n.tr("wb.experiment_add.tip"))
        self.exp_add.clicked.connect(self.add_experiment)
        self.exp_remove = widgets.button("action", "wb.experiment_remove", tooltip=i18n.tr("wb.experiment_remove.tip"))
        self.exp_remove.clicked.connect(self.remove_experiment)
        self.exp_remove.setEnabled(False)
        row.addWidget(exp_label)
        row.addWidget(self.exp_pick, 1)
        row.addWidget(exp_name_label)
        row.addWidget(self.exp_name, 1)
        row.addWidget(self.exp_add)
        row.addWidget(self.exp_remove)
        body.addLayout(row)
        self.samples = QTableWidget(6, 3)
        self.samples.setMinimumHeight(200)
        self._sample_headers()
        for n in range(6):
            self._fill_sample(n)
        self.samples.itemChanged.connect(lambda _: self.recompute())
        body.addWidget(self.samples)
        body.addWidget(self._hint("wb.samples_hint"))  # where the bar names come from (§4-55)
        # ⑤ Results; each picker on its own row so "blot: p44 + p42" is never cut short
        body = self._step(lay, "wb.results")
        pickers = []
        for key in ("wb.band", "wb.loading_band", "wb.reference"):
            row = QHBoxLayout()
            pickers.append(self._picker(row, key))
            body.addLayout(row)
        self.band_pick, self.loading_pick, self.ref_pick = pickers
        self.band_pick.currentIndexChanged.connect(lambda _: self.recompute(refill=False))
        self.loading_pick.currentIndexChanged.connect(lambda _: self.recompute())  # the target list changes
        self.ref_pick.currentIndexChanged.connect(lambda _: self.recompute(refill=False))
        self.result_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._result_headers()
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setMinimumHeight(200)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        body.addWidget(self.result_table)
        self.warning_label = QLabel()
        self.warning_label.setObjectName("muted")
        self.warning_label.setWordWrap(True)
        self.warning_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body.addWidget(self.warning_label)
        self.graph_view = QLabel()
        self.graph_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_view.setFixedHeight(300)
        self.graph_view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.graph_view.setToolTip(i18n.tr("wb.graph_hint"))
        self.graph_view.installEventFilter(self)  # double click: to the lane names (§4-55)
        body.addWidget(self.graph_view)
        body.addWidget(self._hint("wb.graph_hint"))
        row = QHBoxLayout()
        self.unit_label = QLabel()
        i18n.bind(self.unit_label, "graph.unit")
        self.exp_unit = QComboBox()
        for unit in wbstats.UNITS:
            self.exp_unit.addItem(i18n.tr(f"wb.unit.{unit}"), unit)
        self.exp_unit.currentIndexChanged.connect(lambda _: self._make_graph())
        row.addWidget(self.unit_label)
        row.addWidget(self.exp_unit, 1)
        body.addLayout(row)
        self.unit_label.setVisible(False)
        self.exp_unit.setVisible(False)
        row = QHBoxLayout()
        self.style_button = widgets.button("action", "wb.graph_style", tooltip=i18n.tr("wb.style.tip"))
        self.style_button.clicked.connect(self._ask_style)
        self.save_button = widgets.button("primary", "wb.save", tooltip=i18n.tr("wb.save.tip"))
        self.save_button.clicked.connect(lambda: self._save_asking(self.save))
        self.open_folder = widgets.button("action", "wb.open_folder", tooltip=i18n.tr("wb.open_folder.tip"))
        self.open_folder.setEnabled(False)
        self.open_folder.clicked.connect(self._open_saved)
        row.addWidget(self.style_button)
        row.addWidget(self.save_button, 1)
        row.addWidget(self.open_folder)
        body.addLayout(row)
        self._build_figure(lay)
        lay.addStretch(1)
        scroll.setWidget(inner)
        # Wrapped hint lines need more height in a narrow panel than the scroll area gives by itself:
        # without this the widgets under them overlap (§4-55).
        inner.installEventFilter(self)
        return scroll

    def _build_figure(self, lay: QVBoxLayout) -> None:
        """⑥ Figure (docs/PLAN.md §4-27): pick and name strips, level and stretch each, export."""
        body = self._step(lay, "wb.figure")
        strips_label = QLabel()
        i18n.bind(strips_label, "wb.strips")
        body.addWidget(strips_label)
        self.strip_list = QListWidget()
        self.strip_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.strip_list.setMinimumHeight(110)
        self.strip_list.itemChanged.connect(lambda _: self._make_figure())
        self.strip_list.model().rowsMoved.connect(lambda *_: self._make_figure())
        self.strip_list.currentRowChanged.connect(lambda _: self._pick_strip())
        body.addWidget(self.strip_list)
        row = QHBoxLayout()
        name_label, kda_label = QLabel(), QLabel()
        i18n.bind(name_label, "wb.strip_name")
        i18n.bind(kda_label, "wb.kda")
        self.strip_name, self.strip_kda = QLineEdit(), QLineEdit()
        self.strip_kda.setPlaceholderText("42")
        for e in (self.strip_name, self.strip_kda):
            e.editingFinished.connect(self._read_strip)
        row.addWidget(name_label)
        row.addWidget(self.strip_name, 2)
        row.addWidget(kda_label)
        row.addWidget(self.strip_kda, 1)
        body.addLayout(row)
        row = QHBoxLayout()
        angle_label = QLabel()
        i18n.bind(angle_label, "wb.angle")
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(-20, 20)
        self.angle_spin.setDecimals(2)
        self.angle_spin.setSingleStep(1.0)  # arrows: 1° a click (FG14); typing still takes 0.01°
        self.angle_spin.setSuffix(" °")
        self.angle_spin.setMinimumWidth(110)
        self.angle_spin.valueChanged.connect(lambda v: self.set_angle(v))
        self.level_auto = widgets.button("action", "wb.level_auto", tooltip=i18n.tr("wb.level_auto.tip"))
        self.level_auto.clicked.connect(self.auto_level)
        self.level_points = widgets.button("toggle", "wb.points", tooltip=i18n.tr("wb.level_points.tip"))
        self.level_points.toggled.connect(self._points_mode)
        row.addWidget(angle_label)
        row.addWidget(self.angle_spin, 1)
        row.addWidget(self.level_auto)
        row.addWidget(self.level_points)
        body.addLayout(row)
        row = QHBoxLayout()
        contrast_label = QLabel()
        i18n.bind(contrast_label, "wb.strip_contrast")
        self.strip_lo, self.strip_hi = QSpinBox(), QSpinBox()
        for spin in (self.strip_lo, self.strip_hi):
            spin.setRange(0, 65535)
            spin.setSingleStep(100)
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            spin.valueChanged.connect(lambda _: self.set_strip_contrast(self.strip_lo.value(), self.strip_hi.value()))
        self.strip_screen = widgets.button("action", "wb.strip_screen", tooltip=i18n.tr("wb.strip_screen.tip"))
        self.strip_screen.clicked.connect(self.strip_contrast_from_screen)
        self.figure_unclip = widgets.button("action", "wb.figure_unclip", tooltip=i18n.tr("wb.figure_unclip.tip"))
        self.figure_unclip.clicked.connect(self.unclip_figure)
        row.addWidget(contrast_label)
        row.addWidget(self.strip_lo, 1)
        row.addWidget(self.strip_hi, 1)
        body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.strip_screen, 1)
        row.addWidget(self.figure_unclip, 1)
        body.addLayout(row)
        row = QHBoxLayout()
        self.layout_button = widgets.button("action", "wb.layout", tooltip=i18n.tr("wb.layout.tip"))
        self.layout_button.clicked.connect(self._ask_layout)
        self.figure_dpi = QComboBox()
        self.figure_dpi.addItems(["300 dpi", "600 dpi"])
        self.figure_export = widgets.button("action", "wb.figure_export", tooltip=i18n.tr("wb.figure_export.tip"))
        self.figure_export.clicked.connect(lambda: self._save_asking(self.export_figure))
        row.addWidget(self.layout_button)
        row.addWidget(self.figure_dpi)
        row.addWidget(self.figure_export, 1)
        body.addLayout(row)
        self.figure_note = QLabel()
        self.figure_note.setObjectName("muted")
        self.figure_note.setWordWrap(True)
        self.figure_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body.addWidget(self.figure_note)
        self.figure_view = QLabel()
        self.figure_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.figure_view.setFixedHeight(260)
        self.figure_view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        body.addWidget(self.figure_view)
        self.figure_png: bytes | None = None
        self.figure_record: dict | None = None

    # ---- figure (docs/PLAN.md §4-27) -------------------------------------------------------

    def selected_strip(self) -> tuple | None:
        row = self.strip_list.currentRow()
        return self.strip_list.item(row).data(Qt.ItemDataRole.UserRole) if 0 <= row < self.strip_list.count() else None

    def strip_angle(self, blot, k: int) -> float:
        """The strip's angle from the raw image: typed or two-point, else the blot's tilt plus
        what its own window still leans (§4-29, §4-43)."""
        angle = blot.figure[k]["angle"]
        if angle is None:
            angle = round(blot.angle + wbfigure.level_angle(blot.blot.image, blot.lanes_of(k), blot.windows[k]), 2)
        return angle

    def strip_contrast(self, blot, k: int) -> tuple[float, float]:
        """The strip's (white, black) raw values: its own, or its blot's auto range (§4-30, §4-59)."""
        meta = blot.figure[k]
        lo, hi = blot.auto_range()
        return (lo if meta["lo"] is None else meta["lo"], hi if meta["hi"] is None else meta["hi"])

    def set_strip_contrast(self, lo: float, hi: float) -> None:
        """The picked strip's own linear contrast; other strips and the screen are untouched."""
        key = self.selected_strip()
        if key is None or hi <= lo:
            return
        blot, k = key
        blot.figure[k].update(lo=float(lo), hi=float(hi))
        self._make_figure()

    def strip_contrast_from_screen(self) -> None:
        key = self.selected_strip()
        if key is None:
            return
        blot, k = key
        blot.figure[k].update(lo=float(blot.display[0]), hi=float(blot.display[1]))  # the screen's, now
        self._load_strip()
        self._make_figure()

    def _strip_text(self, blot, k: int) -> str:
        how = i18n.tr("wb.angle_auto") if blot.figure[k]["angle"] is None else i18n.tr("wb.angle_set")
        return f"{blot.name}: {', '.join(blot.windows[k].names)}   {self.strip_angle(blot, k):+.2f}° {how}"

    def set_angle(self, angle: float) -> None:
        """Typed angle: the selected strip only, kept until "Auto"."""
        key = self.selected_strip()
        if key is None:
            return
        blot, k = key
        blot.figure[k]["angle"] = float(angle)
        self._refresh_strip_texts()
        self._make_figure()

    def auto_level(self) -> None:
        """The selected strip back to levelling itself from its window."""
        key = self.selected_strip()
        if key is None:
            return
        blot, k = key
        blot.figure[k]["angle"] = None
        self._load_strip()
        self._refresh_strip_texts()
        self._make_figure()

    def _refresh_strip_texts(self) -> None:
        self.strip_list.blockSignals(True)
        for r, (blot, k) in enumerate(self._strip_keys()):
            self.strip_list.item(r).setText(self._strip_text(blot, k))
        self.strip_list.blockSignals(False)

    def _points_mode(self, on: bool) -> None:
        if on and self.tilt_points.isChecked():
            self.tilt_points.setChecked(False)
        self.view.points = []
        self.view.points_clicked = self._two_points if on else None
        self.view.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    # ---- ladder marks (§4-37) -----------------------------------------------------------------

    def add_ladder_mark(self, x: float, y: float, kda: str = "") -> None:
        """A ladder mark Ctrl+clicked at (x, y) on the shown blot, kept in raw pixels (§4-43);
        without a kDa its table cell opens for typing (§4-59)."""
        b = self.current()
        if b is None:
            return
        x, y = b.to_raw([(x, y)])[0]
        mark = [round(float(x), 1), round(float(y), 1), str(kda)]
        b.ladder.append(mark)
        b.ladder.sort(key=lambda m: m[1])
        self._ladder_changed(b)
        if not kda:
            self.edit_ladder_mark(b.ladder.index(mark))

    def move_ladder_mark(self, i: int, x: float, y: float) -> None:
        """Mark i dragged to (x, y) on the shown blot."""
        b = self.current()
        if b is None or not 0 <= i < len(b.ladder):
            return
        x, y = b.to_raw([(x, y)])[0]
        b.ladder[i][:2] = [round(float(x), 1), round(float(y), 1)]
        b.ladder.sort(key=lambda m: m[1])
        self._ladder_changed(b)

    def remove_ladder_mark(self, i: int | None = None) -> None:
        """Mark i (right click on the blot), or the one picked in the table."""
        b = self.current()
        row = self.ladder_table.currentRow() if i is None else i
        if b is not None and 0 <= row < len(b.ladder):
            del b.ladder[row]
            self._ladder_changed(b)

    def edit_ladder_mark(self, i: int) -> None:
        """Open mark i's kDa cell for typing."""
        if 0 <= i < self.ladder_table.rowCount():
            self.ladder_table.setCurrentCell(i, 0)
            self.ladder_table.editItem(self.ladder_table.item(i, 0))

    def _ladder_edited(self, item) -> None:
        b = self.current()
        if b is not None and item.column() == 0 and item.row() < len(b.ladder):
            b.ladder[item.row()][2] = item.text().strip()
            self._ladder_changed(b, refill=False)

    def _ladder_changed(self, blot, refill: bool = True) -> None:
        self._remember_ladder(blot)
        if refill:
            self._fill_ladder_table()
        self._draw()
        self.view.update()
        self._make_figure()

    def _fill_ladder_table(self) -> None:
        b = self.current()
        marks = b.ladder if b is not None else []
        self.ladder_table.blockSignals(True)
        self.ladder_table.setHorizontalHeaderLabels([i18n.tr("wb.kda"), i18n.tr("wb.ladder_row")])
        self.ladder_table.setRowCount(len(marks))
        for r, (x, y, kda) in enumerate(marks):
            self.ladder_table.setItem(r, 0, QTableWidgetItem(kda))
            where = QTableWidgetItem(f"{y:.0f}")
            where.setFlags(where.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.ladder_table.setItem(r, 1, where)
        self.ladder_table.blockSignals(False)
        self.ladder_remove.setEnabled(bool(marks))

    def _remember_ladder(self, blot) -> None:
        """Kept per raw file in the project's settings.json ("wb_ladders"), so reopening the same
        blot brings its marks back."""
        path = self.settings_path() if self.settings_path else None
        if path is None:
            return
        settings = self._settings()
        ladders = dict(settings.get("wb_ladders", {}))
        ladders[str(blot.path)] = [list(m) for m in blot.ladder]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**settings, "wb_ladders": ladders}, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- figure layout (§4-37) -----------------------------------------------------------------

    def figure_layout(self) -> wbfigure.FigureLayout:
        saved = self._settings().get("wb_layout")
        return wbfigure.FigureLayout(**saved) if saved else self._layout

    def set_figure_layout(self, layout: wbfigure.FigureLayout) -> None:
        self._layout = layout
        path = self.settings_path() if self.settings_path else None
        if path is not None:
            settings = {**self._settings(), "wb_layout": asdict(layout)}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._make_figure()

    def layout_dialog(self) -> tuple:
        """The Figure layout window and a function reading the FigureLayout it shows."""
        layout = self.figure_layout()
        n = max([b.lanes.count for b in self.blots] or [6])
        dialog = QDialog(self)
        dialog.setWindowTitle(i18n.tr("wb.layout"))
        dialog.resize(760, 520)
        form = QFormLayout(dialog)
        font = QComboBox()
        for name in wbfigure.FONTS:
            font.addItem(name, name)
        font.setCurrentIndex(max(0, font.findData(layout.font)))
        size = QDoubleSpinBox()
        size.setRange(4, 24)
        size.setDecimals(1)
        size.setValue(layout.font_size)
        names = QCheckBox(i18n.tr("wb.layout.names"))
        names.setChecked(layout.lane_names)
        rotation = QComboBox()
        for deg in (0, 45, 90):
            rotation.addItem(f"{deg}°", deg)
        rotation.setCurrentIndex(max(0, rotation.findData(layout.lane_rotation)))
        boxes = {}
        for key in ("separators", "border", "ticks", "nearest_ladder"):
            boxes[key] = QCheckBox(i18n.tr(f"wb.layout.{key}"))
            boxes[key].setChecked(getattr(layout, key))
        gap, width = QDoubleSpinBox(), QDoubleSpinBox()
        gap.setRange(0, 3)
        gap.setSingleStep(.1)
        gap.setValue(layout.gap)
        width.setRange(.15, 1.5)
        width.setSingleStep(.05)
        width.setSuffix(" in")
        width.setValue(layout.lane_width_in)
        # The rows above the blot: the header (row 0), then condition rows; column 0 = row name.
        table = QTableWidget(1 + len(layout.conditions), 1 + n)
        table.setHorizontalHeaderLabels([i18n.tr("wb.layout.row")] + [str(k + 1) for k in range(n)])
        first = QTableWidgetItem(i18n.tr("wb.layout.header"))
        first.setFlags(first.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(0, 0, first)
        for k in range(n):
            table.setItem(0, k + 1, QTableWidgetItem(layout.header[k] if k < len(layout.header) else ""))
        for r, row in enumerate(layout.conditions, start=1):
            table.setItem(r, 0, QTableWidgetItem(row.get("name", "")))
            values = row.get("values", [])
            for k in range(n):
                table.setItem(r, k + 1, QTableWidgetItem(values[k] if k < len(values) else ""))
        table.setMinimumHeight(150)
        add, remove = widgets.button("action", "wb.layout.add"), widgets.button("action", "wb.layout.remove")

        def add_row():
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(""))
            for k in range(n):
                table.setItem(r, k + 1, QTableWidgetItem("−"))
        add.clicked.connect(add_row)
        remove.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() > 0 else None)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        for key, w in (("style.family", font), ("style.font", size), ("", names), ("wb.layout.rotation", rotation),
                       ("", boxes["separators"]), ("", boxes["border"]), ("", boxes["ticks"]), ("", boxes["nearest_ladder"]),
                       ("wb.layout.gap", gap), ("wb.layout.width", width)):
            form.addRow(i18n.tr(key) if key else "", w)
        hint = QLabel(i18n.tr("wb.layout.hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        form.addRow(table)
        form.addRow(buttons)
        row = QHBoxLayout()
        ok, cancel = widgets.button("action", "ok"), widgets.button("action", "cancel")
        ok.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)
        cell = lambda r, c: table.item(r, c).text().strip() if table.item(r, c) else ""  # noqa: E731

        def read() -> wbfigure.FigureLayout:
            header = [cell(0, k + 1) for k in range(n)]
            conditions = [{"name": cell(r, 0), "values": [cell(r, k + 1) for k in range(n)]}
                          for r in range(1, table.rowCount())]
            return wbfigure.FigureLayout(font.currentData(), size.value(), names.isChecked(), rotation.currentData(),
                                         header if any(header) else [], conditions, boxes["separators"].isChecked(),
                                         boxes["border"].isChecked(), gap.value(), width.value(),
                                         boxes["ticks"].isChecked(), boxes["nearest_ladder"].isChecked())
        dialog.controls = {"font": font, "size": size, "names": names, "rotation": rotation, "gap": gap,
                           "width": width, "table": table, "add": add, **boxes}
        return dialog, read

    def _ask_layout(self) -> None:
        dialog, read = self.layout_dialog()
        if dialog.exec():
            self.set_figure_layout(read())

    def _two_points(self, p1, p2) -> None:
        """Two clicks on the shown blot set the selected strip's angle (that strip's blot is the
        one shown: picking a strip shows its blot)."""
        self.level_points.setChecked(False)
        key = self.selected_strip()
        base = key[0].angle if key is not None else 0.0  # the clicks are on the turned blot (§4-43)
        self.angle_spin.setValue(round(base + wbfigure.two_point_angle(p1, p2), 2))

    def _strip_keys(self) -> list[tuple]:
        """(blot, window index) of every strip, in the list's order."""
        return [self.strip_list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.strip_list.count())]

    def _fill_strips(self) -> None:
        """One checkable row per band window of every blot; existing rows keep their order and ticks."""
        old = {key: self.strip_list.item(r).checkState() for r, key in enumerate(self._strip_keys())}
        keys = [k for k in old if k[0] in self.blots and k[1] < len(k[0].windows)]
        keys += [(b, k) for b in self.blots for k in range(len(b.windows)) if (b, k) not in keys]
        self.strip_list.blockSignals(True)
        current = self.strip_list.currentRow()
        self.strip_list.clear()
        for blot, k in keys:
            while len(blot.figure) < len(blot.windows):
                blot.figure.append({"label": "", "kda": "", "angle": None, "lo": None, "hi": None})
            item = QListWidgetItem(self._strip_text(blot, k))
            item.setData(Qt.ItemDataRole.UserRole, (blot, k))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(old.get((blot, k), Qt.CheckState.Checked))
            self.strip_list.addItem(item)
        self.strip_list.setCurrentRow(min(max(current, 0), self.strip_list.count() - 1))
        self.strip_list.blockSignals(False)
        self._load_strip()

    def _load_strip(self) -> None:
        """The name, kDa and angle fields from the selected strip."""
        key = self.selected_strip()
        fields = (self.strip_name, self.strip_kda, self.angle_spin, self.strip_lo, self.strip_hi)
        for e in fields:
            e.blockSignals(True)
        if key is not None:
            blot, k = key
            meta = blot.figure[k]
            self.strip_name.setText(meta["label"] or ", ".join(blot.windows[k].names))
            self.strip_kda.setText(meta["kda"])
            self.angle_spin.setValue(self.strip_angle(blot, k))
            lo, hi = self.strip_contrast(blot, k)
            self.strip_lo.setValue(int(round(lo)))
            self.strip_hi.setValue(int(round(hi)))
        for e in fields:
            e.blockSignals(False)

    def _pick_strip(self) -> None:
        """Picking a strip shows its blot and window, so two points are clicked on the right one."""
        key = self.selected_strip()
        self._load_strip()
        if key is None:
            return
        blot, k = key
        blot.selected = k
        i = self.blots.index(blot)
        if self.blot_list.currentRow() != i:
            self.blot_list.setCurrentRow(i)
        else:
            self._load_widgets()

    def _read_strip(self) -> None:
        row = self.strip_list.currentRow()
        if 0 <= row < self.strip_list.count():
            blot, k = self.strip_list.item(row).data(Qt.ItemDataRole.UserRole)
            blot.figure[k].update(label=self.strip_name.text().strip(), kda=self.strip_kda.text().strip())
            self._make_figure()

    def figure_strips(self) -> list[wbfigure.Strip]:
        """The ticked strips, top to bottom, each with its own angle and its blot's screen contrast."""
        out = []
        for r, (blot, k) in enumerate(self._strip_keys()):
            if self.strip_list.item(r).checkState() != Qt.CheckState.Checked:
                continue
            meta = blot.figure[k]
            out.append(wbfigure.Strip(str(blot.path), self.strip_angle(blot, k), asdict(blot.lanes_of(k)),
                                      asdict(blot.windows[k]), *self.strip_contrast(blot, k),
                                      meta["label"] or ", ".join(blot.windows[k].names), meta["kda"],
                                      auto=meta["angle"] is None, ticks=[list(m) for m in blot.ladder if m[2]],
                                      extend=self.figure_layout().nearest_ladder, base=blot.angle))
        return out

    def lane_labels(self) -> list[str]:
        return [s["name"] or s["group"] for s in self.samples_list()]

    def _make_figure(self) -> None:
        strips = self.figure_strips()
        counts = {wb.Lanes(**s.lanes).count for s in strips}
        self.figure_png = self.figure_record = None
        note = ""
        if strips and len(counts) == 1:
            n = counts.pop()
            record = wbfigure.compose(strips, self.lane_labels()[:n], None, dpi=110, layout=self.figure_layout())
            self.figure_png, self.figure_record = record.pop("png"), record
            clipped = [f"{s['label']}: {100 * s['clipped_white_black'][1]:.1f}%" for s in record["strips"]
                       if s["clipped_white_black"][1] > 0]
            if clipped:
                note = i18n.tr("wb.figure_clipped", strips=", ".join(clipped))
        elif strips:
            note = i18n.tr("wb.figure_lanes")
        self.figure_note.setText(note)
        if self.figure_png is None:
            self.figure_view.setPixmap(QPixmap())
            return
        pix = QPixmap()
        pix.loadFromData(self.figure_png, "PNG")
        self.figure_view.setPixmap(pix.scaled(self.figure_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))

    def unclip_figure(self) -> None:
        """Each ticked strip's black point = its own largest value (rotated and cut, as drawn),
        so no strip pixel is shown pure black (FG9, FG16). The screen contrast is not changed."""
        for r, (blot, k) in enumerate(self._strip_keys()):
            if self.strip_list.item(r).checkState() != Qt.CheckState.Checked:
                continue
            lo, hi = self.strip_contrast(blot, k)
            s = wbfigure.Strip(str(blot.path), self.strip_angle(blot, k), asdict(blot.lanes_of(k)),
                               asdict(blot.windows[k]), lo, hi, base=blot.angle)
            top = float(s.cut(blot.raw.image)[0].max())
            if top > lo:
                blot.figure[k].update(lo=float(lo), hi=float(np.nextafter(top, np.inf)))
        self._load_strip()
        self._make_figure()

    # ---- where saves go (§4-35) -------------------------------------------------------------

    def _settings(self) -> dict:
        path = self.settings_path() if self.settings_path else None
        return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}

    def start_folder(self) -> Path:
        """Where the folder picker opens: the last chosen folder, else <results folder>/wb."""
        last = self._wb_dir or (Path(self._settings()["wb_dir"]) if self._settings().get("wb_dir") else None)
        return last if last is not None and last.is_dir() else Path(self.results_root()) / "wb"

    def remember_folder(self, folder: Path) -> None:
        self._wb_dir = Path(folder)
        path = self.settings_path() if self.settings_path else None
        if path is not None:
            settings = {**self._settings(), "wb_dir": str(Path(folder))}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def ask_folder(self) -> Path | None:
        """The folder picker; None if cancelled."""
        start = self.start_folder()
        chosen = QFileDialog.getExistingDirectory(self, i18n.tr("wb.save_where"), str(start if start.is_dir() else start.parent))
        return Path(chosen) if chosen else None

    def _save_asking(self, save) -> Path | None:
        """A Save button: pick a folder (cancel writes nothing), remember it, save into it."""
        if (save == self.save and not self.rows) or (save == self.export_figure and not self.figure_strips()):
            return save()  # nothing to save: the method's own no-op
        folder = self.ask_folder()
        if folder is None:
            return None
        self.remember_folder(folder)
        return save(folder)

    def _saved(self, out: Path) -> None:
        self.saved_to = out
        self.saved_label.setText(i18n.tr("wb.saved_to", path=out))
        self.open_folder.setEnabled(True)
        self.statusBar().showMessage(i18n.tr("status.saved", path=out), 10000)

    def _open_saved(self) -> None:
        if self.saved_to is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_to)))

    def export_figure(self, folder: Path | None = None) -> Path | None:
        """<folder>/figure-<date-time>/figure.png, .tif, .svg, .pdf and .json; folder defaults to
        <results folder>/wb."""
        strips = self.figure_strips()
        if not strips or len({wb.Lanes(**s.lanes).count for s in strips}) != 1:
            return None
        n = wb.Lanes(**strips[0].lanes).count
        root = Path(folder) if folder is not None else Path(self.results_root()) / "wb"
        out = root / f"figure-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        k = 1
        while out.exists():
            k += 1
            out = out.with_name(f"{out.name.split('_')[0]}_{k}")
        dpi = 600 if self.figure_dpi.currentIndex() == 1 else 300
        wbfigure.compose(strips, self.lane_labels()[:n], out / "figure", dpi=dpi, layout=self.figure_layout())
        self._saved(out)
        return out

    def _result_headers(self) -> None:
        """Shown headers only; results.csv and the xlsx keep the English column names."""
        self.result_table.setHorizontalHeaderLabels([i18n.tr(f"wb.col.{c}") for c in RESULT_COLUMNS])

    def _sample_headers(self) -> None:
        keys = ("wb.sample", "wb.group", "wb.replicate")
        self.samples.setHorizontalHeaderLabels([i18n.tr(k) for k in keys])
        for c, key in enumerate(keys):
            self.samples.horizontalHeaderItem(c).setToolTip(i18n.tr(f"{key}.tip"))

    def _hint(self, key: str) -> QLabel:
        label = QLabel()
        label.setObjectName("muted")
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        i18n.bind(label, key)
        return label

    def edit_lane_names(self) -> None:
        """Show the sample table and start editing lane 1's name: the bars are named there (§4-55)."""
        self.settings_scroll.ensureWidgetVisible(self.samples)
        self.samples.setFocus()
        self.samples.setCurrentCell(0, 0)
        self.samples.editItem(self.samples.item(0, 0))

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "graph_view", None) and event.type() == event.Type.MouseButtonDblClick:
            self.edit_lane_names()
            return True
        if obj is self.settings_scroll.widget() and event.type() == event.Type.Resize:
            obj.setMinimumHeight(obj.layout().heightForWidth(obj.width()))
        return super().eventFilter(obj, event)

    def _fill_sample(self, n: int) -> None:
        for c, text in enumerate(("", "", f"lane {n + 1}")):
            if self.samples.item(n, c) is None:
                self.samples.setItem(n, c, QTableWidgetItem(text))

    # ---- blots ------------------------------------------------------------------------------

    def _ask_open(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, i18n.tr("wb.open"), "", "TIFF (*.tif *.tiff);;All files (*)")
        for p in paths:
            self.open_blot(Path(p))

    def open_blot(self, path: Path) -> bool:
        """Add a raw blot; anything else is refused with the reason in the status bar."""
        try:
            blot = wb.read_blot(path)
        except (ValueError, OSError) as exc:
            self.statusBar().showMessage(str(exc), 15000)
            return False
        item = _Blot(Path(path), blot)
        item.ladder = [list(m) for m in self._settings().get("wb_ladders", {}).get(str(Path(path)), [])]
        if "actin" in item.name.lower():
            item.windows = [wb.Window(["actin"], item.window.top, item.window.bottom)]
        self.blots.append(item)
        self.blot_list.addItem(item.name)
        self.blot_list.item(len(self.blots) - 1).setToolTip(str(Path(path)))
        self._tell_apart()
        self.blot_list.setCurrentRow(len(self.blots) - 1)
        self.recompute()
        return True

    def _tell_apart(self) -> None:
        """Blots whose folder names give the same name get their folder date added, and the
        imager's time (or a number) when the dates match too, so the pickers can tell them apart
        (§4-39, §4-40); names the user typed stay."""
        groups: dict[str, list] = {}
        for b in self.blots:
            if b.name == b.base_name or b.name.startswith(b.base_name + " ("):
                groups.setdefault(b.base_name, []).append(b)
        for base, same in groups.items():
            for n, b in enumerate(same, start=1):
                twins = [o for o in same if o.date == b.date]
                if len(same) == 1:
                    b.name = base
                elif not b.date:
                    b.name = f"{base} ({n})"
                elif len(twins) == 1:
                    b.name = f"{base} ({b.date})"
                elif b.time and [o.time for o in twins].count(b.time) == 1:
                    b.name = f"{base} ({b.date} {b.time})"
                else:
                    b.name = f"{base} ({b.date}-{twins.index(b) + 1})"
        for r, b in enumerate(self.blots):
            self.blot_list.item(r).setText(b.name)

    def close_blot(self) -> None:
        """Take the picked blot off the list (its file is untouched). Target and loading control
        keep pointing at the same blot and band when that blot stays (§4-26)."""
        i = self.blot_list.currentRow()
        if not 0 <= i < len(self.blots):
            return
        kept = {}
        for name, combo in (("loading", self.loading_pick), ("target", self.band_pick)):
            d = combo.currentData()
            if d and d["blot"] != i:
                kept[name] = (self.blots[d["blot"]], d["band"])
        for k, e in enumerate(self.experiments):  # the other experiments' blot numbers (§4-39)
            if k == self.exp_index:
                continue
            for key in ("target", "loading"):
                d = e.get(key)
                if d and d["blot"] == i:
                    e[key] = {}
                elif d and d["blot"] > i:
                    e[key] = {**d, "blot": d["blot"] - 1}
        del self.blots[i]
        self.blot_list.blockSignals(True)
        self.blot_list.takeItem(i)
        self.blot_list.setCurrentRow(min(i, len(self.blots) - 1))
        self.blot_list.blockSignals(False)
        for name, combo in (("loading", self.loading_pick), ("target", self.band_pick)):
            combo.blockSignals(True)
            combo.clear()  # drop the old indices; refilled below
            if name in kept:
                blot, band = kept[name]
                combo.addItem("", {"blot": self.blots.index(blot), "band": band})
            combo.blockSignals(False)
        self._load_widgets()
        self.recompute()

    def close_all(self, ask: bool = True) -> bool:
        """Start over (§4-50): every blot off the list (files untouched), one experiment, an empty
        sample table, no results. The graph style, figure layout, save folder and remembered ladder
        marks stay."""
        if not self.blots:
            return False
        if ask and QMessageBox.question(self, i18n.tr("wb.close_all"), i18n.tr("wb.close_all.ask")) \
                != QMessageBox.StandardButton.Yes:
            return False
        self.blots.clear()
        self.experiments, self.exp_index = [{"name": "1"}], 0
        emptied = (self.blot_list, self.strip_list, self.loading_pick, self.band_pick, self.ref_pick)
        for w in (*emptied, self.samples):
            w.blockSignals(True)
        for w in emptied:
            w.clear()
        self.samples.clearContents()
        self.samples.setRowCount(6)
        for n in range(6):
            self._fill_sample(n)
        for w in (*emptied, self.samples):
            w.blockSignals(False)
        self.saved_to = None
        self.saved_label.clear()
        self._fill_experiments(0)
        self._load_widgets()
        self.recompute()
        return True

    def current(self) -> _Blot | None:
        i = self.blot_list.currentRow()
        return self.blots[i] if 0 <= i < len(self.blots) else None

    def _set_blot(self, **changes) -> None:
        b = self.current()
        if b is None:
            return
        for k, v in changes.items():
            setattr(b, k, v)
        if "name" in changes:
            self.blot_list.item(self.blot_list.currentRow()).setText(b.name)
        self.recompute()

    def set_lanes(self, lanes: wb.Lanes) -> None:
        """New lanes for the current blot's picked window (§4-51)."""
        self.current().set_lanes(lanes)
        self._load_widgets()
        self.recompute()

    def set_window(self, window: wb.Window) -> None:
        """Replace the picked band window of the current blot."""
        self.current().window = window
        self._load_widgets()
        self.recompute()

    def add_window(self) -> None:
        """A new band window below the last one (same height), picked for editing."""
        b = self.current()
        if b is None:
            return
        h = b.blot.image.shape[0]
        last = b.windows[-1]
        height = last.bottom - last.top
        top = min(last.bottom + 20, h - height)
        b.windows.append(wb.Window([f"band {len(b.windows) + 1}"], max(0, top), max(0, top) + height, lanes=last.lanes))
        b.selected = len(b.windows) - 1
        self._load_widgets()
        self.recompute()

    def remove_window(self) -> None:
        b = self.current()
        if b is None or len(b.windows) < 2:
            return
        del b.windows[b.selected]
        del b.figure[b.selected]
        b.selected = max(0, b.selected - 1)
        if len(b.windows) == 1:  # one window left: its lanes are the blot's again
            b.lanes, b.windows[0] = b.lanes_of(0), replace(b.windows[0], lanes=None)
        self._load_widgets()
        self.recompute()

    def _fit_mode(self, on: bool) -> None:
        self.view.fit_mode = on
        self.view.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def fit_at(self, x: float, y: float) -> bool:
        """Fit the lanes and the picked window to the band clicked at image (x, y): a suggestion,
        to drag or nudge afterwards. Nothing changes where there is no band."""
        b = self.current()
        if b is None:
            return False
        try:
            lanes, top, bottom = wb.fit(b.blot.image, x, y, b.lanes.count, b.lanes_of())
        except ValueError as exc:
            self.statusBar().showMessage(i18n.tr("wb.fit.none", reason=str(exc)), 10000)
            return False
        old = b.window
        keep = [s for s in old.splits if top + wb.END_ROWS < s < bottom - wb.END_ROWS]
        names = old.names if len(keep) == len(old.splits) else old.names[:len(keep) + 1]
        b.window = wb.Window(list(names), top, bottom, keep, old.lanes)
        b.set_lanes(lanes)  # the clicked window's lanes only (§4-51)
        self.fit_button.setChecked(False)
        self._load_widgets()
        self.recompute()
        return True

    def _pick_window(self, k: int) -> None:
        b = self.current()
        if b is None or not 0 <= k < len(b.windows):
            return
        b.selected = k
        self._load_widgets()

    def _load_widgets(self) -> None:
        """The panels from the current blot's settings."""
        b = self.current()
        widgets_ = (self.lane_count, self.lane_width, self.lane_first, self.lane_last, self.win_top, self.win_bottom,
                    self.name_edit, self.same_gel_box, self.win_names, self.win_bands, self.win_pick,
                    self.display_lo, self.display_hi, self.tilt_spin)
        for w in widgets_:
            w.blockSignals(True)
        if b is not None:
            lanes = b.lanes_of()  # the picked window's (§4-51)
            self.lane_count.setValue(lanes.count)
            self.lane_width.setValue(int(round(lanes.width)))
            self.lane_first.setValue(int(round(lanes.first)))
            self.lane_last.setValue(int(round(lanes.last)))
            self.win_pick.clear()
            self.win_pick.addItems([", ".join(w.names) for w in b.windows])
            self.win_pick.setCurrentIndex(b.selected)
            self.win_top.setValue(b.window.top)
            self.win_bottom.setValue(b.window.bottom)
            self.win_names.setText(", ".join(b.window.names))
            self.win_bands.setValue(len(b.window.splits) + 1)
            self.name_edit.setText(b.name)
            self.same_gel_box.setChecked(b.same_gel)
            self.display_lo.setValue(int(round(b.display[0])))
            self.display_hi.setValue(int(round(b.display[1])))
            self.tilt_spin.setValue(b.angle)
        self.win_remove.setEnabled(b is not None and len(b.windows) > 1)
        self.close_button.setEnabled(b is not None)
        self.close_all_button.setEnabled(bool(self.blots))
        for w in (self.tilt_spin, self.tilt_auto, self.tilt_points):
            w.setEnabled(b is not None)
        has_marker = b is not None and b.marker_path is not None
        self.marker_toggle.setEnabled(has_marker)
        if not has_marker and self.marker_toggle.isChecked():
            self.marker_toggle.blockSignals(True)
            self.marker_toggle.setChecked(False)
            self.marker_toggle.blockSignals(False)
        self._fill_ladder_table()

        for w in widgets_:
            w.blockSignals(False)
        self._draw()

    def _read_widgets(self) -> None:
        """The current blot's settings from the panels (invalid ones are reported, not kept)."""
        b = self.current()
        if b is None:
            return
        count, width, old = self.lane_count.value(), self.lane_width.value(), b.lanes_of()
        lanes = wb.Lanes(count, self.lane_first.value(), self.lane_last.value(),
                         width if width != int(round(old.width)) else old.width)
        if (lanes.count, lanes.first, lanes.last, lanes.width) == (old.count, old.first, old.last, old.width):
            lanes = old  # nothing typed in ②: the lanes as they were
        top, bottom, n = self.win_top.value(), self.win_bottom.value(), self.win_bands.value()
        splits = list(b.window.splits)
        if len(splits) != n - 1 or not all(top < s < bottom for s in splits):  # a new count: evenly spaced
            splits = [top + round(k * (bottom - top) / n) for k in range(1, n)]
        names = [s.strip() for s in self.win_names.text().split(",") if s.strip()]
        if len(names) != n:
            names = [f"band {k + 1}" for k in range(n)] if n > 1 else (names[:1] or ["band"])
        try:
            window = wb.Window(names, top, bottom, splits, b.window.lanes)
        except ValueError:
            self.statusBar().showMessage(i18n.tr("wb.window_invalid"), 8000)
            return
        b.window = window
        b.set_lanes(lanes)
        window = b.window
        self.win_pick.blockSignals(True)
        self.win_pick.setItemText(b.selected, ", ".join(window.names))
        self.win_pick.blockSignals(False)
        self.recompute()

    # ---- drawing ----------------------------------------------------------------------------

    def _draw(self) -> None:
        b = self.current()
        if b is None:
            self.view.show_blot(None)
            self.overlay = {}
            return
        self.view.marker = b.marker() if self.marker_toggle.isChecked() else None
        shown = b.from_raw([(m[0], m[1]) for m in b.ladder]) if b.ladder else []
        self.view.marks = [[float(p[0]), float(p[1]), m[2]] for p, m in zip(shown, b.ladder)]
        self.view.show_blot(b.grey, b.lanes, b.windows, b.selected, key=id(b))
        self.overlay = {"boxes": [(*b.lanes_of().columns(i), b.window.top, b.window.bottom) for i in range(b.lanes.count)],
                        "splits": list(b.window.splits),
                        "windows": [(w.top, w.bottom, list(w.splits)) for w in b.windows]}

    def _dragged(self, lanes: wb.Lanes, windows: list[wb.Window], selected: int) -> None:
        """A drag or arrow key on the blot: keep it, show it in the number boxes, recompute
        (a click that only picks another window recomputes nothing)."""
        b = self.current()
        if b is None:
            return
        changed = lanes != b.lanes or windows != b.windows
        b.lanes, b.windows, b.selected = lanes, list(windows), selected
        self._load_widgets()
        if changed:
            self.recompute()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._show_graph()

    # ---- results ----------------------------------------------------------------------------

    def samples_list(self) -> list[dict]:
        out = []
        for n in range(self.samples.rowCount()):
            text = [(self.samples.item(n, c).text().strip() if self.samples.item(n, c) else "") for c in range(3)]
            out.append({"name": text[0], "group": text[1] or text[0] or f"lane {n + 1}", "replicate": text[2]})
        return out

    def _current_experiment(self) -> dict:
        return {"name": self.experiments[self.exp_index]["name"], "loading": self.loading_pick.currentData() or {},
                "target": self.band_pick.currentData() or {}, "samples": self.samples_list(),
                "reference": self.ref_pick.currentText()}

    def experiments_now(self) -> list[dict]:
        """Every experiment, the current one as the widgets show it."""
        return [self._current_experiment() if i == self.exp_index else e for i, e in enumerate(self.experiments)]

    def settings(self) -> dict:
        """Everything needed to re-run the numbers (saved next to the results). The current
        experiment is also at the top level, so one experiment reads like older settings."""
        current = self._current_experiment()
        out = {"blots": [b.settings() for b in self.blots], "background": "hull",  # never negative (§4-60)
               **{k: v for k, v in current.items() if k != "name"}}
        if len(self.experiments) > 1:
            out["experiments"] = self.experiments_now()
        return out

    # ---- experiments (§4-38) -----------------------------------------------------------------

    def add_experiment(self) -> bool:
        """A new experiment with the current one's lane table and reference, and its target and
        loading control on open blots no experiment uses yet: the same band names, preferring a
        blot of the same name (another date) in another parent folder, and a loading control next
        to the new target. Only a suggestion, so the status bar names what was picked. None free:
        nothing is added (§4-39, §4-40)."""
        current = self._current_experiment()
        self.experiments[self.exp_index] = current
        used = {e[key]["blot"] for e in self.experiments for key in ("target", "loading") if e.get(key)}
        free = [i for i in range(len(self.blots)) if i not in used]

        def pick(want: dict, among: list[int], near=None) -> dict:
            if not want:
                return {}
            was = self.blots[want["blot"]]
            fits = [i for i in among if want["band"] in self.blots[i].bands()]
            if near is None:  # the target: same name, then not in the current experiment's folder
                fits.sort(key=lambda i: (self.blots[i].base_name != was.base_name,
                                         self.blots[i].path.parent.parent == was.path.parent.parent))
            else:  # the loading control: in the new target's folder, then of its date
                fits.sort(key=lambda i: (self.blots[i].path.parent.parent != near.path.parent.parent,
                                         self.blots[i].date != near.date,
                                         self.blots[i].base_name != was.base_name))
            return {"blot": fits[0], "band": want["band"]} if fits else {}

        target = pick(current["target"], free)
        if current["loading"] and current["target"] and current["loading"]["blot"] == current["target"]["blot"]:
            loading = {"blot": target["blot"], "band": current["loading"]["band"]} if target else {}  # one membrane
        else:
            loading = pick(current["loading"], [i for i in free if not target or i != target["blot"]],
                           near=self.blots[target["blot"]] if target else None)
        if not target or not loading:
            self.statusBar().showMessage(i18n.tr("wb.experiment_no_blots"), 15000)
            return False
        names = {e["name"] for e in self.experiments}
        k = len(self.experiments) + 1
        while str(k) in names:
            k += 1
        self.experiments.append({**current, "name": str(k), "target": target, "loading": loading})
        self._fill_experiments(len(self.experiments) - 1)
        self.statusBar().showMessage(i18n.tr("wb.experiment_picked").format(
            name=k, target=self.blots[target["blot"]].name, loading=self.blots[loading["blot"]].name), 30000)
        return True

    def remove_experiment(self) -> None:
        if len(self.experiments) > 1:
            del self.experiments[self.exp_index]
            self.exp_index = min(self.exp_index, len(self.experiments) - 1)
            self._fill_experiments(self.exp_index, store=False)

    def rename_experiment(self, name: str) -> None:
        name = name.strip()
        if name and name not in {e["name"] for i, e in enumerate(self.experiments) if i != self.exp_index}:
            self.experiments[self.exp_index]["name"] = name
            self.exp_pick.blockSignals(True)
            self.exp_pick.setItemText(self.exp_index, name)
            self.exp_pick.blockSignals(False)
            self.recompute(refill=False)
        else:
            self.exp_name.setText(self.experiments[self.exp_index]["name"])

    def switch_experiment(self, index: int, store: bool = True) -> None:
        """Show experiment `index` in ③ and ④ (the one shown before keeps what it had)."""
        if not 0 <= index < len(self.experiments):
            return
        if store and index != self.exp_index:
            self.experiments[self.exp_index] = self._current_experiment()
        self.exp_index = index
        e = self.experiments[index]
        self.exp_name.setText(e["name"])
        if "samples" in e:
            self.samples.blockSignals(True)
            self.samples.setRowCount(len(e["samples"]))
            for n, s in enumerate(e["samples"]):
                for c, key in enumerate(("name", "group", "replicate")):
                    self.samples.setItem(n, c, QTableWidgetItem(s[key]))
            self.samples.blockSignals(False)
        self._fill_pickers()
        for combo, key in ((self.loading_pick, "loading"), (self.band_pick, "target")):
            if e.get(key):
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(e[key])))
                combo.blockSignals(False)
            if key == "loading":
                self._fill_pickers()  # the target list leaves out the loading band
        if e.get("reference"):
            self.ref_pick.blockSignals(True)
            self.ref_pick.setCurrentIndex(max(0, self.ref_pick.findText(e["reference"])))
            self.ref_pick.blockSignals(False)
        self.recompute(refill=False)

    def _fill_experiments(self, index: int, store: bool = False) -> None:
        self.exp_pick.blockSignals(True)
        self.exp_pick.clear()
        self.exp_pick.addItems([e["name"] for e in self.experiments])
        self.exp_pick.setCurrentIndex(index)
        self.exp_pick.blockSignals(False)
        self.exp_remove.setEnabled(len(self.experiments) > 1)
        several = len(self.experiments) > 1
        self.unit_label.setVisible(several)
        self.exp_unit.setVisible(several)
        self.switch_experiment(index, store=store)

    def _label(self, band: dict) -> str:
        return f"{self.blots[band['blot']].name}: {band['band']}"

    def _fill_pickers(self) -> None:
        every = [{"blot": i, "band": name} for i, b in enumerate(self.blots) for name in b.bands()]
        loading = self.loading_pick.currentData()
        if loading not in every:  # default: a band or blot named actin, else the first band
            loading = next((d for d in every if "actin" in self._label(d).lower()), every[0] if every else None)
        target = self.band_pick.currentData()
        for combo, items, keep in ((self.loading_pick, every, loading),
                                   (self.band_pick, [d for d in every if d != loading], target)):
            combo.blockSignals(True)
            combo.clear()
            for d in items:
                combo.addItem(self._label(d), d)
            combo.setCurrentIndex(max(0, combo.findData(keep)))
            combo.blockSignals(False)
        ref = self.ref_pick.currentText()
        groups = list(dict.fromkeys(s["group"] for s in self.samples_list()))
        self.ref_pick.blockSignals(True)
        self.ref_pick.clear()
        self.ref_pick.addItems(groups)
        self.ref_pick.setCurrentIndex(max(0, self.ref_pick.findText(ref)))
        self.ref_pick.blockSignals(False)

    def recompute(self, refill: bool = True) -> None:
        """Lanes in the sample table follow the lane count; then measure, normalise and draw."""
        lanes = max([b.lanes.count for b in self.blots] or [6])
        if self.samples.rowCount() != lanes:
            self.samples.blockSignals(True)
            self.samples.setRowCount(lanes)
            for n in range(lanes):
                self._fill_sample(n)
            self.samples.blockSignals(False)
        if refill:
            self._fill_pickers()
            self._fill_strips()
        self._draw()
        self.rows, self.warnings, self.all_rows = [], [], []
        try:
            if self.band_pick.currentData() and self.loading_pick.currentData():
                self.rows, self.warnings = wb.run(self.settings())
        except (ValueError, OSError, ZeroDivisionError) as exc:
            self.warnings = [str(exc)]
        if len(self.experiments) > 1:
            try:
                self.all_rows, self.warnings = wb.run_experiments(self.settings())
            except (ValueError, OSError, ZeroDivisionError, KeyError) as exc:
                self.all_rows, self.warnings = [], self.warnings + [f"{i18n.tr('wb.experiments')}: {exc}"]
        self._show_rows()

    def _show_rows(self) -> None:
        self.result_table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, key in enumerate(RESULT_COLUMNS):
                v = row[key]
                self.result_table.setItem(r, c, QTableWidgetItem(f"{v:.4g}" if isinstance(v, float) else str(v)))
        self.warning_label.setText("\n".join(warning_text(w) for w in self.warnings))
        self._make_graph()
        self._make_figure()

    def graph_item(self) -> tuple[dict, dict, GraphStyle] | None:
        """The relative values as a dot plot, one dot per lane (independent replicate)."""
        if not self.rows:
            return None
        band, loading = self.band_pick.currentData(), self.loading_pick.currentData()
        target = f"{self.blots[band['blot']].name} {band['band']}"
        if len(self.experiments) > 1:
            if not self.all_rows:
                return None
            groups = list(dict.fromkeys(s["group"] for e in self.experiments_now() for s in e.get("samples", [])))
            groups = [g for g in groups if any(r["group"] == g for r in self.all_rows)]
            candidate, stats = wbstats.combine(self.all_rows, groups, self.exp_unit.currentData() or "experiment",
                                               target, self.warnings)
            candidate["title"] = f"{target} / {loading['band']}"
            style = self.graph_style()
            if not style.y_label:
                style = replace(style, y_label=f"Relative to {self.ref_pick.currentText()}")
            return candidate, stats, style
        rows = [{"cohort": "WB", "group": r["group"], "replicate": r["replicate"], "image": f"lane{r['lane']}",
                 "channel": 0, "marker": target, "projection": "wb", "mean": r["relative"], "threshold": "",
                 "spec": "", "warnings": "; ".join(self.warnings)} for r in self.rows]
        candidate = recommendations(rows)[0]
        candidate["title"] = f"{target} / {loading['band']}"  # one line: a second one is cut off at the top
        stats = candidate_statistics(candidate)
        style = self.graph_style()
        if not style.y_label:
            style = replace(style, y_label=f"Relative to {self.ref_pick.currentText()}")
        return candidate, stats, style

    # ---- graph style (§4-36): the main window's Style window, kept as "wb_style" -------------

    def graph_style(self) -> GraphStyle:
        saved = self._settings().get("wb_style")
        return GraphStyle(**saved) if saved else self._style

    def set_graph_style(self, style: GraphStyle) -> None:
        self._style = style
        path = self.settings_path() if self.settings_path else None
        if path is not None:
            settings = {**self._settings(), "wb_style": asdict(style)}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._make_graph()

    def style_dialog(self) -> tuple:
        groups = list(dict.fromkeys(r["group"] for r in self.rows))
        return style_dialog(self, self.graph_style(), groups)

    def _ask_style(self) -> None:
        dialog, read = self.style_dialog()
        if dialog.exec():
            self.set_graph_style(read())

    def _make_graph(self) -> None:
        item = self.graph_item()
        self.graph_png = None if item is None else preview(item[0], item[0]["values"], item[1], style=item[2])
        self._show_graph()

    def _show_graph(self) -> None:
        if self.graph_png is None:
            self.graph_view.setPixmap(QPixmap())
            return
        pix = QPixmap()
        pix.loadFromData(self.graph_png, "PNG")
        self.graph_view.setPixmap(pix.scaled(self.graph_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def save(self, folder: Path | None = None) -> Path | None:
        """<folder>/<date-time>/: results.csv, settings.json and the graph files; folder defaults
        to <results folder>/wb."""
        if not self.rows:
            return None
        root = Path(folder) if folder is not None else Path(self.results_root()) / "wb"
        base = root / datetime.now().strftime("%Y%m%d-%H%M%S")
        out, n = base, 1
        while out.exists():
            n += 1
            out = base.with_name(f"{base.name}-{n}")
        out.mkdir(parents=True)
        several = len(self.experiments) > 1
        rows = self.all_rows if several else self.rows
        columns = (("experiment",) if several else ()) + RESULT_COLUMNS
        with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        candidate, stats, style = self.graph_item()
        settings = {**self.settings(), "warnings": self.warnings, "style": asdict(style),
                    "app_version": __version__}  # which version made these numbers (§4-41)
        if several:
            settings["unit"] = self.exp_unit.currentData()
        (out / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_xlsx(out / "results.xlsx", rows, candidate, stats)
        dot_bar(candidate, candidate["values"], stats, out / "graph", style=style)
        self._saved(out)
        return out

    def _write_xlsx(self, path: Path, rows: list[dict], candidate: dict, stats: dict) -> None:
        """results.xlsx (§4-38): every lane, one value per experiment and group, and the test."""
        columns = ["experiment"] + list(RESULT_COLUMNS)
        lanes = [columns] + [[r.get("experiment", self.experiments[self.exp_index]["name"]) if c == "experiment" else r[c]
                              for c in columns] for r in rows]
        groups = candidate["groups"]
        if "experiment" not in rows[0]:
            rows = [{**r, "experiment": self.experiments[self.exp_index]["name"]} for r in rows]
        per = wbstats.per_experiment(rows, groups)
        table = [["experiment"] + groups] + [[e] + [by.get(g) for g in groups] for e, by in per.items()]
        test = stats.get("test") or {}
        summary = [["test", candidate["test_name"] if stats.get("test") else "No test"],
                   ["n per group", ", ".join(f"{g}={candidate['n'][g]}" for g in groups)]]
        summary += [[k, v] for k, v in test.items() if isinstance(v, (int, float))]
        summary += [[], ["group A", "group B", "p", "p (unadjusted)"]]
        summary += [[groups[c["i"]], groups[c["j"]], c["p"], c.get("p_unadjusted", c["p"])] for c in stats.get("comparisons", [])]
        summary += [[]] + [["warning", w] for w in stats.get("warnings", candidate.get("warnings", []))]
        xlsx.write(path, [("Lanes", lanes), ("Per experiment", table), ("Statistics", summary)])

    def _retranslate(self) -> None:
        self.setWindowTitle(i18n.tr("wb.title"))
        self._sample_headers()
        self._result_headers()
        self.graph_view.setToolTip(i18n.tr("wb.graph_hint"))
        self.warning_label.setText("\n".join(warning_text(w) for w in self.warnings))
        self._refresh_strip_texts()
        self._draw()
