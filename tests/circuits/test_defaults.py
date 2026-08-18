"""Tests for flowguard.circuits.defaults: config-sourced f1/f2/f3, caching, reset."""

import pytest

from flowguard.circuits import defaults


@pytest.fixture(autouse=True)
def clean_defaults_cache():
    defaults.reset()
    yield
    defaults.reset()


# --- expected ---

def test_defaults_match_circuit_defaults_yaml():
    assert defaults.default_overload().as_list() == [1, 2]
    assert defaults.default_safety().as_list() == [1, 2, 3, 4, 5]
    assert defaults.default_delay().as_list() == [1]


def test_import_reads_no_config():
    # The autouse fixture just reset; merely having imported the module must not
    # have (re)populated the cache.
    assert defaults._cache is None


# --- edge ---

def test_defaults_are_cached_until_reset():
    first = defaults.default_overload()
    assert defaults.default_overload() is first
    defaults.reset()
    assert defaults.default_overload() is not first


def test_reset_rereads_config(tmp_path, monkeypatch):
    tweaked = tmp_path / "circuit_defaults.yaml"
    tweaked.write_text(
        "overload_penalty_coefficients: [5]\n"
        "safety_penalty_coefficients: [1, 2, 3]\n"
        "delay_penalty_coefficients: [1]\n",
        encoding="utf-8",
    )
    assert defaults.default_overload().as_list() == [1, 2]
    monkeypatch.setattr(defaults, "_CONFIG_PATH", tweaked)
    defaults.reset()
    assert defaults.default_overload().as_list() == [5]


# --- failure ---

def test_missing_config_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(defaults, "_CONFIG_PATH", tmp_path / "absent.yaml")
    defaults.reset()
    with pytest.raises(FileNotFoundError):
        defaults.default_delay()
