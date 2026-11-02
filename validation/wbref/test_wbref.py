"""Hand-computed checks for the independent WB reference and generator."""

import math

import numpy as np
import tifffile

from validation.wbref.reference import (
    Lanes, Window, combine, holm_adjust, lane_columns, measure, normalise,
    rotate, rotate_mask,
)
from validation.wbref.synthetic import Band, make_blot, write_tiff


def test_rotate_three_by_three_ninety_degrees() -> None:
    image = np.arange(1, 10, dtype=np.uint16).reshape(3, 3)
    expected = np.array([[3, 6, 9], [2, 5, 8], [1, 4, 7]], dtype=np.float64)
    assert np.array_equal(rotate(image, 90), expected)


def test_zero_turn_preserves_image_and_mask() -> None:
    image = np.arange(12, dtype=np.uint16).reshape(3, 4)
    mask = image == 5
    assert np.array_equal(rotate(image, 0), image)
    assert np.array_equal(rotate_mask(mask, 0), mask)


def test_lane_rounding_uses_floor_and_ties_to_even() -> None:
    lanes = Lanes(3, 100, 300, 40.5, widths=(40.5, 41, 42))
    assert lane_columns(lanes, 500) == [(80, 120), (180, 221), (279, 321)]


def test_nine_row_profile_integrals_and_saturation() -> None:
    profile = np.array([10, 10, 10, 10, 20, 10, 10, 10, 10], dtype=np.uint16)
    mask = np.zeros_like(profile, dtype=bool)
    mask[4] = True
    rows = measure(profile[:, None], mask[:, None], Lanes(1, 0, 0, 1),
                   [Window(("upper", "lower"), 0, 9, (4,))])
    assert [row["value"] for row in rows] == [0.0, 10.0, 10.0]
    assert all(row["saturated"] for row in rows)
    assert [row["band"] for row in rows] == ["upper", "lower", "upper + lower"]


def test_holm_adjustment_hand_case() -> None:
    assert np.allclose(holm_adjust([0.01, 0.03, 0.04]), [0.03, 0.06, 0.06])


def test_normalise_and_complete_block_statistics() -> None:
    target = [{"lane": i + 1, "band": "T", "value": x} for i, x in enumerate((2, 4, 6))]
    loading = [{"lane": i + 1, "band": "L", "value": 2} for i in range(3)]
    norm = normalise(target, loading, ["Ref", "A", "A"], "Ref", "T", "L")
    assert [row["relative"] for row in norm] == [1.0, 2.0, 3.0]
    experiments = [
        {"experiment": "e1", "values": [
            {"group": "A", "relative": 1.0}, {"group": "B", "relative": 1.2},
            {"group": "C", "relative": 0.9}]},
        {"experiment": "e2", "values": [
            {"group": "A", "relative": 1.1}, {"group": "B", "relative": 1.3},
            {"group": "C", "relative": 1.0}]},
        {"experiment": "e3", "values": [
            {"group": "A", "relative": 1.2}, {"group": "B", "relative": 1.4}]},
    ]
    result = combine(experiments, ["A", "B", "C"])
    assert result["included_experiments"] == ["e1", "e2"]
    assert result["left_out_experiments"] == ["e3"]
    assert result["omnibus"]["df1"] == 2
    assert result["omnibus"]["df2"] == 2
    assert len(result["paired_tests"]) == 3


def test_integrated_gaussian_amount_and_tif_description(tmp_path) -> None:
    generated = make_blot((256, 160), [80], [Band(0, 500_000, 120, 4, 3)],
                          seed=17, background=3000, gradient=0.25)
    background = 3000 + 0.25 * np.arange(256)[:, None]
    recovered = np.sum(generated.image.astype(np.float64) - background)
    assert math.isclose(recovered, 500_000, rel_tol=4e-4)
    assert not generated.clipped_mask.any()
    path = write_tiff(tmp_path / "known_Ch.tif", generated.image)
    with tifffile.TiffFile(path) as tif:
        assert tif.asarray().dtype == np.uint16
        assert "Method=Chemiluminescence" in str(tif.pages[0].description)


def test_tilt_sign_levels_band_rows() -> None:
    angle = 3.0
    generated = make_blot((128, 160), [80], [Band(0, 1_000_000, 64, 6, 3)],
                          seed=5, background=0, gradient=0, tilt_degrees=angle)
    leveled = rotate(generated.image, angle)
    # The band peak is level to within a pixel after applying the same positive turn.
    peaks = np.argmax(leveled[:, 60:101], axis=0)
    assert int(peaks.max()) - int(peaks.min()) <= 1
