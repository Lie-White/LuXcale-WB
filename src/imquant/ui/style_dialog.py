"""The graph Style window (docs/PLAN.md §4-18), shared by the main window and the WB window (§4-36)."""

from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit,
)

from imquant.graphs import FONTS, GraphStyle
from imquant.ui import i18n, widgets


def style_dialog(parent, style: GraphStyle, groups: list[str]) -> tuple[QDialog, "callable"]:
    """The Style window showing `style`, with a colour button per group, and a function reading
    the GraphStyle it shows (tests read it directly)."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(i18n.tr("graph.style"))
    form = QFormLayout(dialog)

    def combo(items, current):
        box = QComboBox()
        for key, data in items:
            box.addItem(i18n.tr(key), data)
        box.setCurrentIndex(max(0, box.findData(current)))
        return box

    kind = combo((("style.bar", "bar"), ("style.mean_line", "mean_line"), ("style.box", "box"), ("style.violin", "violin")), style.kind)
    error = combo((("style.sd", "sd"), ("style.sem", "sem"), ("style.ci95", "ci95")), style.error)
    dots = QCheckBox(i18n.tr("style.dots"))
    dots.setChecked(style.dots)
    dot_size = QDoubleSpinBox()
    dot_size.setRange(1, 200)
    dot_size.setValue(style.dot_size)
    colors = combo((("style.grey", "grey"), ("style.colour", "colour"), ("style.custom", "custom")), style.colors)
    custom = dict(style.custom_colors)
    swatches = QHBoxLayout()
    for g in groups:
        b = widgets.button("action", text=g)
        b.setStyleSheet(f"border-left: 10px solid {custom.get(g, '#888888')};")

        def pick(_=False, g=g, b=b):
            chosen = QColorDialog.getColor(QColor(custom.get(g, "#888888")), dialog)
            if chosen.isValid():
                custom[g] = chosen.name()
                b.setStyleSheet(f"border-left: 10px solid {custom[g]};")
                colors.setCurrentIndex(colors.findData("custom"))
        b.clicked.connect(pick)
        swatches.addWidget(b)
    significance = combo((("style.stars", "stars"), ("style.p", "p"), ("style.none", "none")), style.significance)
    y_min, y_max = QLineEdit("" if style.y_min is None else repr(style.y_min)), QLineEdit("" if style.y_max is None else repr(style.y_max))
    for e in (y_min, y_max):
        e.setValidator(QDoubleValidator(e))
        e.setPlaceholderText(i18n.tr("style.auto"))
    y_label = QLineEdit(style.y_label)
    y_label.setPlaceholderText(i18n.tr("style.auto"))
    font = QDoubleSpinBox()
    font.setRange(5, 24)
    font.setDecimals(1)
    font.setValue(style.font_size)
    family = QComboBox()
    for name in FONTS:
        family.addItem(name, name)
    family.setCurrentIndex(max(0, family.findData(style.font)))
    family.setToolTip(i18n.tr("style.family.tip"))
    width, height = QDoubleSpinBox(), QDoubleSpinBox()
    for s, v in ((width, style.width_in), (height, style.height_in)):
        s.setRange(1, 12)
        s.setDecimals(1)
        s.setSuffix(" in")
        s.setValue(v)
    for key, w in (("style.kind", kind), ("style.error", error), ("", dots), ("style.dot_size", dot_size),
                   ("style.colors", colors), ("", swatches), ("style.significance", significance),
                   ("style.y_min", y_min), ("style.y_max", y_max), ("style.y_label", y_label),
                   ("style.family", family), ("style.font", font), ("style.width", width), ("style.height", height)):
        form.addRow(i18n.tr(key) if key else "", w)
    row = QHBoxLayout()
    ok, cancel = widgets.button("action", "ok"), widgets.button("action", "cancel")
    ok.clicked.connect(dialog.accept)
    cancel.clicked.connect(dialog.reject)
    row.addStretch(1)
    row.addWidget(cancel)
    row.addWidget(ok)
    form.addRow(row)
    number = lambda e: float(e.text()) if e.text().strip() else None  # noqa: E731

    def read() -> GraphStyle:
        return GraphStyle(kind.currentData(), error.currentData(), dots.isChecked(), dot_size.value(),
                          colors.currentData(), dict(custom), significance.currentData(), number(y_min), number(y_max),
                          y_label.text().strip(), font.value(), width.value(), height.value(), family.currentData())
    dialog.controls = {"kind": kind, "error": error, "dots": dots, "dot_size": dot_size, "colors": colors,
                       "significance": significance, "y_min": y_min, "y_max": y_max, "y_label": y_label,
                       "font": font, "width": width, "height": height, "family": family}
    return dialog, read

