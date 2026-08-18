"""Tests for flowguard.settings: env accessors and the YAML config loader."""

from pathlib import Path

import pytest
import yaml

from flowguard.settings import MissingEnvVarError, get_int, get_str, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- expected ---

def test_get_str_reads_env_var(monkeypatch):
    monkeypatch.setenv("FLOWGUARD_TEST_STR", "hello")
    assert get_str("FLOWGUARD_TEST_STR") == "hello"


def test_get_int_reads_env_var(monkeypatch):
    monkeypatch.setenv("FLOWGUARD_TEST_INT", "42")
    assert get_int("FLOWGUARD_TEST_INT") == 42


def test_load_config_parses_example_circuit():
    cfg = load_config(REPO_ROOT / "config" / "example_circuit.yaml")
    circuit = cfg["circuit"]
    assert circuit["name"] == "C1"
    assert circuit["external_nodes"] == ["N1", "N2"]
    n1, n2 = circuit["nodes"]
    assert n1["load_factor"] == 10 and n1["load_safety_cap"] == 16
    assert n2["load_factor"] == 5 and n2["load_safety_cap"] == 8
    assert n1["safety_penalty_coefficients"] == [1, 2, 3]


# --- edge ---

def test_missing_optional_var_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("FLOWGUARD_TEST_ABSENT", raising=False)
    assert get_str("FLOWGUARD_TEST_ABSENT", "fallback") == "fallback"
    assert get_int("FLOWGUARD_TEST_ABSENT", 7) == 7


# --- failure ---

def test_missing_required_var_raises_named_error(monkeypatch):
    monkeypatch.delenv("FLOWGUARD_TEST_ABSENT", raising=False)
    with pytest.raises(MissingEnvVarError, match="FLOWGUARD_TEST_ABSENT"):
        get_str("FLOWGUARD_TEST_ABSENT")


def test_non_integer_var_raises_named_error(monkeypatch):
    monkeypatch.setenv("FLOWGUARD_TEST_INT", "not-a-number")
    with pytest.raises(MissingEnvVarError, match="FLOWGUARD_TEST_INT"):
        get_int("FLOWGUARD_TEST_INT")


def test_malformed_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("circuit: [unclosed", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_config(bad)
