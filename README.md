# EPSM

EPSM connects a physical Core building, Data constructions, an energy engine and
LCA. It keeps the building state, calculation choices, energy and climate results
for each evaluation.

```python
from epsm import Building, Weather
from epsm_rc import RCSettings

building = Building(preset="illustrative-reference")
weather = Weather.from_epw("weather.epw")
rc = RCSettings.from_policy(
    "epsm_rc_5r1c_v1",
    airflow_policy="sensible_only_unlimited_supply",
    ground_policy="conductance_multiplier",
)
result = building.simulate(engine="epsm_rc", weather=weather, settings=rc)
print(result.energy.delivered_by_carrier)
print(result.lca.status, result.lca.requirements)
```

This selects a teaching building. Replace its assumed inputs before a study.
`Building()` starts empty with the current Core version. `Building.from_record`
copies source evidence and leaves missing information unresolved. Portable DB
records are retained in `building.to_dict()["source_record"]["portable_record"]`,
including component heights, certificate subjects and quality findings, without
retrieval credentials. Older saved Buildings with summary-only evidence remain
readable; they do not acquire missing evidence on load. Data
constructions, services, operation, ground choices, thermal bridge uplift and
load reference area must be supplied or explicitly selected through a preset.

RC modelling settings are separate from climate assessment settings. In this
example RC omits latent recovery and supply-temperature limits, and approximates
ground transfer with a conductance multiplier. It reports these choices in
`result.energy.diagnostics`. Unsupported features remain errors unless an
explicitly supported approximation is selected. EnergyPlus has its own settings
and requires a supported executable installed separately.

## Install and examples

Python 3.11+. The coordinated packages live in private repositories; install
their tested wheels first if they are not available from your package index.
Then install EPSM with the extras needed for your work:

```sh
python -m pip install '.[rc,examples,workflows]'
python -m pytest tests
python scripts/run_examples.py --integration
python examples/platform_walkthrough.py --optimise
```

Start with the [indexed worked notebooks](examples/README.md). They cover the
building and Data, material quantities and renovation history, then actual
annual RC energy and complete renovation climate reports. The command-line
walkthrough also supports EnergyPlus and optional Workflows optimisation.
Database access is optional and is not needed by these examples.

## One shared local development environment

With the EPSM repositories checked out as siblings under `~/GitHub`, run this
once from `epsm`:

```sh
python3.12 scripts/setup_shared_venv.py
```

The script installs all local Python libraries and the updated example tools from `requirements-local.txt` in
`epsm/.venv`, checks their editable source paths and dependencies, then moves
the old `.venv` directories out of the way. It verifies each replacement link
before deleting its old directory. Core, Data, DB, Development, RC, LCA,
Studies, Workflows, and `smhi2epw` then share the same interpreter. Studio
keeps its own backend environment. Re-running the script updates the shared
packages and checks existing links; `python3.12 scripts/setup_shared_venv.py
--verify-only` checks the current installation without changing it.

Use `~/GitHub/epsm/.venv/bin/python` as the Python interpreter in your editor,
or use a repository's linked `.venv/bin/python` when running its tests. For
example, from `epsm_core` run `.venv/bin/python -m pytest tests/core`. The
shared environment must stay in `epsm/.venv`, and changing package metadata
requires re-running the setup script. Python source changes are available
immediately through the editable installs. The script needs write access to
each sibling checkout to migrate its old `.venv`.

For a package-index installation, plain `pip install epsm` retains only the
base Core, Data, and LCA dependencies. `pip install 'epsm[all]'` also requests
RC, DB, Workflows, Studies, and `smhi2epw`; private distributions must be
available through a configured package index. Neither command looks for local
sibling checkouts.

## Renovation climate reports

`building.assessment = AssessmentSettings(...)` controls the automatic LCA after
an energy run. `result.lca` remains the existing single-state result: cumulative
material work through that state plus that state's operational impact. Missing
factors produce an incomplete result. A failed assessment preserves successful
energy.

Use `assess_renovation` for the baseline and every recorded step. One renovate
call groups changes together; successive calls create successive steps:

```python
from epsm import assess_renovation

# The worked notebooks define the building, measures and sourced factors.
step_1 = baseline.renovate(windows)
step_2 = step_1.renovate(wall_insulation)

# Run each state with the same weather and explicit engine settings.
base_run = baseline.simulate(engine="epsm_rc", weather=weather, settings=rc)
first_run = step_1.simulate(engine="epsm_rc", weather=weather, settings=rc)
final_run = step_2.simulate(engine="epsm_rc", weather=weather, settings=rc)

report = assess_renovation(step_2, assessment_settings, energy={
    0: base_run.annual_energy(),
    1: first_run.annual_energy(),
    2: final_run.annual_energy(),
})
print(report.table())
print(report.quantities(action="removed", by_material=True))
```

The snippet shows the call sequence; the notebooks supply every input.
`annual_energy()` uses the evaluation's saved state and names its source. It
refuses incomplete or non-annual energy. It never simulates or attaches old
energy to a later edited building. `AnnualEnergy.for_building(...)` is also
available for your supplied measured or assumed annual carrier values.

Each report row uses the same assessment period. It shows material impact this
step, material impact so far, this state's operational impact, total climate
impact and savings against the baseline. Energy from different states is never
added together. Existing materials are retained by default. Added and removed
quantities remain inspectable even when their climate factors are missing.

The report provides `table()`, `summary()`, JSON `save()`/`load()` and an optional
Matplotlib `plot()`. Files retain the quantities, factors and sources used in the
calculation. Saving refuses an existing file unless replacement is explicit.
Future replacements, final demolition, dated operating periods and environmental
impacts other than climate remain outside this assessment.

## Retained results and energy reuse

`building.results` is always a collection. Each evaluation retains fixed
physical inputs, weather identity and an EPW copy, quantities, renovation history,
energy choices, outputs and LCA. Edits preserve old results;
`building.results.for_current_state(building)` selects matching physical states.
A renovated child starts with empty results and inherits assessment settings.
`to_dict()`/`from_dict()` preserve the building, settings, evidence and path.

The common purchased-energy coverage is **space heating and ventilation fans**.
Thermal heating demand is kept separate from purchased carrier energy. DHW,
cooling and plug loads are not silently included. Whole-building energy LCA
therefore remains incomplete until its requested coverage is supported.

`EvaluationCache(directory)` stores energy and LCA separately. Factor or period
updates reuse energy; changed physical inputs or RC choices do not. Each call
still creates a separate combined evaluation and retains its own files. EPSM
uses the packages' public APIs and configures no logging handlers; an application
can choose its own logging output.

For generated SMHI actual-year weather,
`Weather.from_epw(epw_path, provenance_path=receipt_path)` keeps the quality
receipt and explicit year. Typical-year files use the documented 2023 calendar
unless `calendar_year` is supplied. Each evaluation retains that weather evidence.

## Tested package combination

The examples and CI use these fixed source versions, checked on 15 October 2026.
EPSM 0.2.0 requires Core and RC 0.3.0+ so the explicit-authoring and reduction
APIs are distinguishable from earlier implementations. Exact commits still
identify the tested source combination; the manifest is the executable CI input.

| Package | Version | Tested commit |
| --- | --- | --- |
| Data | 0.5.0 | `8484c1039e3fdca9e3f174a1880630f0eb02c8c1` |
| Core | 0.3.0 | `ad2e031c180462678abe8c3edc783feb112e0849` |
| RC | 0.3.0 | `026d9fc93ad8c07913ecb56e20b57288b45dc318` |
| LCA | 0.2.0 | `834660ab649594230e29cd320ba66beec0352ddd` |
| Database | 0.2.0 | `9abe1d7e38475d824c2d52c5001b154baf23fa1a` |
| Studies | 0.1.0 | `8abbcea3bd2c204e9e34e903ed03f3d10f0de708` |
| smhi2epw | 1.1.1 | `434d7b26de1a6da88e156bebc39e246c615c4ba0` |
| EPSM | 0.2.0 | `self` |

Core's explicit presets, ground inputs, thermal bridge choices, load reference
area and heat-gain choices survive EPSM snapshots and round trips. RC requires
explicit settings, and its corrected ventilation recovery can change previous
energy outputs. EPSM includes implementation and numerical dependency identities
in its energy cache keys. LCA 0.2.0 keeps the old automatic assessment interface,
while EPSM now exposes its full renovation report too. Recalculate earlier
teaching results after a package update; previous outputs do not establish that
the new combination works.

The supported package combination is recorded in [compatibility.json](compatibility.json).
CI builds and installs every wheel, records exact tested revisions, and checks
the platform suite, public handoffs, EPSM notebooks and the LCA annual renovation
notebook in fresh kernels on Python 3.11
and 3.13. Separate pinned and development jobs distinguish reproducible support
from integration against current development. Required collaborators fail
explicitly when unavailable; Workflows and Studio are outside this matrix. Optional
EnergyPlus checks need a separately installed binary. The compatibility modules
for older DB and Data adapters remain available during migration. EPSM-owned
code uses MIT; see [LICENSE](LICENSE).

To run the required offline cross-package handoff locally, use
`python scripts/check_installed_platform.py --directory build/installed-handoff`.
Add `--require-wheels` in a clean wheel environment. The check uses synthetic DB
evidence, retains shared-certificate scope and runs actual annual RC energy and
renovation LCA. It performs no live database query or provider acquisition.

## Migrating to EPSM 0.2.0

Install the coordinated Core/RC versions and refresh editable metadata after
changing source versions. Saved Buildings retain complete portable DB evidence
alongside their comparison summaries; old summary-only files remain readable.
Database 0.2.0 stock-cell conversion returns the same physical Building type as
individual records, with the old weather/policy route explicitly named legacy.

## Operation logging

Library calls use Python's standard `logging` module and install no console or
file output. Instrumented operations accept optional keyword-only `log_context`
with small identifier mappings; nested events carry operation and parent IDs.
INFO describes major stages; DEBUG exposes selections, conversions and caches.
Logging context does not change physical models or scientific cache inputs.

For an application using EPSM's coordinated logging setup:

```python
from epsm import configure_logging, reset_logging

configure_logging(directory="outputs/example")  # INFO stderr, DEBUG JSONL
# Run operations here.
configure_logging(enabled=False)  # Stop console and file logging.
reset_logging()  # Restore the host application's settings.
```

EPSM is needed only for this combined configuration, not for ordinary library
logging. Existing scripts can keep using `logging.basicConfig(level=logging.INFO)`.

See [the logging notebook](examples/05_logging.ipynb), [handoff example](examples/logging_walkthrough.py) and [worker queue example](examples/logging_workers.py).


## Coordinated logging release

The logging release is tested with the versions and exact source commits in
`logging-compatibility.json`: Data 0.5.0, Core 0.3.0, RC 0.4.0, LCA 0.2.0,
Database 0.2.0, Weather 1.2.0 and Studies 0.2.0. The older compatibility
baseline above remains supported; full cross-package logging requires the
instrumented releases. See [release notes](RELEASE_NOTES.md).

See [archetype application](docs/archetype-application.md) and the [geometry-first example](examples/00_geometry_and_archetype.ipynb) for catalogue and custom authoring on an existing Building.

See [archetypes and building evidence](docs/archetype-consumers.md) for record assembly, independent component selection and maintained stock handovers.

See [installed archetype acceptance](docs/archetype-installed-checks.md) for authored and catalogue application checks with actual RC and EnergyPlus execution.
