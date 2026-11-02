# PyInstaller build of the lab release (docs/PLAN.md §4-41): one folder, no console, WB only.
# Run from C:\Imaging:  tools\uv.cmd run --no-sync pyinstaller packaging\LuXcale.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).parent
# The confocal side's viewer and anything only tests or notebooks use.
EXCLUDE = ["napari", "vispy", "IPython", "jupyter_client", "tkinter", "pytest", "PyInstaller",
           "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
           "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
           "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtBluetooth",
           # The confocal side and what only it uses: the installer is the WB window alone (§4-57).
           "skimage", "liffile", "imquant.__main__", "imquant.ui.main", "imquant.ui.canvas",
           "imquant.ui.channel_card", "imquant.ui.open_dialog", "imquant.ui.splash", "imquant.cohort",
           "imquant.lasx", "imquant.measure", "imquant.session", "imquant.sources", "imquant.render",
           "imquant.corrections", "imquant.export", "imquant.recipe", "imquant.lut", "imquant.scalebar"]

a = Analysis([str(ROOT / "packaging" / "luxcale_entry.py")], pathex=[str(ROOT / "src")],
             datas=[(str(ROOT / "src" / "imquant" / "ui" / "assets"), "imquant/ui/assets")],
             excludes=EXCLUDE, noarchive=False,
             # matplotlib picks its file writers by name at save time (svg, pdf, png).
             hiddenimports=["matplotlib.backends.backend_svg", "matplotlib.backends.backend_pdf",
                            "matplotlib.backends.backend_agg", "matplotlib.backends.backend_qtagg"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LuXcale", console=False,
          icon=str(ROOT / "src" / "imquant" / "ui" / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="LuXcale")
