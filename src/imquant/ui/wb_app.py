"""The Western blot window on its own: the lab release (docs/PLAN.md §4-41).

`launch` opens it the way the installed LuXcale.exe does: Korean unless the user switched, and the
settings in the data folder (%LOCALAPPDATA%\\LuXcale when installed). `smoke` runs a saved WB
settings.json without a window, to check an installed copy end to end. `main` is the command line
(`python -m imquant.ui.wb_app`); it imports nothing from the confocal side (§4-57).
"""

import argparse
import csv
import json
import os
from pathlib import Path

import imquant
from imquant import __version__


def data_dir() -> Path:
    """Where settings live: C:\\Imaging\\tools in development, the user's LuXcale folder installed."""
    return Path(imquant._TOOLS)


def settings_path() -> Path:
    return data_dir() / "settings.json"


def results_root() -> Path:
    """The default results folder; every save still asks where (§4-35)."""
    return Path.home() / "Documents" / "LuXcale"


def _read() -> dict:
    path = settings_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def window():
    """The WB window with the language from settings (Korean by default) and a language button."""
    from imquant.ui import i18n, widgets
    from imquant.ui.wb_window import WBWindow

    i18n.set_language(_read().get("language", "ko"))
    win = WBWindow(results_root, settings_path)
    lang = widgets.button("action", "language")

    def switch():
        i18n.set_language("ko" if i18n.language() == "en" else "en")
        _write({**_read(), "language": i18n.language()})

    lang.clicked.connect(switch)
    win.statusBar().addPermanentWidget(lang)
    win.lang_button = lang
    return win


def launch() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from imquant.ui import theme

    app = QApplication.instance() or QApplication([])
    app.setApplicationDisplayName(f"{theme.APP_NAME} {__version__}")
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.ico")))
    app.setStyleSheet(theme.STYLESHEET)
    win = window()
    win.showMaximized()
    return app.exec()


def smoke(settings_file: Path, out: Path) -> int:
    """Build the window off screen, open the blots of a saved WB settings.json, compute them and
    write results.csv, results.xlsx and the graph to `out`. 0 when everything ran."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from imquant import wb, wbstats, xlsx
    from imquant.graphs import dot_bar

    app = QApplication.instance() or QApplication([])
    settings = json.loads(Path(settings_file).read_text(encoding="utf-8"))
    win = window()
    for blot in settings["blots"]:
        if not win.open_blot(Path(blot["path"])):
            print(f"could not open {blot['path']}")
            return 1
    rows, warnings = wb.run_experiments(settings)
    if not rows:
        print("no rows: " + "; ".join(warnings))
        return 1
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    xlsx.write(out / "results.xlsx", [("Lanes", [columns] + [[r[c] for c in columns] for r in rows])])
    groups = list(dict.fromkeys(r["group"] for r in rows))
    candidate, stats = wbstats.combine(rows, groups, "experiment", "WB", warnings)
    dot_bar(candidate, candidate["values"], stats, out / "graph")
    (out / "version.txt").write_text(__version__, encoding="utf-8")
    win.close()
    app.processEvents()
    print(f"ok {len(rows)} rows, LuXcale {__version__}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="LuXcale", description="the Western blot window")
    p.add_argument("--smoke", nargs=2, type=Path, metavar=("SETTINGS", "OUT"),
                   help="no window: run a saved WB settings.json and write the results to OUT (install check)")
    args = p.parse_args(argv)
    return smoke(*args.smoke) if args.smoke else launch()


if __name__ == "__main__":
    raise SystemExit(main())
