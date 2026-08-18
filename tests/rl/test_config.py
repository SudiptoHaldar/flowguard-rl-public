"""Tests for flowguard.rl.config: tunables come from YAML and are validated at load."""

import pytest

from flowguard.rl import config


@pytest.fixture(autouse=True)
def reset_config():
    config.reset()
    yield
    config.reset()


# --- expected ---

def test_defaults_load_from_yaml():
    assert config.commit_every_n_steps() == 50
    assert config.stale_run_threshold_seconds() == 900
    # The trial budget is a formula (v2.02 D4), so config holds its coefficients, not a
    # constant — see flowguard.rl.driver.default_budget.
    assert config.budget_k() == 4
    assert config.budget_floor() == 50
    assert config.min_allocation() == 0.1
    assert config.random_simplex_concentration() == 1.0
    assert config.hill_climb_initial_step_fraction() == 0.25


# --- edge ---

def test_values_are_cached_until_reset(monkeypatch):
    assert config.commit_every_n_steps() == 50
    calls = []
    monkeypatch.setattr(
        config, "load_config", lambda path: calls.append(path) or {"recorder": {}}
    )
    assert config.commit_every_n_steps() == 50  # served from cache, loader not called
    assert calls == []


def test_import_reads_nothing():
    # The cache is only populated on first access, never at import time.
    config.reset()
    assert config._cache is None


# --- failure ---

@pytest.mark.parametrize("bad", [0, -1, 1.5, None, True, "50"])
def test_invalid_batch_size_rejected_at_load(monkeypatch, bad):
    monkeypatch.setattr(
        config,
        "load_config",
        lambda path: {
            "recorder": {
                "commit_every_n_steps": bad,
                "stale_run_threshold_seconds": 900,
            },
            "run": {"default_budget": 200},
        },
    )
    with pytest.raises(ValueError, match="commit_every_n_steps must be an integer"):
        config.commit_every_n_steps()
