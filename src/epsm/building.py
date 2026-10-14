"""Public researcher interface over the single physical Core Building."""

from __future__ import annotations

import importlib.util
import logging
import shutil
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from epsm_core import Building as CoreBuilding
from epsm_core import BuildingSnapshot, Weather
from epsm_lca import AssessmentSettings, LCAResult, assess

from .cache import EvaluationCache
from .energy import normalize_energy
from .results import Evaluation, Results, encode, identity

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _implementation(package):
    """Pin executable source, including uncommitted development changes."""
    spec = importlib.util.find_spec(package)
    if spec is None:
        raise ImportError(f"Install {package} to use this engine")
    root = Path(spec.origin).parent
    return identity(
        {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}
    )


class Building(CoreBuilding):
    """A Core Building with record, simulation and automatic LCA conveniences.

    ``Building()`` uses Core's inspectable illustrative reference preset. Use
    ``empty()`` for blank authoring. Assessment settings must be explicit before
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

    @property
    def results(self):
        return self._results

    def _copy_runtime_configuration_to(self, child):
        child.assessment = deepcopy(self.assessment)
        child._evaluation_cache = self._evaluation_cache
        child._source_record = deepcopy(self._source_record)
        child._baseline_inventory = deepcopy(
            self._baseline_inventory
            if self._baseline_inventory is not None
            else (self.quantities().to_dict() if self.readiness("quantities") else None)
        )

    @classmethod
    def from_record(cls, record, **options):
        """Copy observed geometry and evidence, retaining unresolved model inputs.

        Swedish DB footprints are projected metric coordinates. Geometry needs
        storeys and height/elevations; missing source heights remain unresolved.
        Catalogue and HVAC selections are explicit options, never measurements.
        """
        from .records import building_from_record

        return building_from_record(cls, record, **options)

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
            source_record=deepcopy(self._source_record),
            lineage=self.lineage_to_dict(),
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
        building.restore_lineage(data.get("lineage", {}))
        return building

    def simulate(
        self, *, engine="energyplus", weather, directory=None, cache=None, **options
    ):
        """Freeze inputs, calculate energy, assess LCA and append one evaluation.

        An incomplete or failed LCA leaves energy accessible. Cache entries hold
        separate energy/LCA calculations, so changing factors reuses energy.
        Each call still appends a distinct evaluation. Artifacts are retained in
        a unique evaluation subdirectory below the supplied directory, or ``outputs/epsm``.
        """
        if engine not in {"energyplus", "epsm_rc"}:
            raise ValueError("engine must be 'energyplus' or 'epsm_rc'")
        if not isinstance(weather, Weather):
            weather = Weather.from_epw(weather)
        self.readiness(engine=engine, weather=weather).require()
        snapshot = self.snapshot()
        frozen = snapshot.to_building()
        settings = (
            AssessmentSettings.from_dict(self.assessment.to_dict())
            if self.assessment
            else None
        )
        evaluation_id = uuid.uuid4().hex
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
            weather_path, calendar_year=weather.climate.calendar_year
        )
        spec = frozen.to_spec(frozen_weather)
        quantities = frozen.quantities()
        flows = deepcopy(self.material_flows)
        cache = cache if cache is not None else self._evaluation_cache
        engine_identity = None
        if engine == "energyplus":
            from epsm_core.compiler import EnergyPlusCompiler

            compiler = EnergyPlusCompiler(
                options.get("energyplus"), settings=options.get("settings")
            )
            engine_identity = dict(
                executable=compiler.engine_hash,
                schema=compiler.schema_hash,
                version=compiler.version,
                settings=compiler.settings.model_dump(mode="json"),
            )
        key = identity(
            dict(
                format=2,
                physical=spec.physical_dict(),
                engine=engine,
                engine_identity=engine_identity,
                core=_implementation("epsm_core"),
                data=_implementation("epsm_data"),
                implementation=_implementation(
                    "epsm_core" if engine == "energyplus" else "epsm_rc"
                ),
                normalization=_implementation("epsm"),
                options=options,
            )
        )
        logger.info(
            "Energy calculation started",
            extra={"engine": engine, "evaluation_id": evaluation_id, "energy_id": key},
        )
        energy_data = cache.get("energy", key)
        reused_energy = energy_data is not None
        if energy_data is None:
            if engine == "energyplus":
                from epsm_core import run_building

                raw = run_building(
                    frozen,
                    weather=frozen_weather,
                    directory=output / "energy",
                    **options,
                )
            else:
                from epsm_rc import simulate_building

                raw = simulate_building(
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
                implementation=_implementation("epsm_lca"),
            )
        )
        lca_data = cache.get("lca", lca_key)
        reused_lca = lca_data is not None
        if lca_data is None:
            try:
                lca = assess(
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
                    extra={"evaluation_id": evaluation_id, "lca_id": lca_key},
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
            "Evaluation completed",
            extra={
                "evaluation_id": evaluation_id,
                "energy_reused": reused_energy,
                "lca_status": lca_data["status"],
            },
        )
        return result
