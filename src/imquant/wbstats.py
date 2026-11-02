"""Combining repeated Western blot experiments (docs/PLAN.md §4-38).

Each experiment is normalised on its own (imquant.wb.run_experiments), so its reference group's
mean is exactly 1. With the experiment as one n, every experiment gives one value per group (the
mean of its lanes) and groups are compared paired by experiment on the log scale (ratios): a
paired t-test for two groups; for three or more, a repeated-measures ANOVA (experiments as
blocks) and paired t-tests between every pair of groups, Holm-adjusted. Because the reference
is 1 (log 0) in every experiment, its paired t-test equals testing whether log(group ÷
reference) averages 0. With the lane as one n, the app's usual unpaired tests run, with a
warning that lanes from one experiment are not independent.
"""

import math

import numpy as np
from scipy import stats as sps

from imquant.recommend import candidate_statistics, recommendations
from imquant.stats import stars

UNITS = ("experiment", "lane")
LANES_NOT_INDEPENDENT = ("n counts lanes, not experiments: lanes from one experiment share a gel, "
                         "a transfer and an exposure, so they are not independent and p values come out too small")


def per_experiment(rows: list[dict], groups: list[str]) -> dict[str, dict[str, float]]:
    """{experiment: {group: mean relative value of its lanes}} for the groups it has."""
    out: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        out.setdefault(str(r["experiment"]), {}).setdefault(r["group"], []).append(float(r["relative"]))
    return {e: {g: math.fsum(v) / len(v) for g, v in by.items() if g in groups} for e, by in out.items()}


def holm(p: list[float]) -> list[float]:
    """Holm step-down adjusted p values, in the input order."""
    order = sorted(range(len(p)), key=lambda i: p[i])
    adjusted, running = [0.0] * len(p), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        adjusted[i] = running
    return adjusted


def rm_anova(matrix: np.ndarray) -> dict:
    """One-way repeated-measures ANOVA on an (experiments × groups) matrix with no gaps."""
    n, k = matrix.shape
    grand = matrix.mean()
    ss_groups = n * ((matrix.mean(0) - grand) ** 2).sum()
    ss_blocks = k * ((matrix.mean(1) - grand) ** 2).sum()
    ss_error = ((matrix - grand) ** 2).sum() - ss_groups - ss_blocks
    df1, df2 = k - 1, (k - 1) * (n - 1)
    f = (ss_groups / df1) / (ss_error / df2) if ss_error > 0 else math.inf
    return {"f": float(f), "df1": df1, "df2": df2, "p": float(sps.f.sf(f, df1, df2)) if math.isfinite(f) else 0.0}


def paired(per: dict[str, dict[str, float]], groups: list[str]) -> tuple[dict, list[str], list[str]]:
    """(statistics, experiments used, warnings) for the experiments that have every group."""
    complete = [e for e, by in per.items() if all(g in by for g in groups)]
    warnings = []
    left_out = [e for e in per if e not in complete]
    if left_out:
        warnings.append(f"Left out of the paired test (a group is missing): {', '.join(left_out)}")
    result = {"test": None, "comparisons": [], "test_name": "No test"}
    if len(complete) < 2 or len(groups) < 2:
        warnings.append("No test: at least two experiments with every group are required")
        return result, complete, warnings
    logs = np.log(np.array([[per[e][g] for g in groups] for e in complete]))
    if len(groups) == 2:
        t = sps.ttest_rel(logs[:, 0], logs[:, 1])
        test = {"t": float(t.statistic), "df": len(complete) - 1, "p": float(t.pvalue), "stars": stars(float(t.pvalue))}
        result.update(test=test, comparisons=[{"i": 0, "j": 1, **test}], test_name="Paired t-test (log scale)")
    else:
        pairs = [(i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))]
        raw = [sps.ttest_rel(logs[:, i], logs[:, j]) for i, j in pairs]
        adjusted = holm([float(t.pvalue) for t in raw])
        result.update(test=rm_anova(logs), test_name="Repeated-measures ANOVA (log scale) + paired t (Holm)",
                      comparisons=[{"i": i, "j": j, "t": float(t.statistic), "df": len(complete) - 1,
                                    "p_unadjusted": float(t.pvalue), "p": p, "stars": stars(p)}
                                   for (i, j), t, p in zip(pairs, raw, adjusted)])
    if any(not math.isfinite(c["p"]) for c in result["comparisons"]):
        warnings.append("Some pairs have the same difference in every experiment: no p value for them")
    return result, complete, warnings


def combine(rows: list[dict], groups: list[str], unit: str = "experiment", target: str = "WB",
            warnings: list[str] | None = None) -> tuple[dict, dict]:
    """(candidate, statistics) in the shapes `imquant.graphs.dot_bar` draws, for all experiments'
    rows (each with "experiment", "group", "replicate", "lane", "relative")."""
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}")
    warnings = list(warnings or [])
    if unit == "lane":
        # Each lane is its own n here, so it is its own "replicate" (lane labels may repeat across groups).
        lane_rows = [{"cohort": "WB", "group": r["group"], "replicate": f"{r['experiment']}/lane{r['lane']}",
                      "image": f"{r['experiment']}/lane{r['lane']}", "channel": 0, "marker": target, "projection": "wb",
                      "mean": r["relative"], "threshold": "", "spec": "", "warnings": "; ".join(warnings)}
                     for r in rows]
        candidate = recommendations(lane_rows, group_order=groups, unit="roi")[0]
        candidate["warnings"] = [w for w in candidate["warnings"] if "not animals" not in w] + [LANES_NOT_INDEPENDENT]
        candidate["unit"] = "replicate"  # drawn with "n = …" per group; the warning says what n is
        statistics = candidate_statistics(candidate)
        return candidate, statistics
    per = per_experiment(rows, groups)
    result, used, said = paired(per, groups)
    values = {g: [per[e][g] for e in per if g in per[e]] for g in groups}
    candidate = {"title": target, "cohort": "WB", "channel": 0, "marker": target, "projection": "wb",
                 "quantity": "mean", "groups": list(groups), "n": {g: len(v) for g, v in values.items()},
                 "unit": "replicate", "animals": {g: len(v) for g, v in values.items()},
                 "test_name": result["test_name"], "warnings": warnings + said, "values": values,
                 "replicate_ids": {g: [e for e in per if g in per[e]] for g in groups},
                 "image_counts": {}, "excluded": {}, "excluded_rows": 0, "spec_hashes": [], "thresholds": [],
                 "experiments_paired": used, "candidate_index": 1, "total_candidates": 1}
    from imquant.stats import STAR_THRESHOLDS, describe

    statistics = {"descriptive": {g: describe(values[g]) for g in groups}, "test": result["test"],
                  "comparisons": result["comparisons"], "warnings": candidate["warnings"],
                  "star_thresholds": [{"p_lt": p, "label": label} for p, label in STAR_THRESHOLDS]}
    return candidate, statistics
