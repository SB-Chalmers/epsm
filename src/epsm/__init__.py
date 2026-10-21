"""EPSM platform entry point; importing it performs no catalogue or file I/O."""

import logging as _stdlib_logging

from epsm_core import HVACSystem, OperationProfile, Weather
from epsm_data import (
    Archetype,
    Component,
    ConstructionSet,
    Element,
    EnvironmentalFactor,
    Layer,
    Material,
)
from epsm_lca import (
    AnnualEnergy,
    AssessmentSettings,
    RenovationResult,
    StageResult,
    assess_renovation,
)

from .archetypes import ArchetypeApplicationReport
from .building import Building
from .cache import EvaluationCache
from .io import load_bundle_metadata
from .logging import configure_logging, reset_logging
from .provenance import evaluation_identity
from .requirements import (
    output_capabilities,
    output_requirements,
    preflight,
    validate_outputs,
)
from .results import EnergyResult, Evaluation, Results

__version__ = "0.4.0"
__all__ = [
    "configure_logging",
    "reset_logging",
    "evaluation_identity",
    "Building",
    "ArchetypeApplicationReport",
    "Weather",
    "HVACSystem",
    "OperationProfile",
    "AssessmentSettings",
    "AnnualEnergy",
    "RenovationResult",
    "StageResult",
    "assess_renovation",
    "EnvironmentalFactor",
    "Material",
    "Layer",
    "Component",
    "Element",
    "ConstructionSet",
    "Archetype",
    "EvaluationCache",
    "EnergyResult",
    "Evaluation",
    "Results",
    "load_bundle_metadata",
    "output_requirements",
    "output_capabilities",
    "preflight",
    "validate_outputs",
]

# A library emits no output until its host selects handlers.

_stdlib_logging.getLogger("epsm").addHandler(_stdlib_logging.NullHandler())
