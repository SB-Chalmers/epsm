"""Public researcher interface over the single physical Core Building."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import importlib.util
from pathlib import Path
import shutil
import uuid

from epsm_core import Building as CoreBuilding, BuildingSnapshot, Weather
from epsm_lca import AssessmentSettings, LCAResult, assess

from .cache import EvaluationCache
from .energy import normalize_energy
from .results import Evaluation, Results, encode, identity


@lru_cache(maxsize=None)
def _implementation(package):
    """Pin executable source, including uncommitted development changes."""
    spec = importlib.util.find_spec(package)
    if spec is None:
        raise ImportError(f"Install {package} to use this engine")
    root = Path(spec.origin).parent
    return identity({str(p.relative_to(root)): p.read_text()
                     for p in sorted(root.rglob("*.py"))})


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
        self.results = Results()
        self._baseline_inventory = None
        self._source_record = None

    def _copy_runtime_configuration_to(self, child):
        child.assessment = deepcopy(self.assessment)
        child._source_record = deepcopy(self._source_record)
        child._baseline_inventory = deepcopy(
            self._baseline_inventory if self._baseline_inventory is not None
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
        return dict(format="epsm-building-1", building=self.snapshot().to_dict(),
                    assessment=self.assessment.to_dict() if self.assessment else None,
                    baseline_inventory=deepcopy(self._baseline_inventory),
                    source_record=deepcopy(self._source_record), lineage=self.lineage_to_dict())

    @classmethod
    def from_dict(cls, data):
        if data.get("format") != "epsm-building-1":
            return CoreBuilding.from_dict.__func__(cls, data)
        building = BuildingSnapshot.from_dict(data["building"]).to_building(building_type=cls)
        building.assessment = AssessmentSettings.from_dict(data["assessment"]) if data["assessment"] else None
        building._baseline_inventory = deepcopy(data.get("baseline_inventory"))
        building._source_record = deepcopy(data.get("source_record"))
        building.restore_lineage(data.get("lineage", {}))
        return building

    def simulate(self, *, engine="energyplus", weather, directory=None, cache=None, **options):
        """Freeze inputs, calculate energy, assess LCA and append one evaluation.

        An incomplete or failed LCA leaves energy accessible. Cache entries hold
        separate energy/LCA calculations, so changing factors reuses energy.
        Each call still appends a distinct evaluation. Artifacts are retained in
        the supplied directory, or ``outputs/epsm/<evaluation-id>``.
        """
        if engine not in {"energyplus", "epsm_rc"}:
            raise ValueError("engine must be 'energyplus' or 'epsm_rc'")
        if not isinstance(weather, Weather):
            weather = Weather.from_epw(weather)
        snapshot = self.snapshot()
        frozen = snapshot.to_building()
        settings = AssessmentSettings.from_dict(self.assessment.to_dict()) if self.assessment else None
        evaluation_id = uuid.uuid4().hex
        output = Path(directory or Path("outputs") / "epsm" / evaluation_id).resolve()
        output.mkdir(parents=True, exist_ok=True)
        from epsm_core.weather import file_sha256
        if file_sha256(weather.path) != weather.sha256:
            raise ValueError("Weather changed after it was inspected; create a new Weather object")
        weather_path = output / "weather.epw"
        if Path(weather.path).resolve() != weather_path:
            shutil.copyfile(weather.path, weather_path)
        frozen_weather = Weather.from_epw(weather_path, calendar_year=weather.climate.calendar_year)
        spec = frozen.to_spec(frozen_weather)
        quantities = frozen.quantities()
        flows = deepcopy(self.material_flows)
        cache = cache if cache is not None else EvaluationCache()
        key = identity(dict(format=1, physical=spec.physical_dict(), engine=engine,
                            implementation=_implementation("epsm_core" if engine == "energyplus" else "epsm_rc"),
                            normalization=_implementation("epsm"), options=options))
        energy_data = cache.get("energy", key)
        reused_energy = energy_data is not None
        if energy_data is None:
            if engine == "energyplus":
                from epsm_core import run_building
                raw = run_building(frozen, weather=frozen_weather, directory=output / "energy", **options)
            else:
                from epsm_rc import simulate_building
                raw = simulate_building(frozen, weather=frozen_weather, directory=output / "energy", **options)
            energy = normalize_energy(spec, raw, engine=engine)
            energy_data = energy.to_dict()
            # Valid thermal output is reusable even when delivery is incomplete.
            if raw.diagnostics.get("accepted", True):
                cache.put("energy", key, energy_data)
        else:
            from .results import EnergyResult
            energy = EnergyResult.from_dict(energy_data)
        path_id = identity(flows)
        lca_key = identity(dict(format=1, quantities=quantities.to_dict(), flows=flows,
                                energy=key, settings=settings, baseline=self._baseline_inventory,
                                implementation=_implementation("epsm_lca")))
        lca_data = cache.get("lca", lca_key)
        reused_lca = lca_data is not None
        if lca_data is None:
            try:
                lca = assess(quantities, flows, energy, settings,
                             baseline_quantities=self._baseline_inventory)
            except Exception as error:
                lca = LCAResult("failed", None, None, None,
                                (f"{type(error).__name__}: {error}",))
            lca_data = lca.to_dict()
            if lca.complete:
                cache.put("lca", lca_key, lca_data)
        result = Evaluation(id=evaluation_id, state_id=snapshot.sha256, path_id=path_id,
                            engine=engine, energy_id=key, lca_id=lca_key,
                            snapshot=snapshot.to_dict(), weather=frozen_weather.to_dict(),
                            assessment=settings, energy=energy_data, lca=lca_data,
                            quantities=quantities.to_dict(), material_flows=flows,
                            diagnostics=dict(energy_reused=reused_energy, lca_reused=reused_lca,
                                             energy_boundary=energy.boundary))
        self.results._append(result)
        # Energy and in-memory result already exist if artifact persistence fails.
        (output / "evaluation.json").write_text(encode(result.to_dict()))
        return result
