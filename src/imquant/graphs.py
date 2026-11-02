"""Deterministic dots + mean/SD bars with auditable data and vector artist IDs."""

import csv
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import textwrap

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np

from imquant.recommend import UNIT_NAMES


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]
"""Group colours for the "colour" style: told apart with common colour-vision deficiencies."""


FONTS = ("Arial", "DejaVu Sans")


@dataclass
class GraphStyle:
    """How a graph looks (docs/PLAN.md §4-18). Never changes the statistics. The defaults draw
    exactly the original dots + mean ± SD bars."""
    kind: str = "bar"
    """"bar" (dots + bar), "mean_line" (dots + mean line), "box" or "violin"."""
    error: str = "sd"
    """Error bars for bar and mean_line: "sd", "sem" or "ci95"."""
    dots: bool = True
    dot_size: float = 15.0
    colors: str = "grey"
    """"grey", "colour" (Okabe–Ito) or "custom" (`custom_colors`, by group)."""
    custom_colors: dict[str, str] = field(default_factory=dict)
    significance: str = "stars"
    """"stars", "p" (p = …) or "none"."""
    y_min: float | None = None
    y_max: float | None = None
    y_label: str = ""
    """Empty: chosen from the quantity."""
    font_size: float = 8.5
    width_in: float = 3.2
    height_in: float = 2.8
    font: str = "Arial"
    """"Arial" (on Windows and macOS, so Illustrator opens the text in the same font; §4-33) or
    "DejaVu Sans" (the earlier default). Korean text falls back to Malgun Gothic."""

    def __post_init__(self) -> None:
        for name, allowed in (("kind", ("bar", "mean_line", "box", "violin")), ("error", ("sd", "sem", "ci95")),
                              ("colors", ("grey", "colour", "custom")), ("significance", ("stars", "p", "none")),
                              ("font", FONTS)):
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name} must be one of {allowed}")

    def color(self, i: int, n: int, group: str) -> str:
        grey = str(.72 - .30*i/max(1, n-1))
        if self.colors == "colour":
            return OKABE_ITO[i % len(OKABE_ITO)]
        if self.colors == "custom":
            return self.custom_colors.get(group, grey)
        return grey


def preview(candidate: dict, values: dict, stats: dict, dpi: float = 150, style: GraphStyle | None = None) -> bytes:
    """The PNG `dot_bar` would export, at `dpi`, without writing anything (the window's graph panel)."""
    return dot_bar(candidate, values, stats, None, dpi, style)


def dot_bar(candidate: dict, values: dict, stats: dict, out_base: Path | None, preview_dpi: float = 150,
            style: GraphStyle | None = None):
    """Export PNG/SVG/PDF plus full numeric CSV/JSON; n is biological replicates. With `out_base`
    None, nothing is written and the PNG bytes at `preview_dpi` are returned instead. `style`
    changes only the drawing (docs/PLAN.md §4-18)."""
    look = style or GraphStyle()
    groups = candidate["groups"]
    if set(values) != set(groups):
        raise ValueError("Values must match the candidate groups")
    comparisons = stats["comparisons"]
    pairs = comparisons if len(groups) == 2 else [r for r in comparisons if math.isfinite(r["p"]) and r["p"] < .05]
    pairs = [r for r in pairs if math.isfinite(r["p"])] if look.significance != "none" else []
    height = look.height_in + .22*len(pairs)
    style = {"font.size": look.font_size, "font.family": [look.font, "Malgun Gothic"],
             "axes.titlesize": look.font_size + 1, "axes.labelsize": look.font_size, "xtick.labelsize": look.font_size - .5,
             "ytick.labelsize": look.font_size - .5, "svg.fonttype": "none", "pdf.fonttype": 42,
             "svg.hashsalt": "luxcale-p5-v1"}
    with matplotlib.rc_context(style):
        figure = Figure(figsize=(look.width_in, height), facecolor="white")
        FigureCanvasAgg(figure)
        ax = figure.add_axes((.22, .27, .73, .58))
        rng = np.random.default_rng(0)
        low, high = [0.], [0.]
        dot_x = {}
        for i, group in enumerate(groups):
            data = np.asarray(values[group], dtype=float)
            description = stats["descriptive"][group]
            if not np.isfinite(data).all() or description["n"] != len(data):
                raise ValueError("Provide the same finite replicate data used for statistics")
            if not len(data):
                ax.text(i, 0, "No data", ha="center", va="bottom", fontsize=8)
                dot_x[group] = []
                continue
            mean, sd = description["mean"], description["sd"]
            color = look.color(i, len(groups), group)
            if look.kind == "bar":
                bar = ax.bar(i, mean, width=.58, facecolor=color, edgecolor="black", linewidth=.6, zorder=1)[0]
                bar.set_gid(f"bar-{i}")
            elif look.kind == "mean_line":
                line, = ax.plot([i-.25, i+.25], [mean, mean], color=color if look.colors != "grey" else "black",
                                linewidth=1.6, zorder=2)
                line.set_gid(f"mean-{i}")
            elif look.kind == "box":
                box = ax.boxplot([data], positions=[i], widths=.5, patch_artist=True, showfliers=False,
                                 medianprops={"color": "black", "linewidth": 1.0}, zorder=1)
                box["boxes"][0].set_facecolor(color)
                box["boxes"][0].set_gid(f"box-{i}")
                box["medians"][0].set_gid(f"median-{i}")
            elif len(data) >= 2:  # violin: a density needs two values at least
                body = ax.violinplot([data], positions=[i], widths=.6, showextrema=False)["bodies"][0]
                body.set_facecolor(color)
                body.set_edgecolor("black")
                body.set_alpha(.85)
                body.set_gid(f"violin-{i}")
                ys = body.get_paths()[0].vertices[:, 1]
                low.append(float(ys.min()))
                high.append(float(ys.max()))
                median, = ax.plot([i-.12, i+.12], [np.median(data)]*2, color="black", linewidth=1.0, zorder=2)
                median.set_gid(f"median-{i}")
            if look.kind in ("bar", "mean_line") and math.isfinite(sd):
                if look.error == "sd":
                    yerr, lo, hi = sd, mean-sd, mean+sd
                elif look.error == "sem":
                    yerr, lo, hi = description["sem"], mean-description["sem"], mean+description["sem"]
                else:
                    lo, hi = description["ci_lo"], description["ci_hi"]
                    yerr = [[mean-lo], [hi-mean]]
                errors = ax.errorbar(i, mean, yerr=yerr, fmt="none", color="black", linewidth=.8,
                                     capsize=3, capthick=.8, zorder=2)
                for j, cap in enumerate(errors.lines[1]):
                    cap.set_gid(f"errorcap-{i}-{j}")
                for collection in errors.lines[2]:
                    collection.set_gid(f"errorbar-{i}")
                low.append(lo)
                high.append(hi)
            jitter = rng.uniform(-.10, .10, len(data)) if len(data) > 1 else np.array([0.])
            xs = i+jitter
            if look.dots:
                dots = ax.scatter(xs, data, s=look.dot_size, c="black", edgecolors="white", linewidths=.25, zorder=3)
                dots.set_gid(f"dots-{i}")
            dot_x[group] = xs.tolist()
            low.append(float(data.min()))
            high.append(float(data.max()))
        bottom, top = min(low), max(high)
        span = top-bottom or 1.
        for level, pair in enumerate(pairs):
            y = top + (.14+.15*level)*span
            i, j = pair["i"], pair["j"]
            line, = ax.plot([i, i, j, j], [y, y+.035*span, y+.035*span, y], color="black", linewidth=.65)
            line.set_gid(f"significance-{i}-{j}")
            label = pair["stars"] if look.significance == "stars" else f"p = {pair['p']:.3g}"
            ax.text((i+j)/2, y+.04*span, label, ha="center", va="bottom", fontsize=look.font_size - .5)
        if not pairs and look.significance != "none":
            ax.text(.5, 1.03, "ns" if stats["test"] is not None else "Not tested",
                    transform=ax.transAxes, ha="center", va="bottom", fontsize=8)
        ax.set_xlim(-.6, max(.6, len(groups)-.4))
        ax.set_ylim(bottom-.10*span if bottom < 0 else 0, top+(.18+.15*len(pairs))*span)
        if look.y_min is not None:
            ax.set_ylim(bottom=look.y_min)
        if look.y_max is not None:
            ax.set_ylim(top=look.y_max)
        ax.set_xticks(range(len(groups)), groups, rotation=30 if any(len(g) > 10 for g in groups) else 0,
                      ha="right" if any(len(g) > 10 for g in groups) else "center")
        display = any("display units" in w.lower() for w in stats["warnings"])
        ylabel = "Positive area (%)" if candidate["quantity"] == "positive_pct" else (
            "Mean intensity (display units)" if display else "Mean intensity (raw units)")
        ylabel = look.y_label or ylabel
        ax.set_ylabel(ylabel)
        ax.set_title(candidate["title"], pad=22)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_linewidth(.65)
        ax.spines["bottom"].set_linewidth(.65)
        ax.tick_params(width=.65, length=3)
        test_name = candidate["test_name"] if stats["test"] is not None else "No test"
        unit = candidate.get("unit", "replicate")
        if unit == "replicate":
            footer = "n (biological replicates): " + ", ".join(f"{g}={stats['descriptive'][g]['n']}" for g in groups)
        else:  # docs/PLAN.md §4-19: say what was counted, and from how many animals
            footer = f"n = {UNIT_NAMES[unit]} (animals): " + ", ".join(
                f"{g}={stats['descriptive'][g]['n']} ({candidate['animals'][g]})" for g in groups)
        shown = test_name if unit == "replicate" else f"{test_name}; {UNIT_NAMES[unit]} are not independent"
        figure.text(.08, .02, textwrap.fill(footer, width=52) + "\n" + shown, fontsize=look.font_size - .5, va="bottom")
        if out_base is None:
            from io import BytesIO

            buffer = BytesIO()
            figure.savefig(buffer, format="png", dpi=preview_dpi, facecolor="white")
            return buffer.getvalue()
        out_base = Path(out_base)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        paths = {suffix: out_base.with_name(out_base.name + "." + suffix) for suffix in ("png", "svg", "pdf", "json")}
        paths["stats_csv"] = out_base.with_name(out_base.name + "_stats.csv")
        paths["prism_csv"] = out_base.with_name(out_base.name + "_prism.csv")
        for kind in ("png", "svg", "pdf"):
            figure.savefig(paths[kind], format=kind, dpi=300, facecolor="white")
        geometry = {"axes_rect": list(ax.get_position().bounds), "xlim": list(ax.get_xlim()),
                    "ylim": list(ax.get_ylim()), "figure_inches": list(figure.get_size_inches()),
                    "svg_points_per_inch": 72, "dot_x": dot_x, "ylabel": ylabel,
                    "jitter_seed": 0, "jitter_half_width": .1, "error": look.error,
                    "significant_pairs_drawn": [[p["i"], p["j"]] for p in pairs]}
        payload = {"schema_version": 1, "candidate": candidate, "data": dict(values),
                   "n": {g: len(values[g]) for g in groups}, "statistics": stats,
                   "actual_test_name": test_name, "star_thresholds": stats["star_thresholds"],
                   "input_spec_hashes": candidate["spec_hashes"],
                   "total_candidates": candidate["total_candidates"], "plot": geometry,
                   "style": asdict(look)}
        paths["json"].write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2,
                                           allow_nan=False), encoding="utf-8")
        fields = ["kind", "group", "i", "j", "n", "mean", "sd", "sem", "ci_lo", "ci_hi",
                  "t", "df", "f", "df1", "df2", "p", "diff", "confidence", "stars", "test_name"]
        records = [{"kind": "descriptive", "group": g, **d, "test_name": test_name}
                   for g, d in stats["descriptive"].items()]
        if stats["test"] is not None:
            records.append({"kind": "test", **stats["test"], "test_name": test_name})
        records.extend({"kind": "comparison", **r, "test_name": test_name} for r in comparisons)
        with paths["stats_csv"].open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for record in records:
                safe = _json_safe(record)
                writer.writerow({k: "" if v is None else v for k, v in safe.items()})
        write_prism_table(paths["prism_csv"], groups, values)
        figure.clear()
    return paths


def write_prism_table(path: Path, groups: list[str], values: dict) -> None:
    """A table for a Prism Column sheet (§4-33): one column per group in graph order, the plotted
    values exactly (repr round-trips), shorter columns padded with blanks."""
    columns = [[repr(float(v)) for v in values[g]] for g in groups]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(groups)
        for i in range(max((len(c) for c in columns), default=0)):
            writer.writerow([c[i] if i < len(c) else "" for c in columns])


def export_all(rows: list[dict], out_dir: Path, group_order=None, style: GraphStyle | None = None,
               unit: str = "replicate") -> list[tuple[dict, dict, Path]]:
    """Every recommended candidate of P3a channels.csv rows, each written to out_dir (the
    `graphs` command and the window's Graphs button). Returns (candidate, statistics, base path)."""
    from imquant.recommend import candidate_statistics, recommendations

    done = []
    for candidate in recommendations(rows, group_order=group_order, unit=unit):
        base = Path(out_dir) / file_name(candidate)
        result = candidate_statistics(candidate)
        dot_bar(candidate, candidate["values"], result, base, style=style)
        done.append((candidate, result, base))
    return done


def file_name(candidate: dict) -> str:
    """Base name of a candidate's exported files."""
    label = f"{candidate['candidate_index']:03d}_{candidate['cohort']}_{candidate['marker'] or candidate['channel']}_{candidate['quantity']}"
    if candidate.get("unit", "replicate") != "replicate":
        label += f"_per_{candidate['unit']}"
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in label)


def read_channels_csv(path: Path) -> list[dict]:
    """Rows of a P3a channels.csv (UTF-8, optional BOM)."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
