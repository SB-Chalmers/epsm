"""Sveby solar-shading factor choice shared by the record and archetype routes.

Sveby gives two window solar factors. ``behaviour`` is the occupant part (blinds and
curtains, 0.71 for single-family houses and offices, 0.65 for schools). ``total`` also
covers fixed obstructions (0.50 for houses and offices; Sveby gives schools one factor,
so school stays 0.65). Multi-family is not applied: named choices give 1.0 there. Use ``behaviour`` when obstructions are modelled as geometry and
``total`` when they are not. ``None`` turns the factor off (1.0), as in EPSM runs
before policy version 6. A number in (0, 1] is used as given.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

SOLAR_SHADING_CHOICES = ("behaviour", "total")
DEFAULT_SOLAR_SHADING = "behaviour"

# Building types for which the named Sveby factors resolve to 1.0 (off). An explicit
# number still applies. Multi-family: not applied after the final calibration campaign
# (2026-11-24), where 0.71 lowered the multi-family match; 1.0 is the value the earlier
# validation used and is untested on fresh buildings.
NOT_APPLIED = {
    "multi_family": (
        "Sveby solar shading not applied for multi-family (factor 1.0) after the "
        "final calibration campaign; untested at 1.0 on fresh buildings"
    ),
}


def validate_solar_shading(choice):
    """Return a valid choice or raise ``ValueError``."""
    if choice is None or choice in SOLAR_SHADING_CHOICES:
        return choice
    if isinstance(choice, bool) or not isinstance(choice, (int, float)):
        raise ValueError(
            "solar_shading must be 'behaviour', 'total', None or a number in (0, 1]"
        )
    if not math.isfinite(choice) or not 0 < choice <= 1:
        raise ValueError("solar_shading factor must be in (0, 1]")
    return float(choice)


def sveby_shading_factors(values):
    """``{"behaviour": f, "total": f}`` from Data profile values, or None if absent."""
    shading = values.get("solar_shading")
    if isinstance(shading, Mapping) and "occupant_behavior_factor" in shading:
        behaviour = shading["occupant_behavior_factor"]
        return {"behaviour": behaviour, "total": shading.get("total_default_factor", behaviour)}
    completion = values.get("completion_inputs")
    if isinstance(completion, Mapping) and "solar_shading_behavior_factor" in completion:
        behaviour = completion["solar_shading_behavior_factor"]
        return {
            "behaviour": behaviour,
            "total": completion.get("solar_shading_total_factor", behaviour),
        }
    return None


def solar_shading_factor(values, choice, building_type=None):
    """Resolve ``choice`` against profile ``values`` for ``building_type``.

    Returns the factor and a short description, or ``(None, None)`` when the choice is
    a named Sveby factor but the profile carries no Sveby shading data. Named choices
    resolve to 1.0 for the types in ``NOT_APPLIED``.
    """
    choice = validate_solar_shading(choice)
    if choice is None:
        return 1.0, "Sveby solar shading off (factor 1.0)"
    if not isinstance(choice, str):
        return choice, f"Explicit solar shading factor {choice}"
    if building_type in NOT_APPLIED:
        return 1.0, NOT_APPLIED[building_type]
    factors = sveby_shading_factors(values)
    if factors is None:
        return None, None
    factor = factors[choice]
    if choice == "behaviour":
        text = (
            f"Sveby occupant solar shading (blinds, curtains) {factor}; "
            "fixed obstructions are geometry, not part of this factor"
        )
    else:
        text = f"Sveby total solar shading {factor} (occupant behaviour and fixed obstructions)"
    return factor, text
