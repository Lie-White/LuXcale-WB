"""The new-version notice (docs/PLAN.md §4-65): ask GitHub for LuXcale-WB's latest release, and
download its installer only when its size and SHA-256 match. Nothing about the user or the
blots is sent; any failure means "no notice", never an error window."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import urllib.request

REPO = "Lie-White/LuXcale-WB"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"  # the only place an installer comes from
PAGE = f"https://github.com/{REPO}/releases/latest"
TIMEOUT = 5  # seconds for the question; the download gets longer


@dataclass
class Update:
    version: str
    url: str | None  # the installer, or None: then the button opens PAGE
    size: int
    sha256: str | None


def version(text: str) -> tuple[int, ...] | None:
    """"v1.0.4" or "1.0.4" -> (1, 0, 4); anything else -> None."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(text).strip())
    return tuple(int(g) for g in m.groups()) if m else None


def newer(release: dict, current: str) -> Update | None:
    """The release as an Update when its tag is above `current`."""
    tag, now = version(release.get("tag_name", "")), version(current)
    if tag is None or now is None or tag <= now:
        return None
    asset = next((a for a in release.get("assets") or []
                  if re.fullmatch(r"LuXcale-[\d.]+-setup\.exe", str(a.get("name", "")))), None)
    url = str(asset.get("browser_download_url", "")) if asset else ""
    if not url.startswith(DOWNLOADS):
        return Update(".".join(map(str, tag)), None, 0, None)
    digest = str(asset.get("digest") or "")
    sha = digest[len("sha256:"):] if digest.startswith("sha256:") else None
    if sha is None:  # the release notes' "SHA-256 (…): `…`" line
        m = re.search(r"SHA-256[^`\n]*`([0-9a-fA-F]{64})`", str(release.get("body") or ""))
        sha = m.group(1) if m else None
    return Update(".".join(map(str, tag)), url, int(asset.get("size") or 0), sha.lower() if sha else None)


def latest(current: str, opener=urllib.request.urlopen) -> Update | None:
    """Ask GitHub; None when there is nothing newer or anything goes wrong."""
    request = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "LuXcale"})
    try:
        with opener(request, timeout=TIMEOUT) as response:
            release = json.load(response)
    except (OSError, ValueError):
        return None
    return newer(release, current) if isinstance(release, dict) else None


def download(update: Update, folder: Path, opener=urllib.request.urlopen, progress=None) -> Path | None:
    """The installer in `folder` when its size and SHA-256 match the release; otherwise nothing
    is kept and None is returned. `progress(done, total)` is called as it arrives."""
    if not update.url or not update.url.startswith(DOWNLOADS) or not update.sha256:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / update.url.rsplit("/", 1)[-1]
    digest, done = hashlib.sha256(), 0
    try:
        request = urllib.request.Request(update.url, headers={"User-Agent": "LuXcale"})
        with opener(request, timeout=60) as response, path.open("wb") as out:
            while chunk := response.read(1 << 16):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, update.size)
    except OSError:
        path.unlink(missing_ok=True)
        return None
    if done != update.size or digest.hexdigest() != update.sha256:
        path.unlink(missing_ok=True)
        return None
    return path
