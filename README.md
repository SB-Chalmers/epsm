# EPSM

The researcher interface to the EPSM building platform. `epsm.Building` extends
the physical implementation in `epsm_core`; shared constructions come from
`epsm_data`. One object can be authored gradually, quantified, renovated,
simulated and assessed.

```python
from epsm import Building, Weather

building = Building()  # Named illustrative reference preset, not a measured building.
weather = Weather.from_epw("weather.epw")
print(building.quantities().by_material())
result = building.simulate(engine="epsm_rc", weather=weather)
print(result.energy.scalars)
print(result.lca.status, result.lca.requirements)
print(building.results.latest)
```

Use `Building.empty()` or `Building.from_footprint(...)` for gradual authoring.
`Building.from_record(record)` copies portable evidence; missing geometry inputs
remain unresolved. Assign a catalogue construction set explicitly, or provide
one to the factory. A copied assignment cannot change the catalogue.

## Install

Python 3.11+. Install compatible local packages in dependency order: `epsm_data`,
`epsm_core`, `epsm_lca`, `epsm`, then the optional `epsm_rc`, `epsm_db` and
`epsm_workflows`. The development repositories are private and therefore need
authenticated access; these versions are not claimed to be published on PyPI.
For a local checkout, `python -m pip install -e ../epsm_data -e ../epsm_core
-e ../epsm_lca -e ../epsm_rc -e .` installs the platform with RC.
EnergyPlus requires a separately installed supported binary.

### One shared local development environment

With the EPSM repositories checked out as siblings under `~/GitHub`, run this
once from `epsm`:

```sh
python3.12 scripts/setup_shared_venv.py
```

The script installs all local Python libraries from `requirements-local.txt` in
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

## Results and assessment

`building.results` is always a collection. Each evaluation stores fixed physical
inputs, weather content identity and a retained EPW, quantities, intervention
history, settings, engine outputs and LCA. Edits preserve old results;
`building.results.for_current_state(building)` filters matching inputs.
`result.energy` distinguishes thermal demand from delivered carrier energy.
The first common delivery boundary is **space heating and ventilation fans**.
DHW and cooling remain separate demand outputs; whole-building operational LCA
is incomplete until its delivery boundary is explicitly supported.

Attach `AssessmentSettings` to `building.assessment`. Missing settings/factors
produce an incomplete LCA; assessment failures preserve successful energy.
`EvaluationCache(directory)` stores energy and LCA independently. Factor updates
reuse energy, while every call adds a distinct combined evaluation.

`building.renovate(*measures)` applies one transactional bundle to a new child.
The child inherits settings, retains its path and starts with empty results.
`to_dict()`/`from_dict()` preserve the physical state, evidence, settings and
renovation lineage without carrying a database connection.

Run the installed [platform walkthrough](examples/platform_walkthrough.py):

```sh
python examples/platform_walkthrough.py --weather /absolute/path/weather.epw
python -m pytest tests
```

The example's factors are synthetic teaching inputs. Replace them with sourced
data before drawing research conclusions. Solver limitations are reported by
the selected engine. The previous DB and Data adapters remain accessible through
compatibility modules while existing studies migrate. Studio is outside this
refactor. EPSM-owned code uses MIT; see LICENSE.

### Generated weather and evidence

For SMHI actual-year weather, `Weather.from_epw(epw_path, provenance_path=receipt_path)` infers the explicit AMY year and retains the fingerprinted quality receipt. Undated typical-year files use the documented 2023 calendar unless you supply `calendar_year`. Each evaluation copies its EPW and retains that receipt alongside its fixed Building state.
