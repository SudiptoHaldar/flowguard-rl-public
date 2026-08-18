"""Environment and configuration loading for flowguard-rl.

Env vars come from the process environment, with a repo-root ``.env`` loaded once at
import (``load_dotenv`` never overrides variables that are already set). Tunable
parameters (polynomial coefficients, horizons, tolerances) live in versioned YAML files
under ``config/`` and are read with :func:`load_config`; they must never be hard-coded.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_REQUIRED = object()


class MissingEnvVarError(RuntimeError):
    """Raised when a required environment variable is absent or invalid."""

    def __init__(self, name: str, detail: str = "is not set"):
        super().__init__(f"Required environment variable '{name}' {detail}")
        self.name = name


def get_str(name: str, default=_REQUIRED) -> str:
    value = os.environ.get(name)
    if value is None:
        if default is _REQUIRED:
            raise MissingEnvVarError(name)
        return default
    return value


def get_int(name: str, default=_REQUIRED) -> int:
    raw = os.environ.get(name)
    if raw is None:
        if default is _REQUIRED:
            raise MissingEnvVarError(name)
        return default
    try:
        return int(raw)
    except ValueError:
        raise MissingEnvVarError(name, f"must be an integer, got '{raw}'") from None


def load_config(path: "str | Path") -> dict:
    """Parse a YAML config file into a dict.

    Schema validation is deferred to the circuits spec group; this only guarantees
    well-formed YAML. Missing files raise ``FileNotFoundError``; malformed YAML raises
    ``yaml.YAMLError``.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
