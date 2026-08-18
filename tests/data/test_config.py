"""Tests for flowguard.data.config: chart tunables come from YAML and validate at load."""

import pytest

from flowguard.data import config


@pytest.fixture(autouse=True)
def reset_config():
    config.reset()
    yield
    config.reset()


# --- expected ---

def test_defaults_load_from_yaml():
    assert config.default_max_points() == 1000
    assert config.max_points_ceiling() == 20000
    assert config.default_run_limit() == 50
    assert config.max_run_limit() == 500


def test_import_reads_nothing():
    """Route decorators run at import; config must not be pulled in with them."""
    config.reset()
    assert config._cache is None


# --- edge ---

def test_values_are_cached_after_first_read(monkeypatch):
    config.default_max_points()
    monkeypatch.setattr(
        config, "load_config", lambda path: pytest.fail("config re-read after caching")
    )
    assert config.default_max_points() == 1000


# --- failure ---

@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None, "many"])
def test_non_positive_int_rejected_at_load(monkeypatch, bad):
    monkeypatch.setattr(
        config,
        "load_config",
        lambda path: {
            "series": {"default_max_points": bad, "max_points_ceiling": 20000},
            "runs": {"default_limit": 50, "max_limit": 500},
        },
    )
    config.reset()
    with pytest.raises(ValueError, match="series.default_max_points"):
        config.default_max_points()


def test_ceiling_below_default_is_rejected(monkeypatch):
    """An incoherent pair fails when the config is read, not on the first odd request."""
    monkeypatch.setattr(
        config,
        "load_config",
        lambda path: {
            "series": {"default_max_points": 1000, "max_points_ceiling": 500},
            "runs": {"default_limit": 50, "max_limit": 500},
        },
    )
    config.reset()
    with pytest.raises(ValueError, match="max_points_ceiling must be >="):
        config.default_max_points()


def test_run_limit_pair_is_validated(monkeypatch):
    monkeypatch.setattr(
        config,
        "load_config",
        lambda path: {
            "series": {"default_max_points": 1000, "max_points_ceiling": 20000},
            "runs": {"default_limit": 500, "max_limit": 50},
        },
    )
    config.reset()
    with pytest.raises(ValueError, match="runs.max_limit must be >="):
        config.default_run_limit()
