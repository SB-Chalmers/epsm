"""Immutable saved evaluations and a stable collection for a Building."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
import hashlib
import json


def json_value(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"No portable representation for {type(value).__name__}")


def encode(value):
    return json.dumps(value, default=json_value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class EnergyResult:
    """Fixed hourly engine output plus explicitly bounded annual carrier totals."""

    def __init__(self, *, engine, scalars, hourly, units, diagnostics, artifacts,
                 delivered_by_carrier, requirements=(), boundary="space_heating_and_fans",
                 time_axis=(), annual=True):
        self._json = encode(dict(engine=engine, scalars=scalars, hourly=hourly, units=units,
                                 diagnostics=diagnostics, artifacts=artifacts,
                                 delivered_by_carrier=delivered_by_carrier,
                                 requirements=requirements, boundary=boundary,
                                 time_axis=time_axis, annual=annual))

    def to_dict(self):
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def __getattr__(self, name):
        data = self.to_dict()
        if name in data:
            return data[name]
        raise AttributeError(name)

    @property
    def complete(self):
        return not self.requirements and self.diagnostics.get("accepted", True)

    @property
    def annual_delivered_energy_kwh(self):
        return sum(self.delivered_by_carrier.values()) if self.complete and self.annual else None


class Evaluation:
    """Self-contained physical inputs, material path, settings and calculation identities."""

    def __init__(self, **data):
        self._json = encode(data)

    def to_dict(self):
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def __getattr__(self, name):
        data = self.to_dict()
        if name == "energy":
            return EnergyResult.from_dict(data[name])
        if name == "lca":
            from epsm_lca import LCAResult
            return LCAResult.from_dict(data[name])
        if name in data:
            return data[name]
        raise AttributeError(name)

    def matches(self, building):
        return self.state_id == building.snapshot().sha256

    def __repr__(self):
        return f"Evaluation(engine={self.engine!r}, lca={self.lca.status!r}, id={self.id[:12]!r})"


class Results(Sequence):
    """Append-only evaluation collection; editing a Building never rewrites it."""

    def __init__(self):
        self._entries = []

    def __len__(self):
        return len(self._entries)

    def __getitem__(self, index):
        return self._entries[index]

    @property
    def latest(self):
        return self._entries[-1] if self._entries else None

    def for_engine(self, engine):
        return tuple(r for r in self if r.engine == engine)

    def for_current_state(self, building):
        return tuple(r for r in self if r.matches(building))

    def _append(self, result):
        self._entries.append(result)

    def __repr__(self):
        return f"Results(evaluations={len(self)})"
