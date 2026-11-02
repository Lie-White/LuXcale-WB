"""P0: the environment keeps its files inside C:\\Imaging."""

from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def test_matplotlib_cache_stays_in_the_project():
    import imquant  # noqa: F401  (sets MPLCONFIGDIR before matplotlib loads)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.canvas.draw()  # forces the font cache to be built
    plt.close(fig)
    config = Path(matplotlib.get_configdir()).resolve()
    cache = Path(matplotlib.get_cachedir()).resolve()
    assert config.is_relative_to(PROJECT), config
    assert cache.is_relative_to(PROJECT), cache
