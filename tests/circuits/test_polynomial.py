"""Tests for flowguard.circuits.polynomial: convention, evaluation, validation."""

import pytest

from flowguard.circuits import Polynomial


# --- expected ---

def test_degree_one_first_convention():
    # [1, 2] -> f(v) = v + 2v^2  (the plan's f1)
    f1 = Polynomial.from_list([1, 2])
    assert f1.evaluate(5) == 55.0
    assert f1.evaluate(1) == 3.0
    assert f1.degree == 2


def test_cubic_matches_plan_f2():
    # [1, 2, 3] -> f(v) = v + 2v^2 + 3v^3  (the plan's f2); f2(2) = 34
    assert Polynomial.from_list([1, 2, 3]).evaluate(2) == 34.0


def test_zero_input_always_zero_penalty():
    assert Polynomial.from_list([1, 2, 3]).evaluate(0) == 0.0


def test_as_list_round_trip():
    coefficients = [1, 2, 3]
    poly = Polynomial.from_list(coefficients)
    assert poly.as_list() == coefficients
    assert Polynomial.from_list(poly.as_list()) == poly


# --- edge ---

def test_trailing_zero_coefficient_is_valid():
    # [1, 0] -> f(v) = v with a nominal degree of 2
    poly = Polynomial.from_list([1, 0])
    assert poly.evaluate(4) == 4.0
    assert poly.degree == 2


def test_direct_construction_normalizes_to_tuple():
    assert Polynomial([2]) == Polynomial.from_list([2])
    assert isinstance(Polynomial([2]).coefficients, tuple)


def test_evaluate_returns_float_for_int_inputs():
    assert isinstance(Polynomial.from_list([1]).evaluate(3), float)


# --- failure ---

@pytest.mark.parametrize(
    "coefficients",
    [[], [0], [0, 0], [-1, 2], [1, float("inf")], [1, float("nan")], ["a"], [True]],
)
def test_invalid_coefficients_raise(coefficients):
    with pytest.raises(ValueError):
        Polynomial.from_list(coefficients)
