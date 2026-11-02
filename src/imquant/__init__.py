"""Image quantification to publication-ready graphs."""

import os
from pathlib import Path
import sys

__version__ = "1.0.3"

# Keep every settings and cache file inside the project (C:\Imaging\tools\...) instead of the
# user's AppData, unless the caller chose a location. This must run before matplotlib, napari or
# Qt is imported, which is why it lives here. The installed program (PyInstaller sets sys.frozen)
# has no project folder: it uses %LOCALAPPDATA%\LuXcale, or LUXCALE_DATA when set (§4-41).
if getattr(sys, "frozen", False):
    _TOOLS = Path(os.environ.get("LUXCALE_DATA") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "LuXcale")
    # PyInstaller's matplotlib hook points this at a temporary folder removed at exit, so the
    # font cache would be rebuilt at every start.
    os.environ["MPLCONFIGDIR"] = str(_TOOLS / "mplconfig")
else:
    _TOOLS = Path(__file__).resolve().parents[2] / "tools"
os.environ.setdefault("MPLCONFIGDIR", str(_TOOLS / "mplconfig"))
# platformdirs (used by napari and others) honours these overrides on Windows.
os.environ.setdefault("WIN_PD_OVERRIDE_LOCAL_APPDATA", str(_TOOLS / "appdata" / "Local"))
os.environ.setdefault("WIN_PD_OVERRIDE_APPDATA", str(_TOOLS / "appdata" / "Roaming"))
os.environ.setdefault("NAPARI_CONFIG", str(_TOOLS / "appdata" / "napari" / "settings.yaml"))
os.environ.setdefault("QT_API", "pyside6")
# Qt writes compiled OpenGL shaders to %LOCALAPPDATA%\<org>\<app>\cache, which the settings
# above do not reach; the napari viewer left one there (2026-10-28). No disk cache at all.
os.environ.setdefault("QT_DISABLE_SHADER_DISK_CACHE", "1")
