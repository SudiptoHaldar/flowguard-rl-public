"""Tests for flowguard.rl.types: the vocabularies and records, all DB-free."""

import dataclasses

import pytest

from flowguard.rl.types import (
    ObservationMode,
    PenaltyAudit,
    RunStatus,
    TerminationReason,
    Trial,
)


# --- expected ---

def test_vocabularies_are_the_locked_lowercase_values():
    assert [s.value for s in RunStatus] == [
        "running",
        "completed",
        "failed",
        "abandoned",
    ]
    assert [r.value for r in TerminationReason] == [
        "budget_exhausted",
        "converged",
        "target_reached",
        "error",
        "interrupted",
    ]
    assert [m.value for m in ObservationMode] == ["opaque", "enhanced"]


def test_str_enum_members_are_strings():
    # This is what lets them bind straight into Text columns and compare to stored values.
    assert RunStatus.RUNNING == "running"
    assert isinstance(RunStatus.RUNNING, str)
    assert str(ObservationMode.OPAQUE) == "opaque"


def test_trial_defaults_to_no_audit():
    trial = Trial(0, (10.0, 10.0), 92.0)
    assert trial.audit is None
    assert trial.step_index == 0


# --- edge ---

def test_penalty_audit_total_sums_components():
    assert PenaltyAudit(3.0, 55.0, 34.0).total == 92.0


def test_types_module_imports_only_the_standard_library():
    # types.py must stay importable in DB-free paths (v2.02 proposers, v2.07 CLI), so it
    # may not pull in SQLAlchemy or the circuits package. Checked on the parsed imports,
    # not the raw text — the docstring mentions SQLAlchemy on purpose.
    import ast

    import flowguard.rl.types as types_module

    tree = ast.parse(open(types_module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported == {"__future__", "dataclasses", "enum"}


# --- failure ---

def test_records_are_frozen():
    trial = Trial(0, (1.0,), 5.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        trial.total_cost = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        PenaltyAudit(1.0, 2.0, 3.0).delay = 9.0


def test_unknown_vocabulary_value_rejected():
    with pytest.raises(ValueError):
        RunStatus("halted")
