"""Immutable saved evaluations and a stable collection for a Building."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID


def json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
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
    return json.dumps(
        value,
        default=json_value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def identity(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class _FrozenJSON:
    __slots__ = ("_json",)

    def __setattr__(self, name, value):
        if name == "_json":
            try:
                object.__getattribute__(self, "_json")
            except AttributeError:
                object.__setattr__(self, name, value)
                return
        raise AttributeError("Saved calculation results are read-only")


class EnergyResult(_FrozenJSON):
    """Fixed hourly engine output plus explicitly bounded annual carrier totals."""

    __slots__ = ()

    def __init__(
        self,
        *,
        engine,
        scalars,
        hourly,
        units,
        diagnostics,
        artifacts,
        delivered_by_carrier,
        requirements=(),
        boundary="space_heating_and_fans",
        time_axis=(),
        annual=True,
        run_id=None,
    ):
        data = dict(
            engine=engine,
            scalars=scalars,
            hourly=hourly,
            units=units,
            diagnostics=diagnostics,
            artifacts=artifacts,
            delivered_by_carrier=delivered_by_carrier,
            requirements=requirements,
            boundary=boundary,
            time_axis=time_axis,
            annual=annual,
        )
        if run_id is not None:
            data["run_id"] = run_id
        self._json = encode(data)

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
        return (
            sum(self.delivered_by_carrier.values())
            if self.complete and self.annual
            else None
        )

    def summary(self):
        """Inspect calculation boundaries and completeness without hourly arrays."""
        return dict(
            engine=self.engine,
            complete=self.complete,
            annual=self.annual,
            boundary=self.boundary,
            requirements=self.requirements,
            annual_delivered_energy_kwh=self.annual_delivered_energy_kwh,
        )

    def __repr__(self):
        return f"EnergyResult(engine={self.engine[:24]!r}, complete={self.complete}, annual={self.annual})"


class Evaluation(_FrozenJSON):
    """Self-contained physical inputs, material path, settings and calculation identities."""

    __slots__ = ()

    def __init__(self, **data):
        self._json = encode(data)

    def to_dict(self):
        return json.loads(self._json)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save_bundle(self, directory):
        """Save a new portable bundle with external arrays and retained files.

        Parameters
        ----------
        directory : str or pathlib.Path
            New destination directory, relative to the caller's working directory.
            Existing destinations are refused. The completion manifest is written
            last; failed writes remove this call's incomplete destination.

        Returns
        -------
        pathlib.Path
            Absolute bundle directory. See ``docs/evaluation-bundles.md`` for
            the versioned format; the in-memory evaluation is unchanged.
        """
        from .io import save_evaluation_bundle

        return save_evaluation_bundle(self, directory)

    @classmethod
    def load_bundle(cls, directory):
        """Verify and eagerly load a saved bundle without executing calculations.

        All checksummed paths must remain inside the bundle and contain no
        symbolic links. This restores ordinary immutable JSON-backed results;
        consumers that only need metadata can call ``load_bundle_metadata``.
        """
        from .io import load_evaluation_bundle

        return cls.from_dict(load_evaluation_bundle(directory))

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

    def summary(self):
        """Inspect identities, energy boundary and assessment requirements."""
        return dict(
            id=self.id,
            state_id=self.state_id,
            path_id=self.path_id,
            energy_id=self.energy_id,
            lca_id=self.lca_id,
            energy=self.energy.summary(),
            lca=self.lca.to_dict(),
            diagnostics=self.diagnostics,
        )

    def matches(self, building):
        return self.state_id == building.snapshot().sha256

    def annual_energy(self):
        """Supply this saved evaluation's annual energy to a renovation report.

        Returns
        -------
        epsm_lca.AnnualEnergy
            Delivered carrier kWh tied to the saved building state. The source
            names both the evaluation and energy calculation. No simulation or
            file access occurs, and later building edits do not change it.

        Raises
        ------
        ValueError
            Energy is incomplete, does not cover a full year, or the saved
            building identity disagrees with its snapshot.

        Examples
        --------
        After evaluating the baseline and each renovation step, pass
        ``{0: baseline_result.annual_energy(), 1: step_result.annual_energy()}``
        as ``energy`` to ``assess_renovation``. See the renovation notebooks for
        a complete example with an actual annual RC run.
        """
        from epsm_core import BuildingSnapshot
        from epsm_lca import AnnualEnergy

        energy = self.energy
        if not energy.annual:
            raise ValueError("A renovation report requires annual energy")
        if not energy.complete:
            raise ValueError("A renovation report requires complete delivered energy")
        if BuildingSnapshot.from_dict(self.snapshot).sha256 != self.state_id:
            raise ValueError(
                "Saved evaluation state does not match its building snapshot"
            )
        return AnnualEnergy(
            state_id=self.state_id,
            delivered_by_carrier=energy.delivered_by_carrier,
            boundary=energy.boundary,
            source=f"{self.engine} evaluation {self.id}; energy calculation {self.energy_id}",
        )

    def __repr__(self):
        return f"Evaluation(engine={self.engine[:24]!r}, lca={self.lca.status[:24]!r}, id={self.id[:12]!r})"


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
