"""A function whose default argument is a real path reads that path even when a test has pointed the workspace somewhere else.

That is how the tests once passed on a machine that had already built the model and failed on a clean checkout. This test finds any
such default, so the mistake cannot come back.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import certivo_ml


def all_functions():
    for info in pkgutil.iter_modules(certivo_ml.__path__):
        module = importlib.import_module(f"certivo_ml.{info.name}")
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ == module.__name__:
                yield f"{module.__name__}.{name}", function


def test_no_function_has_a_path_as_a_default_argument():
    offenders = []
    for name, function in all_functions():
        for parameter in inspect.signature(function).parameters.values():
            if isinstance(parameter.default, Path):
                offenders.append(f"{name}({parameter.name}={parameter.default})")
    assert offenders == [], "defaults are fixed when the module loads; use None and look the path up inside: " + ", ".join(offenders)


def test_loading_the_model_follows_the_workspace_a_test_sets_up(workspace):
    from certivo_ml import baseline

    baseline.train()
    sums, counts, temperature = baseline.load_model()
    assert counts[0] + counts[1] == 360 and temperature > 0
    assert baseline.MODEL_PATH.is_relative_to(workspace)
