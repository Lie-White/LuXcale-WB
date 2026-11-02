"""Independent implementation of the WB quantification definitions."""

from dataclasses import dataclass
import itertools
import math
from typing import Sequence

import numpy as np
from scipy.stats import f as f_distribution
from scipy.stats import t as t_distribution


SATURATION = 65535


@dataclass(frozen=True)
class Lanes:
    """Evenly spaced lane centres with optional per-lane shifts and widths."""

    count: int
    first: float
    last: float
    width: float
    shifts: tuple[float, ...] | None = None
    widths: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.count < 1 or self.width <= 0:
            raise ValueError("lane count and width must be positive")
        if self.shifts is not None and len(self.shifts) != self.count:
            raise ValueError("shifts must have one value per lane")
        if self.widths is not None and (len(self.widths) != self.count or any(w <= 0 for w in self.widths)):
            raise ValueError("widths must have one positive value per lane")

    def centres(self) -> list[float]:
        if self.count == 1:
            centres = [float(self.first)]
        else:
            step = (self.last - self.first) / (self.count - 1)
            centres = [self.first + i * step for i in range(self.count)]
        if self.shifts is not None:
            centres = [x + self.shifts[i] for i, x in enumerate(centres)]
        return centres

    def lane_width(self, i: int) -> float:
        return self.width if self.widths is None else self.widths[i]


@dataclass(frozen=True)
class Window:
    """A named row interval with optional split rows."""

    names: tuple[str, ...]
    top: int
    bottom: int
    splits: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.top + 6 >= self.bottom:
            raise ValueError("window must have at least seven rows")
        if len(self.names) != len(self.splits) + 1:
            raise ValueError("window needs one name per interval")
        if any(not self.top < split < self.bottom for split in self.splits):
            raise ValueError("split rows must be strictly inside the window")
        if any(a >= b for a, b in zip(self.splits, self.splits[1:])):
            raise ValueError("split rows must be in ascending order")


def rotate(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotate by the task's output-to-input bilinear map, clamping at edges."""
    source = np.asarray(image, dtype=np.float64)
    if source.ndim != 2:
        raise ValueError("image must be a 2-D single-channel array")
    height, width = source.shape
    if angle == 0:
        return source.copy()
    theta = math.radians(float(angle))
    cosine, sine = math.cos(theta), math.sin(theta)
    if abs(cosine) < 1e-15:
        cosine = 0.0
    if abs(sine) < 1e-15:
        sine = 0.0
    yy, xx = np.indices((height, width), dtype=np.float64)
    cy, cx = (height - 1) / 2, (width - 1) / 2
    dy, dx = yy - cy, xx - cx
    source_y = cosine * dy + sine * dx + cy
    source_x = -sine * dy + cosine * dx + cx
    source_y = np.clip(source_y, 0, height - 1)
    source_x = np.clip(source_x, 0, width - 1)
    y0 = np.floor(source_y).astype(np.intp)
    x0 = np.floor(source_x).astype(np.intp)
    y1 = np.minimum(y0 + 1, height - 1)
    x1 = np.minimum(x0 + 1, width - 1)
    fy, fx = source_y - y0, source_x - x0
    top = source[y0, x0] * (1 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1 - fx) + source[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def rotate_mask(mask: np.ndarray, angle: float) -> np.ndarray:
    """Turn a binary saturation mask and mark any interpolated contribution."""
    source = np.asarray(mask, dtype=bool)
    if angle == 0:
        return source.copy()
    return rotate(source.astype(np.float64), angle) > 0


def lane_columns(lanes: Lanes, image_width: int) -> list[tuple[int, int]]:
    """Return each lane's checked half-open column interval."""
    intervals = []
    for i, centre in enumerate(lanes.centres()):
        width = lanes.lane_width(i)
        x0 = math.floor(centre - width / 2 + 0.5)
        x1 = x0 + round(width)
        if x0 < 0 or x1 > image_width:
            raise ValueError(f"lane {i + 1} runs off the image")
        intervals.append((x0, x1))
    return intervals


def baseline(profile: np.ndarray) -> np.ndarray:
    """Straight line through the means of the first/last three profile rows."""
    profile = np.asarray(profile, dtype=np.float64)
    length = len(profile)
    if length < 7:
        raise ValueError("window must have at least seven rows")
    left = float(np.mean(profile[:3]))
    right = float(np.mean(profile[-3:]))
    y = np.arange(length, dtype=np.float64)
    return left + (right - left) * (y - 1) / (length - 3)


def measure(image: np.ndarray, saturation_mask: np.ndarray, lanes: Lanes,
            windows: Sequence[Window]) -> list[dict]:
    """Measure lane-window integrals and report per-row saturation."""
    image = np.asarray(image, dtype=np.float64)
    saturation_mask = np.asarray(saturation_mask, dtype=bool)
    if image.ndim != 2 or saturation_mask.shape != image.shape:
        raise ValueError("image and saturation mask must be matching 2-D arrays")
    intervals = lane_columns(lanes, image.shape[1])
    rows = []
    for lane_i, (x0, x1) in enumerate(intervals):
        for window in windows:
            if not (0 <= window.top < window.bottom <= image.shape[0]):
                raise ValueError("window rows must be inside the image")
            block = image[window.top:window.bottom, x0:x1]
            profile = np.sum(block, axis=1, dtype=np.float64)
            signal = profile - baseline(profile)
            sat = bool(saturation_mask[window.top:window.bottom, x0:x1].any())
            edges = (0,) + tuple(split - window.top for split in window.splits) + (len(profile),)
            values = [float(np.sum(signal[a:b], dtype=np.float64))
                      for a, b in zip(edges, edges[1:])]
            for name, value in zip(window.names, values):
                rows.append({"lane": lane_i + 1, "band": name, "value": value,
                             "saturated": sat, "x0": x0, "x1": x1,
                             "top": window.top, "bottom": window.bottom})
            if len(window.names) > 1:
                rows.append({"lane": lane_i + 1, "band": " + ".join(window.names),
                             "value": float(np.sum(signal, dtype=np.float64)),
                             "saturated": sat, "x0": x0, "x1": x1,
                             "top": window.top, "bottom": window.bottom})
    return rows


def normalise(target_rows: Sequence[dict], loading_rows: Sequence[dict],
              groups: Sequence[str], reference_group: str,
              target_band: str | None = None,
              loading_band: str | None = None) -> list[dict]:
    """Divide target/loading per lane by the reference-group mean ratio."""
    target = {r["lane"]: r for r in target_rows
              if target_band is None or r["band"] == target_band}
    loading = {r["lane"]: r for r in loading_rows
               if loading_band is None or r["band"] == loading_band}
    if len(target) != len(target_rows) and target_band is None:
        raise ValueError("select a target band when multiple rows are present")
    if len(loading) != len(loading_rows) and loading_band is None:
        raise ValueError("select a loading band when multiple rows are present")
    lane_numbers = sorted(target)
    if not lane_numbers or lane_numbers != sorted(loading) or len(groups) != len(lane_numbers):
        raise ValueError("target, loading and groups must cover the same lanes")
    ratios = {lane: target[lane]["value"] / loading[lane]["value"] for lane in lane_numbers}
    reference = [ratios[lane] for lane, group in zip(lane_numbers, groups)
                 if group == reference_group]
    if not reference:
        raise ValueError(f"no lane belongs to reference group {reference_group!r}")
    reference_mean = math.fsum(reference) / len(reference)
    return [{"lane": lane, "group": group, "target": target[lane]["value"],
             "loading": loading[lane]["value"], "ratio": ratios[lane],
             "relative": ratios[lane] / reference_mean}
            for lane, group in zip(lane_numbers, groups)]


def per_experiment_values(experiments: Sequence[dict], groups: Sequence[str]) -> list[dict]:
    """Average each experiment's relative lane values by group."""
    results = []
    for experiment in experiments:
        values = experiment["values"]
        group_means = {}
        for group in groups:
            group_values = [float(row["relative"]) for row in values if row["group"] == group]
            group_means[group] = math.fsum(group_values) / len(group_values) if group_values else None
        results.append({"experiment": experiment["experiment"], "group_means": group_means})
    return results


def _paired_t(differences: Sequence[float]) -> dict:
    values = np.asarray(differences, dtype=np.float64)
    n = len(values)
    if n < 2:
        raise ValueError("paired t test needs at least two complete experiments")
    mean = float(values.mean())
    standard_error = float(values.std(ddof=1) / math.sqrt(n))
    if standard_error == 0:
        statistic = 0.0 if mean == 0 else math.copysign(math.inf, mean)
        p_value = 1.0 if mean == 0 else 0.0
    else:
        statistic = mean / standard_error
        p_value = float(2 * t_distribution.sf(abs(statistic), n - 1))
    return {"t": float(statistic), "df": n - 1, "p": p_value, "n": n}


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values in input order."""
    p_values = [float(p) for p in p_values]
    if any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be between zero and one")
    order = sorted(range(len(p_values)), key=lambda i: (p_values[i], i))
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def _rm_anova(matrix: np.ndarray) -> dict:
    """Repeated-measures one-way ANOVA with experiments as complete blocks."""
    matrix = np.asarray(matrix, dtype=np.float64)
    n, k = matrix.shape
    if n < 2 or k < 3:
        raise ValueError("repeated-measures ANOVA needs >=2 experiments and >=3 groups")
    grand = float(matrix.mean())
    group_means = matrix.mean(axis=0)
    block_means = matrix.mean(axis=1)
    ss_groups = float(n * np.square(group_means - grand).sum())
    ss_blocks = float(k * np.square(block_means - grand).sum())
    residual = matrix - group_means[None, :] - block_means[:, None] + grand
    ss_error = float(np.square(residual).sum())
    df_groups = k - 1
    df_error = (k - 1) * (n - 1)
    ms_groups = ss_groups / df_groups
    ms_error = ss_error / df_error
    if ms_error == 0:
        statistic = 0.0 if ms_groups == 0 else math.inf
        p_value = 1.0 if ms_groups == 0 else 0.0
    else:
        statistic = ms_groups / ms_error
        p_value = float(f_distribution.sf(statistic, df_groups, df_error))
    return {"F": float(statistic), "df1": df_groups, "df2": df_error,
            "p": p_value, "SS_groups": ss_groups, "SS_blocks": ss_blocks,
            "SS_error": ss_error, "MS_groups": ms_groups, "MS_error": ms_error,
            "n": n, "k": k}


def combine(experiments: Sequence[dict], groups: Sequence[str]) -> dict:
    """Summarize complete experiments and run paired/repeated-measures tests."""
    values = per_experiment_values(experiments, groups)
    complete = [row for row in values if all(row["group_means"][g] is not None for g in groups)]
    left_out = [row["experiment"] for row in values if row not in complete]
    if len(complete) < 2:
        raise ValueError("at least two complete experiments are required")
    matrix = np.log(np.asarray([[row["group_means"][g] for g in groups]
                                for row in complete], dtype=np.float64))
    paired = []
    for a, b in itertools.combinations(range(len(groups)), 2):
        stat = _paired_t(matrix[:, a] - matrix[:, b])
        paired.append({"group_a": groups[a], "group_b": groups[b], **stat})
    for adjusted, value in zip(holm_adjust([row["p"] for row in paired]), paired):
        value["p_holm"] = adjusted
    if len(groups) == 2:
        omnibus = {"test": "paired_t", **paired[0]}
    else:
        omnibus = {"test": "rm_anova", **_rm_anova(matrix)}
    return {"groups": list(groups), "per_experiment": values,
            "included_experiments": [row["experiment"] for row in complete],
            "left_out_experiments": left_out, "paired_tests": paired,
            "omnibus": omnibus}
