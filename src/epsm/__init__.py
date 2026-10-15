"""EPSM platform entry point; importing it performs no catalogue or file I/O."""

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

from .building import Building
from .cache import EvaluationCache
from .provenance import evaluation_identity
from .results import EnergyResult, Evaluation, Results

__version__ = "0.1.0"
__all__ = [
    "evaluation_identity",
    "Building",
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
]
