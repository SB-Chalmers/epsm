"""EPSM platform entry point; importing it performs no catalogue or file I/O."""

from epsm_core import Weather, HVACSystem, OperationProfile
from epsm_data import EnvironmentalFactor, Material, Layer, Component, Element, ConstructionSet, Archetype
from epsm_lca import AssessmentSettings

from .building import Building
from .cache import EvaluationCache
from .results import EnergyResult, Evaluation, Results

__version__ = "0.1.0"
__all__ = ["Building", "Weather", "HVACSystem", "OperationProfile", "AssessmentSettings",
           "EnvironmentalFactor", "Material", "Layer", "Component", "Element", "ConstructionSet",
           "Archetype", "EvaluationCache", "EnergyResult", "Evaluation", "Results"]
