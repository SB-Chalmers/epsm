"""Public calculation identities shared by interactive and resumed evaluations."""

import importlib.metadata
import importlib.util
import platform
from functools import lru_cache
from pathlib import Path

from epsm_core import Weather
from epsm_core.weather import file_sha256

from .results import identity


@lru_cache(maxsize=None)
def implementation_identity(package: str) -> str:
    """Fingerprint executable package sources loaded in this process."""
    spec = importlib.util.find_spec(package)
    if spec is None:
        raise ImportError(f"Install {package} to use this calculation")
    root = Path(spec.origin).parent
    return identity(
        {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}
    )


def evaluation_identity(*, engine: str, weather, **options) -> dict:
    """Inspect fixed weather, runtime and calculation options without running energy.

    This identity is for resuming the built-in EPSM evaluator. Physical state,
    renovation path and assessment settings are added by the caller. Weather
    paths are excluded; file contents and calendar settings are included.
    EnergyPlus identity requires the selected executable and schema to be
    available, just as an energy calculation does. Custom remote evaluators must
    supply their own explicitly versioned identity when those are unavailable.
    """
    if engine not in {"energyplus", "epsm_rc"}:
        raise ValueError("engine must be 'energyplus' or 'epsm_rc'")
    weather = weather if isinstance(weather, Weather) else Weather.from_epw(weather)
    if file_sha256(weather.path) != weather.sha256:
        raise ValueError(
            "Weather changed after inspection; create a new Weather object"
        )
    climate = weather.to_dict()
    climate.pop("epw_path")
    versions = {"python": platform.python_version()}
    for name in ("numpy", "pandas", "pvlib", "pydantic", "shapely"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    external = None
    if engine == "energyplus":
        from epsm_core.compiler import EnergyPlusCompiler

        compiler = EnergyPlusCompiler(
            options.get("energyplus"), settings=options.get("settings")
        )
        external = dict(
            executable=compiler.engine_hash,
            schema=compiler.schema_hash,
            version=compiler.version,
            settings=compiler.settings.model_dump(mode="json"),
        )
    energy = dict(
        engine=engine,
        external=external,
        versions=versions,
        options=options,
        implementations={
            name: implementation_identity(name)
            for name in {
                "epsm",
                "epsm_core",
                "epsm_data",
                "epsm_rc" if engine == "epsm_rc" else "epsm_core",
            }
        },
    )
    return dict(
        format=1,
        weather=climate,
        energy=energy,
        assessment=implementation_identity("epsm_lca"),
    )
