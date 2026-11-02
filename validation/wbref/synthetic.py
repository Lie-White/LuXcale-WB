"""Seeded synthetic WB blots with amounts defined by construction."""

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import tifffile


@dataclass(frozen=True)
class Band:
    """One integrated-Gaussian band assigned to a lane."""

    lane: int
    amount: float
    centre_y: float
    sigma_x: float
    sigma_y: float


@dataclass(frozen=True)
class SyntheticBlot:
    """Raw TIF values, the pre-turn clip mask, and known per-band amounts."""

    image: np.ndarray
    clipped_mask: np.ndarray
    amounts: tuple[float, ...]


def amount_vectors(seed: int, count: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """Draw loading amounts and mean-one target/loading ratios."""
    rng = np.random.default_rng(seed)
    loading = rng.uniform(800_000, 1_200_000, count)
    ratios = rng.uniform(0.8, 1.2, count)
    ratios /= ratios.mean()
    return loading, loading * ratios


def _erf(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    return np.fromiter((math.erf(float(value)) for value in values.flat),
                       dtype=np.float64, count=values.size).reshape(values.shape)


def _pixel_mass(centres: np.ndarray, sigma: float) -> np.ndarray:
    root_two_sigma = math.sqrt(2) * sigma
    return 0.5 * (_erf((centres + 0.5) / root_two_sigma) -
                  _erf((centres - 0.5) / root_two_sigma))


def make_blot(shape: tuple[int, int], lane_centres: tuple[float, ...] | list[float],
              bands: tuple[Band, ...] | list[Band], *, seed: int,
              background: float = 3000.0, gradient: float = 0.25,
              noise_sigma: float = 0.0, tilt_degrees: float = 0.0) -> SyntheticBlot:
    """Construct pixel-integrated normalized 2-D Gaussian bands and write no files."""
    height, width = shape
    if height < 1 or width < 1 or not lane_centres:
        raise ValueError("shape and lane centres must be non-empty")
    image = background + gradient * np.arange(height, dtype=np.float64)[:, None]
    image = np.broadcast_to(image, shape).copy()
    amounts = []
    slope = math.tan(math.radians(tilt_degrees))
    for band in bands:
        if not 0 <= band.lane < len(lane_centres):
            raise ValueError("band lane index is outside lane_centres")
        if band.amount < 0 or band.sigma_x <= 0 or band.sigma_y <= 0:
            raise ValueError("band amount and sigmas must be valid")
        centre_x = float(lane_centres[band.lane])
        x_min = max(0, int(math.floor(centre_x - 5 * band.sigma_x)))
        x_max = min(width, int(math.ceil(centre_x + 5 * band.sigma_x)) + 1)
        x_values = np.arange(x_min, x_max, dtype=np.float64)
        x_mass = _pixel_mass(x_values - centre_x, band.sigma_x)
        y_values = np.arange(height, dtype=np.float64)
        if slope == 0.0:
            y_mass = _pixel_mass(y_values - band.centre_y, band.sigma_y)
            image[:, x_min:x_max] += band.amount * y_mass[:, None] * x_mass[None, :]
        else:
            row_centres = band.centre_y + slope * (x_values - centre_x)
            y_mass = np.empty((height, len(x_values)), dtype=np.float64)
            for j, row_centre in enumerate(row_centres):
                y_mass[:, j] = _pixel_mass(y_values - row_centre, band.sigma_y)
            image[:, x_min:x_max] += band.amount * y_mass * x_mass[None, :]
        amounts.append(float(band.amount))
    if noise_sigma:
        image += np.random.default_rng(seed).normal(0, noise_sigma, shape)
    raw = np.rint(np.clip(image, 0, 65535)).astype(np.uint16)
    clipped = raw >= 65535
    return SyntheticBlot(raw, clipped, tuple(amounts))


def write_tiff(path: str | Path, image: np.ndarray) -> Path:
    """Write a single-channel uint16 chemiluminescence TIF."""
    path = Path(path)
    image = np.asarray(image)
    if image.ndim != 2 or image.dtype != np.uint16:
        raise ValueError("synthetic TIF input must be a 2-D uint16 image")
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, image, description="Method=Chemiluminescence")
    return path


def s6_cases() -> list[dict]:
    """Generate the frozen 24 multi-experiment settings in PLAN.md."""
    cases = []
    for index in range(24):
        seed = 6001 + index
        group_count = 2 if index % 2 == 0 else 3
        experiment_count = 2 + index % 4
        groups = [f"G{i}" for i in range(group_count)]
        rng = np.random.default_rng(seed)
        effects = (0.0, 0.18, -0.12)
        experiments = []
        for experiment_i in range(experiment_count):
            block_effect = float(rng.normal(0, 0.12))
            group_values = {}
            for group_i, group in enumerate(groups):
                if group_count == 3 and index % 3 == 0 and experiment_i == experiment_count - 1 and group_i == 2:
                    continue
                lane_error = rng.normal(0, 0.06, 3)
                group_values[group] = np.exp(effects[group_i] + block_effect + lane_error).tolist()
            experiments.append({"experiment": f"S6-{index:02d}-E{experiment_i + 1}",
                                "groups": group_values})
        cases.append({"case": f"S6-{index:02d}", "seed": seed, "groups": groups,
                      "experiments": experiments})
    return cases
