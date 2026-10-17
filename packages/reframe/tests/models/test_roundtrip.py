"""C-2 "Done when": round trip (model → JSON → model) is a property test, for every public
model and every public union / alias type."""

from __future__ import annotations

import importlib.util
import sys
import types
import typing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from pydantic import BaseModel, TypeAdapter

import reframe.models as models


def _load_strategies() -> ModuleType:
    # pytest runs with --import-mode=importlib: a helper next to the tests is loaded by path.
    spec = importlib.util.spec_from_file_location(
        "_reframe_model_strategies", Path(__file__).with_name("strategies.py")
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


strategies = _load_strategies()


def public_models() -> list[type[BaseModel]]:
    return [
        obj
        for name in models.__all__
        if isinstance(obj := getattr(models, name), type) and issubclass(obj, BaseModel)
    ]


def public_type_aliases() -> list[tuple[str, Any]]:
    """Unions and ``Annotated`` aliases of ``reframe.models``. Plain ``Literal`` aliases and
    enums are left out: their values are JSON scalars, the model round trip covers the fields
    that use them, and the JSON Schema snapshot pins their values."""
    result = []
    for name in models.__all__:
        obj = getattr(models, name)
        origin = typing.get_origin(obj)
        if (origin is not None and origin is not typing.Literal) or isinstance(
            obj, types.UnionType
        ):
            result.append((name, obj))
    return result


ROUND_TRIP = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def test_every_public_name_is_exported() -> None:
    assert len(models.__all__) == len(set(models.__all__))
    for name in models.__all__:
        assert hasattr(models, name), name
    # Every model class defined in a reframe.models module is public.
    defined = {
        obj
        for module in list(sys.modules.values())
        if module is not None and module.__name__.startswith("reframe.models.")
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == module.__name__
        and not obj.__name__.startswith("_")
    }
    assert defined <= set(public_models())


@pytest.mark.parametrize("model", public_models(), ids=lambda m: m.__name__)
def test_model_round_trip(model: type[BaseModel]) -> None:
    @ROUND_TRIP
    @given(instance=strategies.model_strategy(model))
    def check(instance: BaseModel) -> None:
        text = instance.model_dump_json()
        again = model.model_validate_json(text)
        assert again == instance
        assert again.model_dump_json() == text
        # The python-mode dump validates too (what the server does with request bodies).
        assert model.model_validate(instance.model_dump(mode="json")) == instance

    check()


@pytest.mark.parametrize(("name", "alias"), public_type_aliases(), ids=lambda v: str(v))
def test_alias_round_trip(name: str, alias: Any) -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(alias)

    @ROUND_TRIP
    @given(value=strategies.strategy_for(alias))
    def check(value: Any) -> None:
        text = adapter.dump_json(value)
        again = adapter.validate_json(text)
        assert again == value
        assert adapter.dump_json(again) == text

    check()
