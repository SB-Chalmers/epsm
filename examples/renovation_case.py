# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Shared teaching inputs, with Data constructions and Boverket material factors.

Building inputs, heating efficiency, fan power, removal factors and carrier
climate factors are assumptions. They are not measured building evidence.
"""

from epsm_core import HVACSystem
from epsm_core.specs import DeliverySpec, HeatingDeliverySpec
from epsm_data import Catalogue, ConstructionOperation, RenovationMeasure
from epsm_data.domain import BuildingElement as Role

from epsm import AssessmentSettings, Building, EnvironmentalFactor


def make_case():
    """Create the same window and wall work as one step and as two steps."""
    catalogue = Catalogue.load()
    existing = catalogue.for_year("multi_family", 1960, state="existing")
    advanced = catalogue.for_year(
        "multi_family", 1960, state="advanced"
    ).construction_set
    baseline = Building(
        preset="illustrative-reference",
        identifier="epsm-renovation-example",
    )
    # This teaching case selects fabric while retaining its explicitly named
    # preset operation/system/envelope assumptions. Full catalogue selections
    # expose those independent sections for an actual building study.
    baseline.apply_archetype(
        existing.with_changes(operating_profile=None, envelope_performance=None)
    )
    baseline.hvac = HVACSystem(
        baseline.hvac.airflow,
        DeliverySpec(
            heating=HeatingDeliverySpec(
                carrier="district_heat",
                efficiency=0.95,
                specific_fan_power_w_per_l_s=1.5,
                source="ASSUMED teaching delivery: district heat efficiency 0.95, fan power 1.5 W/(L/s)",
            )
        ),
    )
    windows = RenovationMeasure(
        "advanced-windows",
        "envelope",
        "Replace windows",
        "Data Advanced window product",
        "window",
        operations=(
            ConstructionOperation(
                "replace_element", Role.WINDOW, element=advanced.elements[Role.WINDOW]
            ),
        ),
    )
    insulation = RenovationMeasure(
        "wall-insulation",
        "envelope",
        "Insulate walls",
        "Data Advanced outer insulation",
        "wall",
        operations=(
            ConstructionOperation(
                "add_component",
                Role.EXT_WALL,
                component=advanced.elements[Role.EXT_WALL].components[0],
                position=0,
            ),
        ),
    )
    single = baseline.renovate(windows, insulation)
    step_1 = baseline.renovate(windows)
    step_2 = step_1.renovate(insulation)
    removal = {
        row.material_id: {
            module: EnvironmentalFactor(
                0.5,
                "m2",
                module,
                "ASSUMED window removal: 0.5 kg CO2e/m2 for each removal stage; not Boverket data",
            )
            for module in ("C1", "C2", "C3", "C4")
        }
        for row in step_1.material_flows[0].removed
    }
    settings = AssessmentSettings.from_building(
        step_2,
        period_years=30,
        catalogue=catalogue,
        material_factors=removal,
        carrier_factors={
            "district_heat": EnvironmentalFactor(
                0.05, "kWh", "B6", "ASSUMED teaching heat factor; not Boverket data"
            ),
            "electricity": EnvironmentalFactor(
                0.1,
                "kWh",
                "B6",
                "ASSUMED teaching electricity factor; not Boverket data",
            ),
        },
    )
    for building in (baseline, single, step_1, step_2):
        building.assessment = settings
    return dict(
        baseline=baseline,
        single_step=single,
        step_1=step_1,
        step_2=step_2,
        settings=settings,
        catalogue=catalogue,
        measures=(windows, insulation),
    )


def rc_settings():
    """Explicitly select unlimited sensible airflow and a ground approximation."""
    from epsm_rc import RCSettings

    return RCSettings.from_policy(
        "epsm_rc_5r1c_v1",
        airflow_policy="sensible_only_unlimited_supply",
        ground_policy="conductance_multiplier",
    )
