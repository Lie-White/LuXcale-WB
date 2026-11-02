"""Western blot band quantification (docs/PLAN.md §4-21).

Numbers come only from the imager's raw 16-bit chemiluminescence TIF; JPGs and the colorimetric
membrane photo are for looking at. Lanes are set by the user (count, first and last centre,
width, evenly spaced) because touching bands defeat automatic splitting. In each lane, a band
window's columns are summed into a vertical profile, a straight baseline joining the window's
two ends is subtracted, and the rest is added up (the idea of ImageJ's Gel Analyzer). A window
may hold several bands (p44/p42): the total uses the window's own baseline, and each band is
the part of the baseline-subtracted profile on its side of a split row (a perpendicular drop).

Two baselines (§4-60): "ends", the straight line above, and "hull", the lower convex hull of the
profile, which never rises above it, so no row and no band can come out negative even when a
window's end touches another band. The WB window uses "hull"; settings saved without a
"background" (before §4-60) are re-run with "ends" and give the same numbers as before.
"""

from dataclasses import dataclass, field
import math
from pathlib import Path

import numpy as np
import tifffile

END_ROWS = 3  # rows averaged at each end of a window for the baseline's end values
BACKGROUNDS = ("ends", "hull")


@dataclass
class Blot:
    image: np.ndarray        # raw values as float64, (Y, X)
    saturation: float        # the detector's top value (65535 for 16-bit)
    method: str              # "Chemiluminescence", "Colorimetric", … from the imager's description
    path: Path | None = None
    clipped: np.ndarray | None = None  # where raw saturated pixels land after turning (§4-43)


def read_blot(path: Path) -> Blot:
    """A raw blot image. Refuses what would give wrong numbers: JPGs (display-scaled, lossy),
    8-bit or colour images, and the imager's colorimetric membrane photo."""
    path = Path(path)
    if path.suffix.lower() not in (".tif", ".tiff"):
        raise ValueError(f"{path.name}: quantify the raw TIF, not a {path.suffix} (display-scaled) picture")
    with tifffile.TiffFile(path) as tif:
        raw = tif.asarray()
        tag = tif.pages[0].tags.get("ImageDescription")
        description = str(tag.value) if tag is not None else ""
    if raw.ndim != 2 or raw.dtype != np.uint16:
        raise ValueError(f"{path.name}: expected one 16-bit channel, got {raw.dtype} {raw.shape}")
    method = next((line.split("=", 1)[1].strip() for line in description.splitlines()
                   if line.strip().lower().startswith("method")), "")
    if method.lower() == "colorimetric":
        raise ValueError(f"{path.name}: this is the membrane photo (colorimetric); quantify the chemiluminescence TIF")
    return Blot(raw.astype(np.float64), float(np.iinfo(np.uint16).max), method, path)


@dataclass
class Lanes:
    """`count` lanes of `width` px, centres evenly spaced from `first` to `last` (x, px). Each lane
    may be moved off that grid by `shifts` (px) and have its own width in `widths` (§4-45);
    empty lists = none (older settings)."""
    count: int
    first: float
    last: float
    width: float
    shifts: list = field(default_factory=list)
    widths: list = field(default_factory=list)

    def centres(self) -> list[float]:
        if self.count == 1:
            even = [self.first]
        else:
            step = (self.last - self.first) / (self.count - 1)
            even = [self.first + i * step for i in range(self.count)]
        return [c + s for c, s in zip(even, self.shifts)] if self.shifts else even

    def width_of(self, i: int) -> float:
        return self.widths[i] if self.widths else self.width

    def columns(self, i: int) -> tuple[int, int]:
        """Lane i's columns [x0, x1)."""
        x0 = int(math.floor(self.centres()[i] - self.width_of(i) / 2 + .5))
        return x0, x0 + int(round(self.width_of(i)))


@dataclass
class Window:
    """Rows [top, bottom) holding one band, or several split at `splits` (rows, ascending);
    `names` has one name per band (len(splits) + 1). `lanes`: this window's own lane boxes
    (§4-51), None = the blot's."""
    names: list[str]
    top: int
    bottom: int
    splits: list[int] = field(default_factory=list)
    lanes: Lanes | None = None

    def __post_init__(self) -> None:
        if isinstance(self.lanes, dict):
            self.lanes = Lanes(**self.lanes)
        if len(self.names) != len(self.splits) + 1:
            raise ValueError("a window needs one name per band (one more than its splits)")
        if not self.top + 2 * END_ROWS < self.bottom or any(not self.top < s < self.bottom for s in self.splits) \
                or any(a >= b for a, b in zip(self.splits, self.splits[1:])):  # ascending (§4-52)
            raise ValueError("window rows out of order")

    @property
    def total_name(self) -> str:
        return " + ".join(self.names)


def rotate(image: np.ndarray, angle: float) -> np.ndarray:
    """The image turned about its centre so a band tilted by `angle` (degrees, see
    wbfigure.level_angle) lies level: bilinear, edges repeated."""
    from scipy import ndimage

    if angle == 0:
        return np.asarray(image, np.float64).copy()
    t = math.radians(angle)
    cos, sin = math.cos(t), math.sin(t)
    h, w = image.shape
    centre = np.array([(h - 1) / 2, (w - 1) / 2])
    m = np.array([[cos, sin], [-sin, cos]])  # (y, x) of the output -> (y, x) of the input
    return ndimage.affine_transform(np.asarray(image, np.float64), m, offset=centre - m @ centre,
                                    order=1, mode="nearest")


def turned(blot: Blot, angle: float) -> Blot:
    """The blot measured level (§4-43): the raw image turned by `angle`, with every place a
    saturated raw pixel reaches still marked saturated (interpolation would shave 65535 off).
    The raw file is never written."""
    if not angle:
        return blot
    clipped = rotate((blot.image >= blot.saturation).astype(np.float64), angle) > 0
    return Blot(rotate(blot.image, angle), blot.saturation, blot.method, blot.path, clipped)


def profile(image: np.ndarray, lanes: Lanes, i: int, window: Window) -> np.ndarray:
    x0, x1 = lanes.columns(i)
    return image[window.top:window.bottom, x0:x1].sum(axis=1)


def baseline(p: np.ndarray) -> np.ndarray:
    """The straight line through the mean of the first and of the last END_ROWS values."""
    k = END_ROWS
    y = np.arange(len(p), dtype=np.float64)
    a, b = (k - 1) / 2, len(p) - 1 - (k - 1) / 2
    left, right = p[:k].mean(), p[-k:].mean()
    return left + (right - left) * (y - a) / (b - a)


def hull_baseline(p: np.ndarray) -> np.ndarray:
    """The lower convex hull of the points (row, p[row]), joined by straight lines: the highest
    convex line that is nowhere above the profile (§4-60)."""
    p = np.asarray(p, np.float64)
    low: list[int] = []
    for i in range(len(p)):  # Andrew's monotone chain, lower half
        while len(low) >= 2 and ((low[-1] - low[-2]) * (p[i] - p[low[-2]])
                                 - (p[low[-1]] - p[low[-2]]) * (i - low[-2])) <= 0:
            low.pop()
        low.append(i)
    line = np.interp(np.arange(len(p)), low, p[low])
    return np.minimum(line, p)  # rounding in the interpolation never lifts it above a row


def measure(blot: Blot, lanes: Lanes, windows: list[Window], background: str = "ends") -> list[dict]:
    """One row per lane × band, plus the window total when it holds more than one band. A window
    with its own lanes is measured in its own boxes (§4-51); every window has the blot's lane count.
    `background`: "ends" (the straight line between the window's ends) or "hull" (§4-60)."""
    if background not in BACKGROUNDS:
        raise ValueError(f"unknown background {background!r}")
    for w in windows:
        if w.lanes is not None and w.lanes.count != lanes.count:
            raise ValueError(f"band {w.total_name} has {w.lanes.count} lanes, its blot {lanes.count}")
    rows = []
    for i in range(lanes.count):
        for w in windows:
            own = w.lanes or lanes
            x0, x1 = own.columns(i)
            if x0 < 0 or x1 > blot.image.shape[1]:
                raise ValueError(f"lane {i + 1} runs off the image")
            p = profile(blot.image, own, i, w)
            signal = p - (hull_baseline(p) if background == "hull" else baseline(p))
            clipped = blot.image >= blot.saturation if blot.clipped is None else blot.clipped
            saturated = bool(clipped[w.top:w.bottom, x0:x1].any())
            edges = [0] + [s - w.top for s in w.splits] + [len(p)]
            parts = [(name, float(signal[a:b].sum())) for name, (a, b) in zip(w.names, zip(edges, edges[1:]))]
            if len(parts) > 1:
                parts.append((w.total_name, float(signal.sum())))
            for name, value in parts:
                rows.append({"lane": i + 1, "band": name, "value": value, "saturated": saturated,
                             "x0": x0, "x1": x1, "top": w.top, "bottom": w.bottom})
    return rows


def normalise(target: list[dict], loading: list[dict], band: str, loading_band: str,
              groups: list[str], control: str, *, same_gel: bool,
              replicates: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Target ÷ the same lane's loading control, then ÷ the control group's mean of that ratio.
    `groups` and `replicates` name each lane in order; by default every lane is its own
    independent replicate. Returns (rows, warnings)."""
    value = lambda rows, b: {r["lane"]: r for r in rows if r["band"] == b}  # noqa: E731
    t, l = value(target, band), value(loading, loading_band)
    lanes = sorted(t)
    if len(groups) != len(lanes) or sorted(l) != lanes:
        raise ValueError("target, loading control and groups must cover the same lanes")
    replicates = replicates or [f"lane {n}" for n in lanes]
    ratio = {n: t[n]["value"] / l[n]["value"] for n in lanes}
    control_lanes = [n for n, g in zip(lanes, groups) if g == control]
    if not control_lanes:
        raise ValueError(f"no lane is in the control group {control!r}")
    base = math.fsum(ratio[n] for n in control_lanes) / len(control_lanes)
    warnings = []
    if not same_gel:
        warnings.append("Loading control from a different gel: assumes the same amount was loaded on each gel")
    saturated = [n for n in lanes if t[n]["saturated"] or l[n]["saturated"]]
    if saturated:
        warnings.append(f"Saturated pixels in lanes {saturated}: those values are underestimated")
    rows = [{"lane": n, "group": g, "replicate": r, "target": t[n]["value"], "loading": l[n]["value"],
             "ratio": ratio[n], "relative": ratio[n] / base}
            for n, g, r in zip(lanes, groups, replicates)]
    return rows, warnings


def windows_of(blot: dict) -> list[Window]:
    """A blot's band windows: `windows` (§4-24), or the single `window` of older settings (§4-22)."""
    return [Window(**w) for w in blot["windows"]] if "windows" in blot else [Window(**blot["window"])]


def run(settings: dict) -> tuple[list[dict], list[str]]:
    """Measure and normalise from a settings dict (what the WB window shows and saves):
    {"blots": [{"path", "name", "same_gel", "angle", "lanes": {...}, "windows": [{...}, ...]}],
     "loading": {"blot": i, "band": name}, "target": {"blot": i, "band": name},
     "samples": [{"name", "group", "replicate"}], "reference": group}.
    Older settings (§4-22: one `window` per blot, the loading blot marked `"loading": true`,
    its window's total as the band) still run. Re-running a saved file gives the same numbers."""
    blots = settings["blots"]
    loading = settings.get("loading")
    if loading is None:
        marked = [i for i, b in enumerate(blots) if b.get("loading")]
        if len(marked) != 1:
            raise ValueError("mark exactly one blot as the loading control")
        loading = {"blot": marked[0], "band": windows_of(blots[marked[0]])[0].total_name}
    measured = {}

    def rows_of(i: int) -> list[dict]:
        if i not in measured:
            b = blots[i]
            raw = turned(read_blot(Path(b["path"])), b.get("angle", 0.0))  # level first (§4-43)
            measured[i] = measure(raw, Lanes(**b["lanes"]), windows_of(b), settings.get("background", "ends"))
        return measured[i]

    t = settings["target"]
    if (t["blot"], t["band"]) == (loading["blot"], loading["band"]):
        raise ValueError("the target is the loading control")
    samples = settings["samples"]
    # Target and loading control on one blot are on one membrane: no different-gel warning.
    same_gel = t["blot"] == loading["blot"] or bool(blots[t["blot"]].get("same_gel"))
    rows, warnings = normalise(rows_of(t["blot"]), rows_of(loading["blot"]), t["band"], loading["band"],
                               [s["group"] for s in samples], settings["reference"], same_gel=same_gel,
                               replicates=[s["replicate"] or f"lane {n}" for n, s in enumerate(samples, 1)])
    for i in sorted({t["blot"], loading["blot"]}):  # §4-45: unequal boxes can cover unequal parts of bands
        every = [Lanes(**blots[i]["lanes"])] + [w.lanes for w in windows_of(blots[i]) if w.lanes]
        if any(lanes.widths and len(set(lanes.widths)) > 1 for lanes in every):
            warnings.append(f"Lane widths differ on {blots[i].get('name') or Path(blots[i]['path']).stem}: "
                            "check each box covers its whole band")
    for row, s in zip(rows, samples):
        row["sample"] = s["name"]
    return rows, warnings


def experiments_of(settings: dict) -> list[dict]:
    """The settings' experiments (§4-38); older settings (one target, loading, sample table and
    reference at the top level) are one experiment."""
    if settings.get("experiments"):
        return settings["experiments"]
    return [{"name": settings.get("name", "1"), **{k: settings[k] for k in ("target", "loading", "samples", "reference")
                                                   if k in settings}}]


def run_experiments(settings: dict) -> tuple[list[dict], list[str]]:
    """Every experiment normalised on its own (its target ÷ the same lane's loading control ÷
    its own reference group's mean), rows tagged with "experiment" (§4-38). Warnings name the
    experiment when there are several."""
    every = experiments_of(settings)
    seen: dict = {}
    for e in every:  # one target band in two experiments would count the same data twice (§4-39)
        t = e.get("target") or {}
        if t:
            key = (t["blot"], t["band"])
            if key in seen:
                raise ValueError(f"experiments {seen[key]} and {e['name']} use the same target band; "
                                 "pick each experiment's own blot")
            seen[key] = e["name"]
    rows, warnings = [], []
    for e in every:
        if not e.get("target") or not e.get("loading"):
            warnings.append(f"{e['name']}: pick its target band and loading control again (left out)")
            continue
        got, said = run({"blots": settings["blots"], "background": settings.get("background", "ends"), **e})
        rows += [{"experiment": e["name"], **r} for r in got]
        warnings += [f"{e['name']}: {w}" if len(every) > 1 else w for w in said]
    return rows, warnings


def fit(image: np.ndarray, x: float, y: float, count: int, current: Lanes | None = None) -> tuple[Lanes, int, int]:
    """A suggested lane grid and band window (top, bottom) for the band clicked at (x, y)
    (docs/PLAN.md §4-25). `count` lanes, evenly spaced; lanes with no signal (empty controls)
    are put on the side nearer the `current` grid. Raises ValueError if no band is there."""
    from scipy import ndimage, signal

    h, w = image.shape
    smooth = ndimage.gaussian_filter(np.asarray(image, np.float64), 1.5)
    # Up/down: the row profile across the current lanes (or near the click).
    if current is not None:
        x0, x1 = max(0, current.columns(0)[0]), min(w, current.columns(current.count - 1)[1])
    else:
        x0, x1 = max(0, int(x) - 150), min(w, int(x) + 150)
    rows = smooth[:, x0:x1].mean(axis=1)
    lo, hi = max(0, int(y) - 20), min(h, int(y) + 21)
    peak = lo + int(np.argmax(rows[lo:hi]))
    # Background under the band: the straight line through the lowest row on each side within
    # 100 px (a flat minimum never comes back down on a sloping background).
    a0, b1 = max(0, peak - 100), min(h, peak + 101)
    ya = a0 + int(np.argmin(rows[a0:peak + 1]))
    yb = peak + int(np.argmin(rows[peak:b1]))
    yy = np.arange(h, dtype=np.float64)
    line = rows[ya] + (rows[yb] - rows[ya]) * (yy - ya) / max(yb - ya, 1)
    rest = rows - line
    height = rest[peak]
    noise = 1.4826 * np.median(np.abs(np.diff(rows[a0:b1]))) / np.sqrt(2)
    if height <= 20 * max(noise, 1e-9) or height < .03 * (np.percentile(image, 99.9) - np.median(image)):
        raise ValueError("no band where you clicked")
    edge = .05 * height
    top, bottom = peak, peak
    while top > ya and rest[top] > edge:
        top -= 1
    while bottom < yb and rest[bottom] > edge:
        bottom += 1
    if top <= a0 and a0 > 0 or bottom >= b1 - 1 and b1 < h:
        raise ValueError("no band where you clicked")
    top, bottom = max(0, top - 6), min(h, bottom + 7)
    # Sideways: each column's background from the rows just above and below the window, so a
    # sideways slope or bands covering most of the width (touching lanes) do not shift the
    # threshold. Separate runs of signal are lanes: their centres give the spacing and phase.
    # One run (all lanes touching; between unequal neighbours there is often no valley at
    # all) is split evenly into `count` lanes.
    outside = np.concatenate([smooth[max(0, top - 8):max(0, top - 2)], smooth[bottom + 2:bottom + 8]])
    cols = smooth[top:bottom].sum(axis=0) - (bottom - top) * outside.mean(axis=0)
    labels, n = ndimage.label(cols > .2 * cols.max())
    runs = [np.flatnonzero(labels == k + 1) for k in range(n)]
    runs = [r for r in runs if len(r) >= 5]
    if runs:
        typical = float(np.median([len(r) for r in runs]))
        runs = [r for r in runs if len(r) >= .3 * typical]  # specks, not lanes
    if not runs:
        raise ValueError("no band where you clicked")
    left, right = runs[0][0], runs[-1][-1] + 1
    starts = np.array([r[0] for r in runs], np.float64)
    lengths = np.array([len(r) for r in runs], np.float64)
    band = lengths.min()  # one lane's band width: the narrowest run
    best = None
    if len(runs) >= 2:
        # A run holds k touching lanes: length ≈ k·step − gap, gap = step − band. Every run
        # starts on the lane grid. Try each spacing; keep the largest one that fits (half the
        # spacing fits too, with every other lane empty).
        for step in np.arange(band + 2, right - left + 1, .5):
            k = np.maximum(1, np.round((lengths + step - band) / step))
            slot = np.round((starts - starts[0]) / step)
            lit = int(slot[-1] + k[-1])
            if lit > max(count, len(runs)) or np.any(np.diff(slot) < k[:-1]):
                continue
            if np.abs(starts - starts[0] - slot * step).max() <= max(3.0, .06 * step):
                best = (step, slot, lit)
    if best is not None:
        step, slot, lit = best
        first = float(np.mean(starts - slot * step)) + band / 2
    else:
        step = (right - left) / count
        first, lit = left + step / 2, count
    if lit > count:  # keep the lanes around the click
        k = int(np.clip(round((x - first) / step) - (count - 1) // 2, 0, lit - count))
        first += k * step
    elif lit < count:
        # Lanes left over: put them where their slots hold signal (a faint lane under the 20%
        # cut, §4-28); only when every choice is empty (< 5% of the strongest lane, e.g. empty
        # controls) on the side nearer the current grid.
        def slot(c: float) -> float:
            a, b = int(round(c - .35 * step)), int(round(c + .35 * step))
            return float(cols[max(a, 0):min(b, w)].mean()) if a < w and b > 0 else 0.0

        strongest = max(slot(first + j * step) for j in range(lit))
        options = [first - k * step for k in range(count - lit + 1)]
        options = [f for f in options if f - step / 2 >= 0 and f + (count - .5) * step <= w] or options
        extra = lambda f: [f + j * step for j in range(count)  # noqa: E731
                           if not first - step / 2 < f + j * step < first + (lit - .5) * step]
        signal_of = {f: sum(max(slot(c), 0.0) for c in extra(f)) for f in options}
        best = max(options, key=lambda f: signal_of[f])
        if signal_of[best] >= .05 * strongest:
            first = best
        else:
            first = min(options, key=lambda f: abs(f - current.first)) if current is not None else options[0]
    # On the bands (§4-44): the grid above starts from where runs begin, which drifts when runs
    # differ in width. Each lane with signal gives its band's centre (columns above 20% of its
    # own peak, weighted); a straight, evenly spaced line through them (weighted by amount)
    # gives first and last. Width = the bands' own width (columns above 10% of the lane's peak,
    # median, +2 px), never more than the spacing so ROIs do not overlap. Where neighbouring
    # bands touch (the valley between them, median over pairs, stays above 10% of the smaller
    # peak), at most 0.8 of the spacing: a wider ROI
    # takes in the neighbour's edge (synthetic touching bands: ratio error 1% at 0.8, 2% at
    # 0.85, 10% at the full spacing), while cutting the same edge off every band keeps ratios.
    widths, touching = [], False
    for _ in range(2):
        found = []
        for j in range(count):
            c = first + j * step
            a, b = max(0, int(round(c - step / 2))), min(w, int(round(c + step / 2)))
            seg = np.clip(cols[a:b], 0, None) if b > a else np.zeros(0)
            if seg.size and seg.max() > 0:
                above = np.clip(seg - .2 * seg.max(), 0, None)
                found.append((j, a + float((np.arange(len(seg)) * above).sum() / above.sum()), float(seg.sum()),
                              int((seg > .1 * seg.max()).sum())))
        strongest = max((f[2] for f in found), default=0.0)
        found = [f for f in found if f[2] >= .05 * strongest]
        if len(found) >= 2:
            j, centre, amount, _ = (np.array(v, np.float64) for v in zip(*found))
            step, first = (float(v) for v in np.polyfit(j, centre, 1, w=np.sqrt(amount)))
        elif found:
            first = found[0][1] - found[0][0] * step
        widths = [f[3] for f in found]
        peaks = {f[0]: float(np.clip(cols, 0, None)[max(0, int(round(f[1] - step / 2))):int(round(f[1] + step / 2))].max())
                 for f in found}
        valleys = []
        for j in peaks:
            a, b = int(round(first + j * step)), int(round(first + (j + 1) * step))
            if j + 1 in peaks and 0 <= a < b <= w:
                valleys.append(cols[a:b].min() / min(peaks[j], peaks[j + 1]))
        touching = bool(valleys) and float(np.median(valleys)) > .1  # most neighbours, not one smudge
    width = int(np.median(widths)) + 2 if widths else int(round(.85 * step))
    width = max(2, min(width, int(math.floor(.8 * step if touching else step))))
    lanes = Lanes(count, int(round(first)), int(round(first + (count - 1) * step)), width)
    if lanes.columns(0)[0] < 0 or lanes.columns(count - 1)[1] > w:
        raise ValueError("the fitted lanes run off the image")
    return lanes, top, bottom
