"""LuXcale.exe: the Western blot window (docs/PLAN.md §4-41); `LuXcale.exe --smoke SETTINGS OUT` checks an install."""

from pathlib import Path
import sys
import traceback

from imquant.ui.wb_app import main  # not imquant.__main__: that would bundle the confocal side (§4-57)

if "--smoke" in sys.argv:  # no error dialog in the install check: the traceback goes to OUT/error.txt
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        out = Path(sys.argv[sys.argv.index("--smoke") + 2])
        out.mkdir(parents=True, exist_ok=True)
        (out / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        sys.exit(1)
sys.exit(main(sys.argv[1:]))
