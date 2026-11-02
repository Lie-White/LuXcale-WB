"""LuXcale look (docs/UI-RULES.md): mid-dark greys that stay readable, raised buttons that sink
when pressed, one cyan accent from the logo's scale bar (#00F2FE)."""

from pathlib import Path

APP_NAME = "LuXcale"
ASSETS = Path(__file__).resolve().parent / "assets"

# Surfaces: only the image canvas is black.
BG = "#272b33"
PANEL = "#20242b"
TITLE = "#1a1d23"
RAISED = "#343a45"
INSET = "#181b20"
BORDER = "#3c424d"
BORDER_STRONG = "#4d5462"
# Text: bright enough on BG; muted text is still readable.
TEXT = "#e4e8ef"
TEXT_STRONG = "#ffffff"
TEXT_MUTED = "#a9b4c4"
ACCENT = "#00f2fe"
ACCENT_DEEP = "#0a7f88"
ON_ACCENT = "#05181b"
WARN = "#f0907c"
FONT_PX = 13

# Swatch colours for LAS X LUT names (display only; rendering uses the exact LUT weights).
LUT_SWATCH = {"Blue": "#3a6cf0", "Green": "#3fbf4f", "Yellow": "#ecd93c", "Red": "#e0453a", "Cyan": "#2fc6d6", "Magenta": "#d24bcc", "Gray": "#c4c4c4"}

# Raised button: light top, dark bottom, a highlight on the top edge and a shadow on the bottom.
_RAISED = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #535b69, stop:0.48 #414854, stop:1 #323844)"
_RAISED_HOVER = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #616a79, stop:0.48 #4c5461, stop:1 #3b424e)"
# Sunken: the same, upside down and darker.
_SUNKEN = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1d2026, stop:0.5 #2a2f37, stop:1 #353b46)"
_ON = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #075c63, stop:0.55 #0a8d97, stop:1 #12b9c4)"
_PRIMARY = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8ffaff, stop:0.45 #2cf3fd, stop:1 #00b9c4)"
_PRIMARY_DOWN = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #00939c, stop:1 #29e6f0)"


def _rule(role: str, body: str, state: str = "") -> str:
    return f'QPushButton[role="{role}"]{state} {{ {body} }}'


_raised = f"background: {_RAISED}; border: 1px solid #1b1e24; border-top-color: #6a7383; border-bottom-color: #121418; border-radius: 6px; padding: 5px 11px; color: {TEXT};"
_hover = f"background: {_RAISED_HOVER};"
_sunken = f"background: {_SUNKEN}; border-top-color: #0d0f12; border-bottom-color: #4f5665; padding-top: 6px; padding-bottom: 4px;"

STYLESHEET = "\n".join([
    f"QWidget {{ background: {BG}; color: {TEXT}; font-family: \"Segoe UI\", \"Malgun Gothic\"; font-size: {FONT_PX}px; }}",
    f"QMainWindow::separator {{ background: {BORDER_STRONG}; width: 6px; height: 6px; }}",
    f"QMainWindow::separator:hover {{ background: {ACCENT}; }}",
    f"QFrame#step {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}",
    f"QFrame#step QLabel {{ background: transparent; }}",
    f"QToolBar#titlebar {{ background: {TITLE}; border: none; border-bottom: 1px solid #0f1114; padding: 6px 12px; spacing: 8px; }}",
    # Only labels and the brand block go transparent; buttons keep their raised look.
    "QToolBar#titlebar QLabel, QWidget#brand, QWidget#group, QWidget#spacer { background: transparent; }",
    f"QToolBar::separator {{ background: {BORDER_STRONG}; width: 1px; margin: 8px 8px; }}",
    f"QStatusBar {{ background: {TITLE}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; font-size: 12px; }}",
    "QStatusBar QLabel { background: transparent; padding: 0 8px; }",
    # Buttons (docs/UI-RULES.md §1): action, toggle, primary.
    _rule("action", _raised), _rule("action", _hover, ":hover"), _rule("action", _sunken, ":pressed"),
    _rule("toggle", _raised), _rule("toggle", _hover, ":hover"), _rule("toggle", _sunken, ":pressed"),
    _rule("toggle", f"background: {_ON}; border: 1px solid {ACCENT}; border-top-color: #03393d; color: {TEXT_STRONG}; font-weight: 700; padding-top: 6px; padding-bottom: 4px;", ":checked"),
    _rule("toggle", "border: 1px solid #8ffaff;", ":checked:hover"),
    _rule("primary", f"background: {_PRIMARY}; border: 1px solid #006a72; border-top-color: #c9fdff; border-bottom-color: #00474d; border-radius: 6px; padding: 5px 16px; color: {ON_ACCENT}; font-weight: 700;"),
    _rule("primary", "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b0fcff, stop:0.45 #5cf6ff, stop:1 #10cad5);", ":hover"),
    _rule("primary", f"background: {_PRIMARY_DOWN}; border-top-color: #00474d; border-bottom-color: #c9fdff; padding-top: 6px; padding-bottom: 4px;", ":pressed"),
    "QPushButton::menu-indicator { subcontrol-position: right center; right: 6px; }",
    # Lists, inputs, cards.
    f"QTreeWidget, QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 2px; }}",
    "QTreeWidget::item { padding: 3px 2px; }",
    f"QTreeWidget::item:selected, QListWidget::item:selected {{ background: {ACCENT_DEEP}; color: {TEXT_STRONG}; }}",
    f"QTreeWidget::item:hover, QListWidget::item:hover {{ background: {RAISED}; }}",
    f"QHeaderView::section {{ background: {PANEL}; color: {TEXT_MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px 6px; font-size: 12px; }}",
    f"QScrollArea {{ background: {BG}; border: none; }}",
    f"QDoubleSpinBox, QSpinBox {{ background: {INSET}; border: 1px solid {BORDER_STRONG}; border-radius: 4px; padding: 2px 5px; color: {TEXT_STRONG}; selection-background-color: {ACCENT_DEEP}; }}",
    f"QSlider::groove:horizontal {{ height: 4px; background: {INSET}; border-radius: 2px; }}",
    f"QSlider::sub-page:horizontal {{ background: {ACCENT_DEEP}; border-radius: 2px; }}",
    f"QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; background: {_RAISED}; border: 1px solid #121418; border-radius: 7px; }}",
    f"QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}",
    "QFrame#card QLabel { background: transparent; }",
    f"QLabel#muted {{ color: {TEXT_MUTED}; font-size: 12px; }}",
    f"QLabel#strong {{ color: {TEXT_STRONG}; font-weight: 600; }}",
    f"QLabel#section {{ color: {TEXT_MUTED}; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }}",
    f"QLabel#warn {{ color: {WARN}; }}",
    f"QLabel#appname {{ color: {TEXT_STRONG}; font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }}",
    f"QLabel#tagline {{ color: {TEXT_MUTED}; font-size: 11px; letter-spacing: 1px; }}",
    f"QMenu {{ background: {RAISED}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}",
    f"QMenu::item {{ padding: 5px 18px; }} QMenu::item:selected {{ background: {ACCENT_DEEP}; }}",
    "QCheckBox::indicator { width: 14px; height: 14px; }",
])


def channel_toggle_style(color: str) -> str:
    """A channel panel toggle: neutral and raised with a stripe of the channel colour when off;
    sunken and filled with the channel colour when on (dark or light text for contrast)."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    text = "#101215" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else TEXT_STRONG
    on = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_shade(color, 0.55)}, stop:0.55 {_shade(color, 0.85)}, stop:1 {color})"
    return (
        f'QPushButton[role="toggle"] {{ border-left: 4px solid {color}; }}'
        f'QPushButton[role="toggle"]:checked {{ background: {on}; color: {text}; border: 1px solid {TEXT_STRONG}; border-left: 4px solid {TEXT_STRONG}; }}'
    )


def _shade(color: str, k: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(int(r * k), int(g * k), int(b * k))
