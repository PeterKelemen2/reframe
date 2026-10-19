"""Hypothesis strategies for the Reframe models, built from their type annotations.

Models whose validators need more than the annotations say get an entry in
:data:`MODEL_OVERRIDES` or :data:`FIELD_OVERRIDES`, so every generated value is valid.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
import types
import typing
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import annotated_types
from hypothesis import strategies as st
from pydantic import AwareDatetime, BaseModel, JsonValue, RootModel
from pydantic.fields import FieldInfo

from reframe.models import (
    AudioCodecRule,
    AudioCodecRules,
    AudioDefaults,
    BatchGrouping,
    BatchResolution,
    BitrateInfo,
    BitrateSource,
    Resolution,
)

Strategy = st.SearchStrategy[Any]

JSON_SAFE_INT = 2**53
_SAFE_TEXT = st.text(alphabet=st.characters(codec="utf-8", exclude_categories=["Cs"]), max_size=12)
_PATH_SEGMENT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ",
    min_size=1,
    max_size=8,
).filter(lambda s: s.strip() not in ("", ".", ".."))

_JSON_SCALARS: Strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-JSON_SAFE_INT, JSON_SAFE_INT),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    _SAFE_TEXT,
)
JSON_VALUES: Strategy = st.recursive(
    _JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(_SAFE_TEXT, children, max_size=3),
    ),
    max_leaves=6,
)


def _paths() -> Strategy:
    return st.lists(_PATH_SEGMENT, min_size=1, max_size=3).map(lambda parts: Path(*parts))


def _datetimes() -> Strategy:
    offsets = st.sampled_from([0, 60, -300, 330, 840]).map(
        lambda minutes: dt.timezone(dt.timedelta(minutes=minutes))
    )
    return st.datetimes(
        min_value=dt.datetime(2000, 1, 1), max_value=dt.datetime(2100, 1, 1), timezones=offsets
    )


class _Bounds:
    def __init__(self, metadata: Sequence[Any]) -> None:
        self.ge: float | None = None
        self.gt: float | None = None
        self.le: float | None = None
        self.lt: float | None = None
        self.min_length: int | None = None
        self.max_length: int | None = None
        self.pattern: str | None = None
        for item in _flatten(metadata):
            for name in ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern"):
                value = getattr(item, name, None)
                if value is not None:
                    setattr(self, name, value)


def _flatten(metadata: Sequence[Any]) -> list[Any]:
    items: list[Any] = []
    for item in metadata:
        if isinstance(item, FieldInfo):
            items.extend(_flatten(item.metadata))
        elif isinstance(item, annotated_types.GroupedMetadata):
            items.extend(_flatten(list(item)))
        else:
            items.append(item)
    return items


def _ints(b: _Bounds) -> Strategy:
    low = -JSON_SAFE_INT
    high = JSON_SAFE_INT
    if b.ge is not None:
        low = int(b.ge)
    if b.gt is not None:
        low = int(b.gt) + 1
    if b.le is not None:
        high = int(b.le)
    if b.lt is not None:
        high = int(b.lt) - 1
    return st.integers(low, high)


def _floats(b: _Bounds) -> Strategy:
    low = b.ge if b.ge is not None else b.gt
    high = b.le if b.le is not None else b.lt
    return st.floats(
        min_value=-1e15 if low is None else float(low),
        max_value=1e15 if high is None else float(high),
        exclude_min=b.gt is not None,
        exclude_max=b.lt is not None,
        allow_nan=False,
        allow_infinity=False,
    )


def _strings(b: _Bounds) -> Strategy:
    if b.pattern is not None:
        strategy: Strategy = st.from_regex(re.compile(b.pattern), fullmatch=True).filter(
            lambda s: "\n" not in s and "\x00" not in s
        )
    else:
        strategy = st.text(
            alphabet=st.characters(codec="utf-8", exclude_categories=["Cs"]),
            min_size=b.min_length or 0,
            max_size=max(b.max_length or 12, b.min_length or 0),
        )
    if b.max_length is not None:
        limit = b.max_length
        strategy = strategy.filter(lambda s: len(s) <= limit)
    if b.min_length is not None:
        floor = b.min_length
        strategy = strategy.filter(lambda s: len(s) >= floor)
    return strategy


def strategy_for(tp: Any, metadata: Sequence[Any] = ()) -> Strategy:
    """A strategy for values of the annotation ``tp`` (with pydantic field metadata)."""
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        base, *extra = typing.get_args(tp)
        return strategy_for(base, [*metadata, *extra])
    if tp is JsonValue:
        return JSON_VALUES
    if tp is type(None) or tp is None:
        return st.none()
    if origin is typing.Union or isinstance(tp, types.UnionType):
        return st.one_of([strategy_for(arg, metadata) for arg in typing.get_args(tp)])
    if origin is typing.Literal:
        return st.sampled_from(typing.get_args(tp))
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return st.sampled_from(list(tp))
    bounds = _Bounds(metadata)
    if origin is list:
        (item,) = typing.get_args(tp)
        return st.lists(
            strategy_for(item),
            min_size=bounds.min_length or 0,
            max_size=max(bounds.max_length or 3, bounds.min_length or 0),
        )
    if origin is dict:
        key, value = typing.get_args(tp)
        return st.dictionaries(strategy_for(key), strategy_for(value), max_size=3)
    if tp is bool:
        return st.booleans()
    if tp is int:
        return _ints(bounds)
    if tp is float:
        return _floats(bounds)
    if tp is str:
        return _strings(bounds)
    if tp is Path:
        return _paths()
    if tp is AwareDatetime or tp is dt.datetime:
        return _datetimes()
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return st.deferred(lambda: model_strategy(tp))
    raise NotImplementedError(f"no strategy for {tp!r}")


def _catch_all(rule: AudioCodecRule) -> AudioCodecRule:
    return rule.model_copy(update={"languages": None, "source_channels": "any"})


def _rules_with_catch_all() -> Strategy:
    rule = model_strategy(AudioCodecRule)
    return st.tuples(st.lists(rule, max_size=3), rule.map(_catch_all)).map(
        lambda pair: [*pair[0], pair[1]]
    )


def _at_most_one(model: type[BaseModel]) -> Callable[[], Strategy]:
    return lambda: st.lists(model_strategy(model), max_size=1)


#: Strategies for single fields whose validators the annotation does not express, or whose
#: items are too large to generate three of.
FIELD_OVERRIDES: dict[tuple[type[BaseModel], str], Callable[[], Strategy]] = {
    (AudioDefaults, "codec_rules"): _rules_with_catch_all,
    (AudioCodecRules, "rules"): _rules_with_catch_all,
    (BatchResolution, "rows"): _at_most_one(Resolution),
    (BatchGrouping, "groups"): lambda: st.lists(st.deferred(_group), max_size=1),
}


def _group() -> Strategy:
    from reframe.models import BatchGroup

    return model_strategy(BatchGroup)


def _bitrates() -> Strategy:
    known = st.builds(
        BitrateInfo,
        value=st.integers(0, 10**9),
        source=st.sampled_from([s for s in BitrateSource if s is not BitrateSource.UNKNOWN]),
    )
    return st.one_of(st.just(BitrateInfo()), known)


#: Whole-model strategies for models with cross-field validators.
MODEL_OVERRIDES: dict[type[BaseModel], Callable[[], Strategy]] = {
    BitrateInfo: _bitrates,
}

_CACHE: dict[type[BaseModel], Strategy] = {}


def model_strategy(model: type[BaseModel]) -> Strategy:
    """Valid instances of ``model`` (every field generated)."""
    if model in _CACHE:
        return _CACHE[model]
    if model in MODEL_OVERRIDES:
        strategy = MODEL_OVERRIDES[model]()
    elif issubclass(model, RootModel):
        field = model.model_fields["root"]
        strategy = strategy_for(field.annotation, field.metadata).map(model)
    else:
        fields: dict[str, Strategy] = {}
        for name, field in model.model_fields.items():
            override = FIELD_OVERRIDES.get((model, name))
            if override is not None:
                fields[name] = override()
            else:
                fields[name] = strategy_for(field.annotation, field.metadata)
        strategy = st.fixed_dictionaries(fields).map(lambda values: model(**values))
    _CACHE[model] = strategy
    return strategy
