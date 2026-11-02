"""Levelling a blot and making a presentation or publication figure from it (docs/PLAN.md §4-27).

Only the figure is cropped and contrast-stretched; the numbers (imquant.wb) come from the raw
image, turned only by the blot's own levelling angle (§4-43), and the raw file is never written. Contrast is one linear stretch per strip,
strips from different windows or blots are always separated by a gap, and a JSON record holds
every angle, crop and contrast so the same figure can be rebuilt and described in Methods.
"""

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path

import numpy as np

from imquant import wb


def level_angle(image: np.ndarray, lanes: wb.Lanes, window: wb.Window) -> float:
    """The band's tilt in degrees (positive: rising to the left in the picture, i.e. y grows
    with x): a straight line through each lane's band centre of mass, weighted by its amount.
    Empty lanes (under 5% of the largest amount) are left out."""
    xs, ys, ws = [], [], []
    rows = np.arange(window.top, window.bottom, dtype=np.float64)
    for i, c in enumerate(lanes.centres()):
        p = wb.profile(image, lanes, i, window)
        s = np.clip(p - wb.baseline(p), 0, None)
        if s.sum() > 0:
            xs.append(c)
            ys.append(float((rows * s).sum() / s.sum()))
            ws.append(float(s.sum()))
    if not ws:
        return 0.0
    keep = [k for k, v in enumerate(ws) if v >= .05 * max(ws)]
    if len(keep) < 2:
        return 0.0
    x, y, w = (np.array([a[k] for k in keep]) for a in (xs, ys, ws))
    slope = np.polyfit(x, y, 1, w=np.sqrt(w))[0]
    return math.degrees(math.atan(slope))


def two_point_angle(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """The tilt in degrees of the line from p1 to p2 ((x, y), y down), folded into -90…90."""
    angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
    return (angle + 90) % 180 - 90


def _matrix(angle: float) -> tuple[float, float]:
    t = math.radians(angle)
    return math.cos(t), math.sin(t)


rotate = wb.rotate  # the same turn as the quantification's (§4-43)


def rotate_points(points, angle: float, shape) -> np.ndarray:
    """Where raw (x, y) points land in `rotate(image, angle)`."""
    cos, sin = _matrix(angle)
    h, w = shape
    cx, cy = (w - 1) / 2, (h - 1) / 2
    p = np.asarray(points, np.float64).reshape(-1, 2)
    dx, dy = p[:, 0] - cx, p[:, 1] - cy
    return np.stack([cx + cos * dx + sin * dy, cy - sin * dx + cos * dy], axis=1)


@dataclass
class Strip:
    """One band window cut out for the figure."""
    path: str
    angle: float
    lanes: dict
    window: dict
    lo: float
    hi: float
    label: str = ""
    kda: str = ""
    margin: int = 8
    auto: bool = False  # the angle came from levelling this strip's window (recorded only)
    ticks: list = field(default_factory=list)
    """Ladder marks of the strip's blot (§4-37): [x, y, kDa text] in raw image pixels."""
    extend: bool = False
    """Widen the strip up or down to the nearest ladder mark when none falls inside it."""
    base: float = 0.0
    """The blot's quantification angle (§4-43): `lanes` and `window` are rows and columns of the
    raw image turned by `base`; `angle` is still the whole turn from the raw image."""

    def tick_rows(self, shape) -> list[tuple[float, str]]:
        """(row in the rotated image, kDa text) of every ladder mark."""
        if not self.ticks:
            return []
        rows = rotate_points([(t[0], t[1]) for t in self.ticks], self.angle, shape)[:, 1]
        return [(float(r), str(t[2])) for r, t in zip(rows, self.ticks)]

    def box(self, shape) -> tuple[int, int, int, int, np.ndarray]:
        """(y0, y1, x0, x1, lane centres x) in the rotated image: the window's rows plus the
        margin, and half a lane spacing beyond the first and last lane centres; with `extend`,
        reaching to the nearest ladder mark (plus 3 px) if none is inside."""
        lanes, window = wb.Lanes(**self.lanes), wb.Window(**self.window)
        mid = (window.top + window.bottom) / 2
        centres = rotate_points([(c, mid) for c in lanes.centres()], self.angle - self.base, shape)
        step = (lanes.last - lanes.first) / max(lanes.count - 1, 1) if lanes.count > 1 else lanes.width
        half = (window.bottom - window.top) / 2 + self.margin
        y_mid = float(centres[:, 1].mean())
        y0, y1 = max(0, int(round(y_mid - half))), min(shape[0], int(round(y_mid + half)))
        rows = [r for r, _ in self.tick_rows(shape)]
        if self.extend and rows and not any(y0 <= r < y1 for r in rows):
            near = min(rows, key=lambda r: min(abs(r - y0), abs(r - y1)))
            y0, y1 = max(0, min(y0, int(math.floor(near)) - 3)), min(shape[0], max(y1, int(math.ceil(near)) + 4))
        x0 = max(0, int(round(centres[0, 0] - step / 2)))
        x1 = min(shape[1], int(round(centres[-1, 0] + step / 2)))
        return y0, y1, x0, x1, centres[:, 0]

    def cut(self, image: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(raw values of the rotated strip, lane centres as column positions in it)."""
        raw = wb.read_blot(Path(self.path)).image if image is None else image
        y0, y1, x0, x1, centres = self.box(raw.shape)
        return rotate(raw, self.angle)[y0:y1, x0:x1], centres - x0

    def shown(self, values: np.ndarray) -> np.ndarray:
        """The one linear stretch: lo white (0), hi black (1)."""
        return np.clip((values - self.lo) / (self.hi - self.lo), 0, 1)

    def clipped(self, values: np.ndarray) -> tuple[float, float]:
        """Fractions of pixels shown pure white (≤ lo) and pure black (≥ hi)."""
        return float((values <= self.lo).mean()), float((values >= self.hi).mean())


FONTS = ("Arial", "DejaVu Sans")


@dataclass
class FigureLayout:
    """How the figure is laid out (§4-37); the defaults draw the earlier figure. Never changes
    the strips' pixels or the numbers."""
    font: str = "Arial"
    font_size: float = 8.0
    lane_names: bool = True
    lane_rotation: int = 45
    """0, 45 or 90 degrees."""
    header: list = field(default_factory=list)
    """Per lane, e.g. ["HEKa"] * 3 + ["M249"] * 3: equal neighbours become one underlined label."""
    conditions: list = field(default_factory=list)
    """Rows above the blot, top to bottom: {"name": "VEM", "values": ["-", "+", ...]}."""
    separators: bool = False
    """A vertical line between header groups, through the whole figure."""
    border: bool = False
    gap: float = .3
    """Space between strips, in lane widths."""
    lane_width_in: float = .45
    ticks: bool = True
    nearest_ladder: bool = False
    """Widen a strip to the nearest ladder mark when none falls inside it (`Strip.extend`)."""

    def __post_init__(self) -> None:
        if self.font not in FONTS:
            raise ValueError(f"font must be one of {FONTS}")
        if self.lane_rotation not in (0, 45, 90):
            raise ValueError("lane_rotation must be 0, 45 or 90")


def header_spans(header: list) -> list[tuple[str, int, int]]:
    """(label, first lane, last lane), 1-based, for runs of equal non-empty header labels."""
    spans = []
    for k, label in enumerate(header, start=1):
        label = str(label).strip()
        if spans and label and spans[-1][0] == label and spans[-1][2] == k - 1:
            spans[-1] = (label, spans[-1][1], k)
        elif label:
            spans.append((label, k, k))
    return spans


def compose(strips: list[Strip], lane_labels: list[str], out_base: Path | None, *, gap: float | None = None,
            dpi: int = 300, lane_width_in: float | None = None, layout: FigureLayout | None = None) -> dict:
    """Stack the strips top to bottom with every lane centre under its label, and write PNG,
    TIFF, SVG, PDF and a JSON record (or nothing, with out_base None). Returns the record.
    `gap` and `lane_width_in`, if given, override the layout's."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    layout = layout or FigureLayout()
    gap = layout.gap if gap is None else gap
    lane_width_in = layout.lane_width_in if lane_width_in is None else lane_width_in
    n = len(lane_labels)
    placed, y = [], 0.0
    for s in strips:
        raw = wb.read_blot(Path(s.path)).image
        values, centres = s.cut(raw)
        step = float(np.diff(centres).mean()) if len(centres) > 1 else float(values.shape[1])
        left = 1 - (centres[0] + .5) / step  # pixel j's centre sits at left + (j + .5) / step
        height = values.shape[0] / step
        shape = raw.shape
        y0 = s.box(shape)[0]
        ticks = [{"kda": kda, "row_px": r - y0, "y": y + (r - y0 + .5) / step}
                 for r, kda in s.tick_rows(shape) if 0 <= r - y0 < values.shape[0]]
        placed.append({"strip": s, "values": values, "extent": [left, left + values.shape[1] / step, y + height, y],
                       "centres_x": [left + (c + .5) / step for c in centres], "clipped": s.clipped(values),
                       "ticks": ticks})
        y += height + gap
    total = y - gap if placed else 1
    width_in = lane_width_in * (n + 2.6)
    height_in = lane_width_in * (total + 1.4)
    # Labels stay editable text in the SVG/PDF (§4-34), as in the graphs (§4-33).
    text_style = {"font.family": [layout.font, "Malgun Gothic"], "svg.fonttype": "none", "pdf.fonttype": 42}
    with matplotlib.rc_context(text_style):
        return _draw(placed, lane_labels, n, total, gap, dpi, out_base, Figure(figsize=(width_in, height_in)), layout)


def _draw(placed, lane_labels, n, total, gap, dpi, out_base, fig, layout: FigureLayout) -> dict:
    from matplotlib.patches import Rectangle

    size = layout.font_size
    line = 1.5 * size / 72 / layout.lane_width_in  # one text line, in lane widths
    ax = fig.add_axes([.04, .02, .76, .98 * total / (total + 1.4)])
    for p in placed:
        ax.imshow(p["strip"].shown(p["values"]), cmap="gray_r", vmin=0, vmax=1, extent=p["extent"],
                  interpolation="nearest", aspect="equal")
        e = p["extent"]
        name = " ".join(t for t in (p["strip"].label, f"({p['strip'].kda} kDa)" if p["strip"].kda else "") if t)
        ax.text(n + .65, (e[2] + e[3]) / 2, name, va="center", ha="left", fontsize=size)
        if layout.border:
            box = Rectangle((.5, e[3]), n, e[2] - e[3], fill=False, linewidth=.8, edgecolor="black", clip_on=False)
            box.set_gid("border")
            ax.add_patch(box)
        for t in p["ticks"] if layout.ticks else []:
            ax.plot([.18, .42], [t["y"], t["y"]], color="black", linewidth=1.0, clip_on=False, solid_capstyle="butt")
            ax.text(.1, t["y"], t["kda"], ha="right", va="center", fontsize=size)
    ax.set_xlim(.5, n + .5)
    ax.set_ylim(total, 0)
    ax.axis("off")
    # Above the blot, bottom to top: condition rows (the last one nearest the blot), lane names, header.
    y = -.15
    for row in reversed(layout.conditions):
        values = list(row.get("values", []))
        for k in range(n):
            ax.text(k + 1, y, str(values[k]) if k < len(values) else "", ha="center", va="bottom", fontsize=size)
        ax.text(n + .65, y, str(row.get("name", "")), ha="left", va="bottom", fontsize=size)
        y -= line
    top = y
    if layout.lane_names:
        how = {0: dict(ha="center", va="bottom"), 45: dict(ha="left", va="bottom"), 90: dict(ha="left", va="center")}
        texts = [ax.text(k + 1, y, label, rotation=layout.lane_rotation, fontsize=size, rotation_mode="anchor",
                         **how[layout.lane_rotation]) for k, label in enumerate(lane_labels)]
        renderer = fig.canvas.get_renderer() if hasattr(fig.canvas, "get_renderer") else None
        if renderer is None:
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            renderer = FigureCanvasAgg(fig).get_renderer()
        inverse = ax.transData.inverted()
        top = min([y] + [inverse.transform(t.get_window_extent(renderer))[:, 1].min() for t in texts if t.get_text()])
        top -= .1
    spans = header_spans(layout.header)
    if spans:
        top -= .1
        for label, a, b in spans:
            ax.text((a + b) / 2, top, label, ha="center", va="bottom", fontsize=size, gid="header")
            ax.plot([a - .4, b + .4], [top + .05, top + .05], color="black", linewidth=.8, clip_on=False)
        top -= line
    if layout.separators and len(spans) > 1:
        for (_, _, b), _next in zip(spans, spans[1:]):
            ax.plot([b + .5, b + .5], [top + line, total], color="black", linewidth=.8, clip_on=False, gid="separator")
    record = {"schema": "luxcale-wb-figure-1", "lane_labels": list(lane_labels), "gap": gap, "dpi": dpi,
              "layout": asdict(layout),
              "strips": [{**p["strip"].__dict__, "extent": p["extent"], "centres_x": p["centres_x"],
                          "clipped_white_black": p["clipped"], "tick_marks": p["ticks"]} for p in placed],
              "note": "Rotation (bilinear) and one linear contrast stretch per strip, for display only; "
                      "quantification used the unrotated raw images."}
    if out_base is not None:
        out_base = Path(out_base)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        for fmt in ("png", "svg", "pdf"):
            fig.savefig(out_base.with_suffix("." + fmt), dpi=dpi, facecolor="white", bbox_inches="tight")
        fig.savefig(out_base.with_suffix(".tif"), dpi=dpi, facecolor="white", bbox_inches="tight",
                    pil_kwargs={"compression": "tiff_lzw"})
        out_base.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    else:  # a preview: the PNG bytes ride along under "png" (never written into a record file)
        from io import BytesIO

        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=dpi, facecolor="white", bbox_inches="tight")
        record["png"] = buffer.getvalue()
    return record


def rebuild(record: dict) -> list[np.ndarray]:
    """The strips' displayed arrays from a saved record (for checking a figure)."""
    keys = ("path", "angle", "lanes", "window", "lo", "hi", "label", "kda", "margin", "ticks", "extend", "base")
    strips = [Strip(**{k: s[k] for k in keys if k in s}) for s in record["strips"]]
    return [s.shown(s.cut()[0]) for s in strips]
