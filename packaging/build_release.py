"""Build the lab release (docs/PLAN.md §4-41): PyInstaller folder, licence texts, setup.exe.

  tools\\uv.cmd run --no-sync python packaging\\build_release.py

Needs Inno Setup's ISCC.exe in tools\\innosetup (portable install). Output:
output\\installer\\LuXcale-1.0.3-setup.exe
"""

from importlib import metadata
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "output" / "dist" / "LuXcale"
STAGE = ROOT / "output" / "installer-stage"
ISCC = ROOT / "tools" / "innosetup" / "ISCC.exe"


def needed() -> list[metadata.Distribution]:
    """imquant's run-time dependencies and theirs (no extras), as installed."""
    seen, todo, out = set(), ["imquant"], []
    while todo:
        name = re.sub(r"[-_.]+", "-", todo.pop()).lower()
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        out.append(dist)
        for req in dist.requires or []:
            if "extra ==" not in req and "sys_platform == \"darwin\"" not in req:
                todo.append(re.match(r"[A-Za-z0-9_.-]+", req)[0])
    return [d for d in out if d.metadata["Name"] != "imquant"]


def licences() -> list[str]:
    """Copy the licence files of everything the build carries."""
    out = STAGE / "licenses"
    copied = []
    for dist in needed():
        files = [f for f in dist.files or [] if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING", "NOTICE"))]
        for f in files:
            target = out / dist.metadata["Name"] / f.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dist.locate_file(f), target)
        if files:
            copied.append(dist.metadata["Name"])
    python = Path(sys.base_prefix) / "LICENSE.txt"
    if python.exists():
        (out / "Python").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(python, out / "Python" / "LICENSE.txt")
        copied.append("Python")
    return copied


def main() -> int:
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "LuXcale.spec"), "--noconfirm",
                    "--distpath", str(ROOT / "output" / "dist"), "--workpath", str(ROOT / "output" / "build")],
                   check=True, cwd=ROOT)
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging" / "NOTICE.txt", STAGE / "NOTICE.txt")
    print("licences:", ", ".join(sorted(licences())))
    if not ISCC.exists():
        print(f"no {ISCC}: install Inno Setup there (portable) to make setup.exe")
        return 1
    subprocess.run([str(ISCC), str(ROOT / "packaging" / "LuXcale.iss")], check=True)
    print(ROOT / "output" / "installer" / "LuXcale-1.0.3-setup.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
