"""Sveby solar-shading factor choice shared by the record and archetype routes.

Sveby gives two window solar factors. ``behaviour`` is the occupant part (blinds and
curtains, 0.71 for housing and offices, 0.65 for schools). ``total`` also covers
fixed obstructions (0.50 for housing and offices; Sveby gives schools one factor, so
school stays 0.65). Use ``behaviour`` when obstructions are modelled as geometry and
``total`` when they are not. ``None`` turns the factor off (1.0), as in EPSM runs
before policy version 6. A number in (0, 1] is used as given.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

SOLAR_SHADING_CHOICES = ("behaviour", "total")
DEFAULT_SOLAR_SHADING = "behaviour"


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


def solar_shading_factor(values, choice):
    """Resolve ``choice`` against profile ``values``.

    Returns the factor and a short description, or ``(None, None)`` when the choice is
    a named Sveby factor but the profile carries no Sveby shading data.
    """
    choice = validate_solar_shading(choice)
    if choice is None:
        return 1.0, "Sveby solar shading off (factor 1.0)"
    if not isinstance(choice, str):
        return choice, f"Explicit solar shading factor {choice}"
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
