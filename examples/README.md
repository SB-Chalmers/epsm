# EPSM examples

Use these in order with the coordinated package versions listed in the main
[README](../README.md#tested-package-combination). Each notebook starts with fresh
variables and imports installed packages. No database or live service is needed.

| Example | What it shows | Energy engine |
| --- | --- | --- |
| [0. Geometry and archetype](00_geometry_and_archetype.ipynb) | Apply catalogue and authored definitions to explicit geometry; inspect assignments and missing inputs | None |
| [1. Building and Data](01_building_and_data.ipynb) | An empty draft, a chosen teaching building, Data constructions, quantities, sources and a partial source record | None |
| [2. Renovation materials](02_renovation_materials.ipynb) | Single and staged work, added and removed quantities, missing factors, saved reports and plots | None |
| [3. Actual energy and climate](03_actual_energy_and_climate.ipynb) | Baseline and renovated annual RC runs, operational impact, savings and matching single/staged final totals | RC |

Install the coordinated private packages first, then this checkout:

```sh
python -m pip install '.[rc,examples,workflows]'
python scripts/run_examples.py --integration
```

The [shared input file](renovation_case.py) declares a 20 × 12 m teaching building
with three storeys. Its geometry, use, heating efficiency and fan power are
assumptions. Data supplies Existing and Advanced multi-family constructions and
Boverket material factors. Heating and electricity climate factors, and removed
window treatment factors, are explicitly labelled teaching assumptions.
A5.1 covers installation waste; it is not complete A5 installation impact.

The same code is available as a [command-line walkthrough](platform_walkthrough.py):

```sh
python examples/platform_walkthrough.py --output outputs/renovation
python examples/platform_walkthrough.py --optimise --output outputs/search
python examples/platform_walkthrough.py --weather /absolute/path/weather.epw
python examples/platform_walkthrough.py --engine energyplus \
    --energyplus-exe /absolute/path/energyplus --weather /absolute/path/weather.epw
```

Without `--weather`, the walkthrough explicitly chooses RC's bundled Gothenburg
example weather, including when comparing EnergyPlus. This choice requires RC
to be installed. EnergyPlus itself must be installed separately.
`--optimise` adds a small Workflows search; it requires the Workflows extra.

Every call creates a new run folder. It retains engine outputs, fixed evaluations,
both full renovation reports, readable CSV tables and an energy summary with
the actual modelling settings. The notebooks also show optional Matplotlib
figures. LCA receives annual purchased energy from each saved evaluation and
does not launch an engine itself.

RC explicitly omits latent recovery and supply-temperature limits in these
examples, and approximates ground heat transfer with a conductance multiplier.
The default rejection of unsupported shading remains active for this simple
rectangular building. Results describe these chosen assumptions, not measured
building accuracy. Recalculate old teaching outputs after updating Core or RC;
changed airflow, gain and ground handling can change annual energy.

## Recorded run with the updated packages

The [15 October 2026 result snapshot](results/current-package-results.json)
records the exact package commits, wheel identity, assumptions and annual
carrier amounts from actual RC and EnergyPlus 24.2 runs:

| Engine | Baseline purchased energy (kWh/year) | After windows and insulation (kWh/year) | Climate savings over 30 years (kg CO₂e) |
| --- | ---: | ---: | ---: |
| RC | 97,518 | 36,506 | 65,335 |
| EnergyPlus | 82,250 | 31,943 | 49,278 |

Both methods count 26,183 kg CO₂e of renovation materials in the final state.
Single-step and staged final totals agree within each engine. Their different
energy answers reflect their declared models; this is not an accuracy ranking.

## Logging

`05_logging.ipynb` teaches explicit output controls and the offline DB-record → Building → RC → LCA trace. Install the coordinated logging package revisions plus the examples extra. `logging_walkthrough.py` uses synthetic evidence and packaged teaching weather; `logging_workers.py` demonstrates one application-owned queue listener. These examples need no live database, provider network or EnergyPlus. Run each notebook from a fresh kernel in this directory.
