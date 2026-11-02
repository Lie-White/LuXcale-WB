"""Recommend basic graphs, reducing images to independent biological replicates first."""

from collections.abc import Iterable, Mapping, Sequence
import math

from imquant.stats import STAR_THRESHOLDS, describe, one_way_anova, t_test, tukey_hsd


# What one n is (docs/PLAN.md §4-19): an animal (biological replicate, the default), one image
# (its ROIs averaged), or one measured ROI. Only "replicate" gives independent n for group tests.
UNITS = ("replicate", "image", "roi")
UNIT_NAMES = {"replicate": "animals", "image": "images", "roi": "ROIs"}
NOT_INDEPENDENT = ("n counts {unit}, not animals: measurements from one animal are not independent, "
                   "so group p values come out too small (more false positives)")
# Measured in validation/p5 (docs/PLAN.md §4-47): ROIs counted as n, no true difference, 3-10 ROIs
# per animal. Images were not simulated, so they get no number.
ROI_FALSE_POSITIVES = ("; in this app's simulation (docs/PLAN.md §4-47) counting ROIs as n gave "
                       "6.7–67.4% false positives instead of 5%, more the more animals differ")


class ReplicateValues(dict):
    """Group lists plus an explicit audit of excluded rows and replicate image counts."""

    def __init__(self, values: dict, *, excluded: dict, replicate_ids: dict, image_counts: dict, animals: dict):
        super().__init__(values)
        self.excluded = excluded
        self.excluded_rows = sum(excluded.values())
        self.replicate_ids = replicate_ids
        self.image_counts = image_counts
        self.animals = animals


def _number(value) -> float:
    if value is None or str(value).strip() == "":
        return math.nan
    return float(value)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _ordered(present: Sequence[str], requested: Sequence[str] | None) -> list[str]:
    if requested is None:
        return list(present)
    if len(requested) != len(set(requested)) or set(requested) != set(present):
        raise ValueError("group_order must contain each present group exactly once")
    return list(requested)


def replicate_values(rows: Iterable[Mapping], marker: str, quantity: str, *,
                     group_order: Sequence[str] | None = None, unit: str = "replicate") -> ReplicateValues:
    """Average values within each group and unit of n (replicate by default); never infer an ID from an image."""
    if quantity not in ("mean", "positive_pct"):
        raise ValueError("quantity must be mean or positive_pct")
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}")
    rows = [r for r in rows if _text(r.get("marker")) == marker]
    for field in ("cohort", "channel", "projection"):
        if len({_text(r.get(field)) for r in rows}) > 1:
            raise ValueError(f"Select one {field} before aggregating a marker")
    groups = list(dict.fromkeys(_text(r.get("group")) for r in rows if _text(r.get("group"))))
    groups = _ordered(groups, group_order)
    values = {g: {} for g in groups}
    animals = {g: set() for g in groups}
    excluded = {"missing_group": 0, "missing_replicate": 0, "missing_value": 0}
    seen = set()
    for row in rows:
        group, replicate = _text(row.get("group")), _text(row.get("replicate"))
        if not group:
            excluded["missing_group"] += 1
            continue
        if not replicate:
            excluded["missing_replicate"] += 1
            continue
        value = _number(row.get(quantity))
        if not math.isfinite(value):
            excluded["missing_value"] += 1
            continue
        # One measurement = one image, or one ROI of it (docs/PLAN.md §4-12); each counts equally.
        key = (group, replicate, _text(row.get("image")), _text(row.get("roi_id")))
        if key[2] and key in seen:
            raise ValueError(f"Duplicate image/ROI/channel measurement: {key}")
        seen.add(key)
        animals[group].add(replicate)
        # The same image name in two animals is two images; every row is its own ROI.
        n_key = {"replicate": replicate, "image": key[1:3], "roi": len(values[group])}[unit]
        values[group].setdefault(n_key, []).append(value)
    collapsed = {g: [math.fsum(images)/len(images) for images in values[g].values()] for g in groups}
    return ReplicateValues(collapsed, excluded=excluded,
                           replicate_ids={g: list(values[g]) for g in groups},
                           image_counts={g: [len(images) for images in values[g].values()] for g in groups},
                           animals={g: len(animals[g]) for g in groups})


def recommendations(rows: Iterable[Mapping], group_order: Sequence[str] | None = None,
                    unit: str = "replicate") -> list[dict]:
    """One intensity and optional positive-area candidate per cohort/channel/projection, with
    `unit` as one n (docs/PLAN.md §4-19)."""
    blocks = {}
    for row in rows:
        key = tuple(_text(row.get(k)) for k in ("cohort", "channel", "marker", "projection"))
        blocks.setdefault(key, []).append(row)
    candidates = []
    for (cohort, channel, marker, projection), block in blocks.items():
        # One animal in two groups (§4-32): the groups are not independent, so no unpaired test.
        in_groups: dict[str, list[str]] = {}
        for r in block:
            group, replicate = _text(r.get("group")), _text(r.get("replicate"))
            if group and replicate and group not in in_groups.setdefault(replicate, []):
                in_groups[replicate].append(group)
        shared = {a: gs for a, gs in in_groups.items() if len(gs) > 1}
        quantities = ["mean"]
        if any(math.isfinite(_number(r.get("threshold"))) for r in block):
            quantities.append("positive_pct")
        for quantity in quantities:
            values = replicate_values(block, marker, quantity, group_order=group_order, unit=unit)
            warnings = list(dict.fromkeys(_text(r.get("warnings")) for r in block if _text(r.get("warnings"))))
            if values.excluded_rows:
                warnings.append(f"Excluded {values.excluded_rows} rows: {values.excluded}")
            specs = sorted({str(r["spec"]) for r in block if r.get("spec")})
            if len(specs) > 1:
                warnings.append("Multiple input spec hashes; verify that measurement settings are comparable")
            thresholds = sorted({float(r["threshold"]) for r in block if math.isfinite(_number(r.get("threshold")))})
            if quantity == "positive_pct" and (len(thresholds) > 1 or any(not math.isfinite(_number(r.get("threshold"))) for r in block)):
                warnings.append("Thresholds differ or are missing across images; compare with caution")
            n = {g: len(v) for g, v in values.items()}
            if shared:
                test = "No test"
                warnings.append("No test: the same animal is in more than one group ("
                                + "; ".join(f"{a}: {', '.join(gs)}" for a, gs in shared.items()) + ")")
            elif len(values) < 2 or any(size < 2 for size in n.values()):
                test = "No test"
                counted = "biological replicates" if unit == "replicate" else UNIT_NAMES[unit]
                warnings.append(f"No test: at least two groups and n >= 2 {counted} in every group are required")
            else:
                test = "Student t-test" if len(values) == 2 else "One-way ANOVA + Tukey HSD"
            if unit != "replicate":
                warnings.append(NOT_INDEPENDENT.format(unit=UNIT_NAMES[unit])
                                + (ROI_FALSE_POSITIVES if unit == "roi" else ""))
            candidates.append({"title": f"{marker or 'Channel '+channel} {'intensity' if quantity == 'mean' else 'area %'}",
                               "cohort": cohort, "channel": channel, "marker": marker,
                               "projection": projection, "quantity": quantity, "groups": list(values),
                               "n": n, "unit": unit, "animals": values.animals, "test_name": test, "warnings": warnings, "values": dict(values),
                               "replicate_ids": values.replicate_ids, "image_counts": values.image_counts,
                               "excluded": values.excluded, "excluded_rows": values.excluded_rows,
                               "spec_hashes": specs, "thresholds": thresholds})
    for index, candidate in enumerate(candidates):
        candidate["candidate_index"] = index+1
        candidate["total_candidates"] = len(candidates)
    return candidates


def candidate_statistics(candidate: Mapping, values: Mapping | None = None) -> dict:
    """Describe every group and run only the candidate's predeclared unpaired test."""
    values = candidate["values"] if values is None else values
    descriptions = {g: describe(values[g]) for g in candidate["groups"]}
    result = {"descriptive": descriptions, "test": None, "comparisons": [],
              "star_thresholds": [{"p_lt": p, "label": label} for p, label in STAR_THRESHOLDS],
              "warnings": list(candidate["warnings"])}
    if candidate["test_name"] == "No test":
        return result
    arrays = [values[g] for g in candidate["groups"]]
    if all(descriptions[g]["sd"] == 0 for g in candidate["groups"]):
        result["warnings"].append("No test: all groups have zero within-group variance")
        return result
    if len(arrays) == 2:
        test = t_test(*arrays)
        result["test"] = test
        result["comparisons"] = [{"i": 0, "j": 1, **test}]
    else:
        result["test"] = one_way_anova(arrays)
        result["comparisons"] = tukey_hsd(arrays)
    return result
