"""Biological-replicate collapsing, missingness, and recommendation multiplicity."""

import math

import pytest

from imquant.recommend import candidate_statistics, recommendations, replicate_values


def example_rows(groups=("control", "treated"), channels: int = 4) -> list[dict]:
    rows = []
    for group_index, group in enumerate(groups):
        for replicate in range(2):
            for image in range(3):
                for channel in range(channels):
                    rows.append({"image": f"{group}-{replicate}-{image}", "cohort": "cohort-A",
                                 "group": group, "replicate": f"{group}-r{replicate}",
                                 "channel": channel, "marker": f"marker{channel}", "projection": "max",
                                 "mean": 10*group_index + 3*replicate + image + channel,
                                 "threshold": 5 if channel < 2 else "",
                                 "positive_pct": 20*group_index + 2*replicate + image if channel < 2 else "",
                                 "spec": "test-spec-123", "warnings": "saturation; JPG"})
    return rows


def test_B4_two_replicates_three_images_each():
    rows = example_rows(channels=1)
    values = replicate_values(rows, "marker0", "mean")
    assert values == {"control": [1, 4], "treated": [11, 14]}
    assert values.image_counts == {"control": [3, 3], "treated": [3, 3]}
    candidate = recommendations(rows)[0]
    assert candidate["n"] == {"control": 2, "treated": 2}
    assert candidate_statistics(candidate)["test"]["df"] == 2  # not image df=10


def test_B4_n_below_two_never_runs_a_test(monkeypatch):
    import imquant.recommend as module

    rows = [r for r in example_rows(channels=1) if r["replicate"].endswith("r0")]
    candidate = recommendations(rows)[0]
    assert candidate["test_name"] == "No test"
    monkeypatch.setattr(module, "t_test", lambda *a, **kw: pytest.fail("n<2 must not run a test"))
    assert candidate_statistics(candidate)["test"] is None
    assert any("n >= 2 biological" in w for w in candidate["warnings"])


def test_B7_candidate_count_and_metadata():
    candidates = recommendations(example_rows())
    assert len(candidates) == 6
    assert sum(c["quantity"] == "mean" for c in candidates) == 4
    assert sum(c["quantity"] == "positive_pct" for c in candidates) == 2
    assert all(c["total_candidates"] == 6 for c in candidates)
    assert all(c["spec_hashes"] == ["test-spec-123"] for c in candidates)
    assert all("saturation; JPG" in c["warnings"] for c in candidates)


def test_missing_values_ids_and_empty_groups():
    rows = example_rows(channels=1)
    rows[0]["mean"] = ""
    rows[1]["mean"] = math.nan
    rows[3]["replicate"] = ""
    values = replicate_values(rows, "marker0", "mean")
    assert values["control"] == [2, 4.5]
    assert values.excluded_rows == 3
    assert values.excluded == {"missing_group": 0, "missing_replicate": 1, "missing_value": 2}
    assert values.image_counts["control"] == [1, 2]
    for row in rows:
        if row["group"] == "treated":
            row["mean"] = ""
    candidate = recommendations(rows)[0]
    assert candidate["n"]["treated"] == 0
    assert candidate["test_name"] == "No test"
    assert candidate_statistics(candidate)["test"] is None


def test_group_order_and_anova():
    rows = example_rows(groups=("z", "a", "b"), channels=1)
    candidate = recommendations(rows)[0]
    assert candidate["groups"] == ["z", "a", "b"]
    candidate = recommendations(rows, group_order=["b", "z", "a"])[0]
    assert candidate["groups"] == ["b", "z", "a"]
    stats = candidate_statistics(candidate)
    assert stats["test"]["df1"] == 2
    assert len(stats["comparisons"]) == 3
    with pytest.raises(ValueError):
        recommendations(rows, group_order=["z", "a"])


def test_cohorts_channels_and_projection_are_not_pooled():
    rows = example_rows(channels=1)
    other = [{**r, "cohort": "cohort-B", "projection": "mean"} for r in rows]
    assert len(recommendations(rows+other)) == 4
    with pytest.raises(ValueError):
        replicate_values(rows+other, "marker0", "mean")
    with pytest.raises(ValueError):
        replicate_values(rows+[rows[0]], "marker0", "mean")


def test_mixed_specs_and_thresholds_reported():
    rows = example_rows(channels=1)
    rows[0]["spec"], rows[0]["threshold"] = "second-spec", 9
    candidate = next(c for c in recommendations(rows) if c["quantity"] == "positive_pct")
    assert len(candidate["spec_hashes"]) == 2
    assert any("Thresholds differ" in w for w in candidate["warnings"])
    assert any("Multiple input spec" in w for w in candidate["warnings"])


def test_constant_data_no_test():
    rows = example_rows(channels=1)
    for row in rows:
        row["mean"] = 3
    stats = candidate_statistics(recommendations(rows)[0])
    assert stats["test"] is None
    assert any("zero within-group variance" in w for w in stats["warnings"])


def test_none_is_not_a_biological_replicate_id():
    rows = example_rows(channels=1)
    rows[0]["replicate"] = None
    values = replicate_values(rows, "marker0", "mean")
    assert values.excluded["missing_replicate"] == 1
    assert "None" not in values.replicate_ids["control"]
