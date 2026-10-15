"""Public researcher interface over the single physical Core Building."""

from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

from epsm_core import Building as CoreBuilding
from epsm_core import BuildingSnapshot, Weather
from epsm_lca import AssessmentSettings, LCAResult, assess

from epsm._logging import bind_context, call_with_context, context_logger
from epsm._logging import operation as logged_operation

from .cache import EvaluationCache
from .energy import normalize_energy
from .provenance import evaluation_identity, implementation_identity
from .results import Evaluation, Results, encode, identity

logger = context_logger(__name__)


class Building(CoreBuilding):
    """A Core Building with record, simulation and automatic LCA conveniences.

    ``Building()`` starts empty, following Core. Select
    ``preset='illustrative-reference'`` for Core's teaching inputs. Assessment
    settings must be explicit before
    a complete LCA can be produced. EnergyPlus is an external prerequisite;
    install the RC extra to use ``engine='epsm_rc'``.
    """

    def __init__(self, *args, assessment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assessment = deepcopy(assessment)
        self._results = Results()
        self._evaluation_cache = EvaluationCache()
        self._baseline_inventory = None
        self._source_record = None
        self._archetype_applications = ()

    @property
    def archetype_applications(self):
        """Immutable application records, in application order."""
        return self._archetype_applications

    @logged_operation("building.archetype.apply")
    def apply_archetype(self, archetype, *, mode="replace", calendar=None):
        """Apply a catalogue or authored definition to existing geometry in place.

        Replace supplied roles and sections, or fill missing assignments while
        retaining existing choices. Invalid supplied values raise before changes.
        Missing systems, calendars and reference bases remain explicit in the
        returned ArchetypeApplicationReport. Openings and geometry are preserved.
        """
        from .archetypes import apply_archetype

        return apply_archetype(self, archetype, mode=mode, calendar=calendar)

    @property
    def results(self):
        return self._results

    def _copy_runtime_configuration_to(self, child):
        child.assessment = deepcopy(self.assessment)
        child._evaluation_cache = self._evaluation_cache
        child._source_record = deepcopy(self._source_record)
        child._archetype_applications = self.archetype_applications
        child._baseline_inventory = deepcopy(
            self._baseline_inventory
            if self._baseline_inventory is not None
            else (self.quantities().to_dict() if self.readiness("quantities") else None)
        )

    @classmethod
    @logged_operation("building.record.convert")
    def from_record(cls, record, *, archetype=None, calendar=None, **options):
        """Copy observed geometry and evidence, retaining unresolved model inputs.

        Swedish DB footprints are projected metric coordinates. Geometry needs
        storeys and height/elevations; missing source heights remain unresolved.
        ``archetype`` is an explicitly selected Data definition, applied through
        ``apply_archetype`` after geometry and source evidence are retained.
        ``calendar`` belongs to that application. Omitting the archetype leaves
        existing gradual authoring behaviour. Choices never become measurements.
        """
        from .records import building_from_record

        return building_from_record(
            cls, record, archetype=archetype, calendar=calendar, **options
        )

    def compare(self, record=None):
        """Compare like-unit model properties with preserved source evidence."""
        from .records import compare_record

        return compare_record(self, record or self._source_record)

    def to_dict(self):
        """Portable physical state and evaluation settings; no live services/results."""
        return dict(
            format="epsm-building-1",
            building=self.snapshot().to_dict(),
            assessment=self.assessment.to_dict() if self.assessment else None,
            baseline_inventory=deepcopy(self._baseline_inventory),
            source_record=json.loads(encode(self._source_record)),
            lineage=self.lineage_to_dict(),
            archetype_applications=[
                report.to_dict() for report in self.archetype_applications
            ],
        )

    @classmethod
    def from_dict(cls, data):
        if data.get("format") != "epsm-building-1":
            return CoreBuilding.from_dict.__func__(cls, data)
        building = BuildingSnapshot.from_dict(data["building"]).to_building(
            building_type=cls
        )
        building.assessment = (
            AssessmentSettings.from_dict(data["assessment"])
            if data["assessment"]
            else None
        )
        building._baseline_inventory = deepcopy(data.get("baseline_inventory"))
        building._source_record = deepcopy(data.get("source_record"))
        from .archetypes import ArchetypeApplicationReport

        building._archetype_applications = tuple(
            ArchetypeApplicationReport.from_dict(report)
            for report in data.get("archetype_applications", ())
        )
        building.restore_lineage(data.get("lineage", {}))
        return building

    @logged_operation("evaluation", traceback=True)
    def simulate(
        self, *, engine="energyplus", weather, directory=None, cache=None, **options
    ):
        """Freeze inputs, calculate energy, assess LCA and append one evaluation.

        An incomplete or failed LCA leaves energy accessible. Cache entries hold
        separate energy/LCA calculations, so changing factors reuses energy.
        Each call still appends a distinct evaluation. Artifacts are retained in
        a unique evaluation subdirectory below the supplied directory, or ``outputs/epsm``.
        RC requires explicit ``settings=RCSettings.from_policy(...)``. These are
        energy model choices, separate from ``building.assessment``. The automatic
        LCA is one reached state's cumulative material and energy result. Use
        ``assess_renovation`` with each evaluation's ``annual_energy()`` to compare
        the baseline and all recorded steps.
        """
        if engine not in {"energyplus", "epsm_rc"}:
            raise ValueError("engine must be 'energyplus' or 'epsm_rc'")
        if not isinstance(weather, Weather):
            weather = Weather.from_epw(weather)
        self.readiness(engine=engine, weather=weather).require()
        snapshot = self.snapshot()
        application_records = [
            report.to_dict() for report in self.archetype_applications
        ]
        frozen = snapshot.to_building()
        settings = (
            AssessmentSettings.from_dict(self.assessment.to_dict())
            if self.assessment
            else None
        )
        evaluation_id = uuid.uuid4().hex
        bind_context(evaluation_id=evaluation_id)
        output = Path(directory or Path("outputs") / "epsm").resolve() / evaluation_id
        output.mkdir(parents=True, exist_ok=True)
        from epsm_core.weather import file_sha256

        if file_sha256(weather.path) != weather.sha256:
            raise ValueError(
                "Weather changed after it was inspected; create a new Weather object"
            )
        weather_path = output / "weather.epw"
        if Path(weather.path).resolve() != weather_path:
            shutil.copyfile(weather.path, weather_path)
        frozen_weather = Weather.from_epw(
            weather_path,
            calendar_year=weather.climate.calendar_year,
            provenance=weather.provenance,
        )
        spec = call_with_context(frozen.to_spec, frozen_weather)
        quantities = frozen.quantities()
        flows = deepcopy(self.material_flows)
        cache = cache if cache is not None else self._evaluation_cache
        runtime = evaluation_identity(engine=engine, weather=frozen_weather, **options)
        key = identity(
            dict(format=3, physical=spec.physical_dict(), runtime=runtime["energy"])
        )
        logger.info(
            "Energy calculation started",
            extra={
                "epsm_event": "evaluation.energy.started",
                "epsm_context": {"evaluation_id": evaluation_id, "energy_id": key},
                "epsm_details": {"engine": engine},
            },
        )
        energy_data = cache.get("energy", key)
        reused_energy = energy_data is not None
        logger.debug(
            "Energy cache %s",
            "hit" if reused_energy else "miss",
            extra={
                "epsm_event": "evaluation.energy.cache",
                "epsm_details": {"reused": reused_energy, "energy_id": key},
            },
        )
        if energy_data is None:
            if engine == "energyplus":
                from epsm_core import run_building

                raw = call_with_context(
                    run_building,
                    frozen,
                    weather=frozen_weather,
                    directory=output / "energy",
                    **options,
                )
            else:
                from epsm_rc import simulate_building

                raw = call_with_context(
                    simulate_building,
                    frozen,
                    weather=frozen_weather,
                    directory=output / "energy",
                    **options,
                )
            energy = normalize_energy(spec, raw, engine=engine)
            energy_data = energy.to_dict()
            # Valid thermal output is reusable even when delivery is incomplete.
            if raw.diagnostics.get("accepted", True):
                cache.put("energy", key, energy_data)
        else:
            # A reused calculation retains its arrays; copy available artifacts
            # into this evaluation rather than exposing paths owned by another run.
            from .cache import materialize_artifacts
            from .results import EnergyResult

            energy_data = materialize_artifacts(energy_data, output / "energy")
            energy = EnergyResult.from_dict(energy_data)
        path_id = identity(flows)
        lca_key = identity(
            dict(
                format=1,
                quantities=quantities.to_dict(),
                flows=flows,
                energy=key,
                settings=settings,
                baseline=self._baseline_inventory,
                requirements=getattr(self, "material_history_requirements", ()),
                implementation=implementation_identity("epsm_lca"),
            )
        )
        lca_data = cache.get("lca", lca_key)
        reused_lca = lca_data is not None
        logger.debug(
            "LCA cache %s",
            "hit" if reused_lca else "miss",
            extra={
                "epsm_event": "evaluation.lca.cache",
                "epsm_details": {"reused": reused_lca, "lca_id": lca_key},
            },
        )
        if lca_data is None:
            try:
                lca = call_with_context(
                    assess,
                    quantities,
                    flows,
                    energy,
                    settings,
                    baseline_quantities=self._baseline_inventory,
                    requirements=getattr(self, "material_history_requirements", ()),
                )
            except Exception as error:
                logger.exception(
                    "LCA calculation failed; energy result retained",
                    extra={
                        "epsm_event": "evaluation.lca.failed",
                        "epsm_context": {
                            "evaluation_id": evaluation_id,
                            "lca_id": lca_key,
                        },
                        "epsm_details": {"energy_retained": True},
                    },
                )
                lca = LCAResult(
                    "failed", None, None, None, (f"{type(error).__name__}: {error}",)
                )
            lca_data = lca.to_dict()
            if lca.complete:
                cache.put("lca", lca_key, lca_data)
        result = Evaluation(
            id=evaluation_id,
            state_id=snapshot.sha256,
            path_id=path_id,
            engine=engine,
            energy_id=key,
            lca_id=lca_key,
            snapshot=snapshot.to_dict(),
            source_record=deepcopy(self._source_record),
            archetype_applications=application_records,
            weather=frozen_weather.to_dict(),
            assessment=settings,
            energy=energy_data,
            lca=lca_data,
            quantities=quantities.to_dict(),
            material_flows=flows,
            diagnostics=dict(
                energy_reused=reused_energy,
                lca_reused=reused_lca,
                energy_boundary=energy.boundary,
                lca_status=lca_data["status"],
                lca_requirements=lca_data["requirements"],
            ),
        )
        self.results._append(result)
        # Energy and in-memory result already exist if artifact persistence fails.
        (output / "evaluation.json").write_text(encode(result.to_dict()))
        logger.info(
            "Saved evaluation",
            extra={
                "epsm_event": "evaluation.saved",
                "epsm_details": {"path": str(output / "evaluation.json")},
            },
        )
        return result
