"""Unpaired biological-replicate statistics; explicit confidence and star rules."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from itertools import combinations
import math

import numpy as np
from scipy import stats as scipy_stats

STAR_THRESHOLDS = ((.0001, "****"), (.001, "***"), (.01, "**"), (.05, "*"))
"""Strict upper bounds; p exactly at a boundary receives the next lower label."""


def stars(p: float) -> str:
    if not math.isfinite(p):
        return "NA"
    if not 0 <= p <= 1:
        raise ValueError("p must be between zero and one")
    return next((label for bound, label in STAR_THRESHOLDS if p < bound), "ns")


def _sample(x) -> np.ndarray:
    values = np.asarray(list(x), dtype=float)
    if values.ndim != 1 or np.isinf(values).any():
        raise ValueError("Use a one-dimensional sample with no infinite values")
    return values[~np.isnan(values)]


def _mean(x: np.ndarray) -> float:
    if not len(x):
        return math.nan
    mean = math.fsum(map(float, x)) / len(x)
    # Correct the rounding of sum/n without needing platform-dependent long double.
    return mean + math.fsum(float(v)-mean for v in x) / len(x)


def _ss(x: np.ndarray, mean: float) -> float:
    residuals = [float(v) - mean for v in x]
    # A corrected two-pass sum avoids residual mean rounding at large offsets.
    return max(0., math.fsum(v*v for v in residuals) - math.fsum(residuals)**2 / len(x))


def _confidence(confidence: float) -> None:
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between zero and one")


def describe(x, confidence: float = .95) -> dict:
    """Sample SD (n-1), SEM, and a two-sided Student confidence interval."""
    _confidence(confidence)
    values = _sample(x)
    n, mean = len(values), _mean(values)
    sd = math.sqrt(_ss(values, mean) / (n-1)) if n >= 2 else math.nan
    sem = sd / math.sqrt(n) if n else math.nan
    half = float(scipy_stats.t.ppf((1+confidence)/2, n-1)) * sem if n >= 2 else math.nan
    return {"n": n, "mean": mean, "sd": sd, "sem": sem, "ci_lo": mean-half, "ci_hi": mean+half,
            "median": float(np.median(values)) if n else math.nan,
            "min": float(values.min()) if n else math.nan, "max": float(values.max()) if n else math.nan,
            "confidence": confidence}


def t_test(a, b, welch: bool = False, confidence: float = .95) -> dict:
    """Two-sided unpaired t-test; difference and CI use mean(a)-mean(b)."""
    _confidence(confidence)
    a, b = _sample(a), _sample(b)
    na, nb = len(a), len(b)
    if not na or not nb or na+nb <= 2 or (welch and min(na, nb) < 2):
        raise ValueError("Insufficient observations for the requested t-test")
    ma, mb = _mean(a), _mean(b)
    sa, sb = _ss(a, ma), _ss(b, mb)
    diff = ma-mb
    if welch:
        va, vb = sa/(na-1)/na, sb/(nb-1)/nb
        se = math.sqrt(va+vb)
        denominator = va*va/(na-1) + vb*vb/(nb-1)
        df = (va+vb)**2 / denominator if denominator else float(na+nb-2)
    else:
        df = na+nb-2
        se = math.sqrt((sa+sb)/df * (1/na+1/nb))
    statistic = diff / se if se else (math.copysign(math.inf, diff) if diff else math.nan)
    p = float(2*scipy_stats.t.sf(abs(statistic), df)) if not math.isnan(statistic) else math.nan
    half = float(scipy_stats.t.ppf((1+confidence)/2, df))*se
    return {"name": "Welch t-test" if welch else "Student t-test", "t": statistic, "df": df,
            "p": p, "diff": diff, "se": se, "ci_lo": diff-half, "ci_hi": diff+half,
            "confidence": confidence, "stars": stars(p)}


def _groups(groups: Mapping | Sequence) -> list[np.ndarray]:
    arrays = [_sample(v) for v in (groups.values() if isinstance(groups, Mapping) else groups)]
    if len(arrays) < 2 or any(not len(a) for a in arrays) or sum(map(len, arrays)) <= len(arrays):
        raise ValueError("At least two nonempty groups with residual degrees of freedom are required")
    return arrays


def one_way_anova(groups: Mapping | Sequence) -> dict:
    """Ordinary independent-groups ANOVA with a shared residual variance."""
    arrays = _groups(groups)
    n = sum(map(len, arrays))
    # ANOVA is translation invariant. Center *before* computing group means so
    # large common offsets do not round away between-group differences.
    origin = float(arrays[0][0])
    centered = [a-origin for a in arrays]
    grand = _mean(np.concatenate(centered))
    means = [_mean(a) for a in centered]
    between = math.fsum(len(a)*(m-grand)**2 for a, m in zip(centered, means))
    within = math.fsum(_ss(a, m) for a, m in zip(centered, means))
    df1, df2 = len(arrays)-1, n-len(arrays)
    ms_between, ms_within = between/df1, within/df2
    f = ms_between/ms_within if ms_within else (math.inf if ms_between else math.nan)
    p = float(scipy_stats.f.sf(f, df1, df2)) if not math.isnan(f) else math.nan
    return {"name": "One-way ANOVA", "f": f, "df1": df1, "df2": df2, "p": p,
            "ss_between": between, "ss_within": within, "ms_between": ms_between,
            "ms_within": ms_within, "stars": stars(p)}


@lru_cache(maxsize=128)
def _range_critical(k: int, df: int, confidence: float) -> float:
    return float(scipy_stats.studentized_range.ppf(confidence, k, df))


def tukey_hsd(groups: Mapping | Sequence, confidence: float = .95) -> list[dict]:
    """Tukey-Kramer all-pair comparisons; diff = mean(j)-mean(i), matching R j-i."""
    _confidence(confidence)
    arrays = _groups(groups)
    anova = one_way_anova(arrays)
    critical = _range_critical(len(arrays), anova["df2"], confidence)
    means = [_mean(a) for a in arrays]
    comparisons = []
    for i, j in combinations(range(len(arrays)), 2):
        diff = means[j]-means[i]
        denominator = math.sqrt(anova["ms_within"]/2*(1/len(arrays[i])+1/len(arrays[j])))
        q = abs(diff)/denominator if denominator else (math.inf if diff else math.nan)
        p = float(scipy_stats.studentized_range.sf(q, len(arrays), anova["df2"])) if not math.isnan(q) else math.nan
        half = critical*denominator
        comparisons.append({"i": i, "j": j, "diff": diff, "ci_lo": diff-half, "ci_hi": diff+half,
                            "p": p, "q": q, "df": anova["df2"], "confidence": confidence,
                            "stars": stars(p)})
    return comparisons
