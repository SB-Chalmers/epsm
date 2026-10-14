"""Run the installed platform from portable record to renovation optimisation.

Uses illustrative constructions and deliberately synthetic factors, unsuitable
for research conclusions. Supply an EPW with --weather; otherwise the RC package's
bundled Gothenburg weather is used. Writes outputs only below --output.
"""

import argparse
from importlib.resources import files
from pathlib import Path

from epsm_core import HVACSystem
from epsm_core.specs import DeliverySpec, HeatingDeliverySpec
from epsm_data import ConstructionOperation, RenovationCatalogue, RenovationMeasure
from epsm_data.domain import BuildingElement as Role
from epsm_workflows import optimise_renovations

from epsm import (
    AssessmentSettings,
    Building,
    EnvironmentalFactor,
    EvaluationCache,
    Weather,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/platform_walkthrough")
    )
    args = parser.parse_args()
    reference = Building()
    record = dict(
        building_id="illustrative",
        dataset_id="example",
        facts={"storey_height_m": 2.8},
        storeys=3,
        atemp_m2=720,
        geometry={
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 12], [0, 12], [0, 0]]],
        },
    )
    building = Building.from_record(
        record,
        construction_set=reference.construction_set,
        hvac=reference.hvac,
        operation=reference.operation,
        facade=reference.facade,
    )
    building.hvac = HVACSystem(
        building.hvac.airflow,
        DeliverySpec(
            heating=HeatingDeliverySpec(
                carrier="district_heat",
                efficiency=0.95,
                specific_fan_power_w_per_l_s=1.5,
                source="Illustrative example assumptions",
            )
        ),
    )
    print("Evidence comparison:", building.compare())
    print("Material inventory:", building.quantities().by_material())
    window = building.construction_set.elements[Role.WINDOW]
    measure = RenovationMeasure(
        "replace-window",
        "envelope",
        "Replace windows",
        "Illustrative like-for-like replacement",
        "window",
        operations=(
            ConstructionOperation("replace_element", Role.WINDOW, element=window),
        ),
    )
    factors = {
        q.material_id: {
            "A1A3": EnvironmentalFactor(
                1,
                "kg"
                if q.mass_kg is not None
                else ("item" if q.count is not None else "m2"),
                "A1A3",
                "SYNTHETIC example factor; replace before research",
            )
        }
        for q in building.quantities()
    }
    building.assessment = AssessmentSettings(
        30,
        "space_heating_and_fans",
        "retained",
        ("A1A3",),
        factors,
        {
            c: EnvironmentalFactor(0.1, "kWh", "B6", "SYNTHETIC example factor")
            for c in ("electricity", "district_heat")
        },
    )
    weather = Weather.from_epw(
        args.weather or files("epsm_rc") / "data/epw/goteborg.epw"
    )
    cache = EvaluationCache(args.output / "cache")
    child = building.renovate(measure)
    result = child.simulate(
        engine="epsm_rc",
        weather=weather,
        cache=cache,
        directory=args.output / "renovated",
    )
    assert result.lca.complete, result.lca.requirements
    assert not building.results and len(child.results) == 1
    print(
        result, result.energy.annual_delivered_energy_kwh, result.lca.total_gwp_kgco2e
    )
    tree = optimise_renovations(
        building,
        catalogue=RenovationCatalogue([measure]),
        max_depth=1,
        budget=2,
        evaluator=lambda candidate: candidate.simulate(
            engine="epsm_rc",
            weather=weather,
            cache=cache,
            directory=args.output / "search" / candidate.snapshot().sha256,
        ),
    )
    print(
        f"Evaluated {len(tree.nodes)} alternatives; Pareto alternatives: {len(tree.pareto)}"
    )


if __name__ == "__main__":
    main()
