"""Optional native construction integration checks."""
import math
from epsm_data.nominal import validate_nominal_handover

def validate_native_handover(bundle):
    """Optionally validate/roundtrip with installed Honeybee and core types."""
    from epsm_core.specs.facade import GlazingSpec
    from epsm_core.specs.physics import ConstructionSpec
    from honeybee_energy.construction.dictutil import dict_to_construction

    validate_nominal_handover(bundle)
    for role, record in bundle["honeybee"].items():
        native = dict_to_construction(record)
        reconstructed = dict_to_construction(native.to_dict())
        if native != reconstructed:
            raise ValueError(f"Honeybee roundtrip mismatch: {role}")
        for material, source in zip(native.materials, record["materials"], strict=True):
            fields = (
                ("u_factor", "shgc", "vt")
                if role == "WINDOW"
                else (
                    "thickness",
                    "conductivity",
                    "density",
                    "specific_heat",
                    "thermal_absorptance",
                    "solar_absorptance",
                    "visible_absorptance",
                )
            )
            if any(
                not math.isclose(getattr(material, f), source[f], rel_tol=1e-10) for f in fields
            ):
                raise ValueError(f"Honeybee changed nominal properties: {role}")
        if role == "WINDOW":
            GlazingSpec(**bundle["core"][role])
        else:
            value = ConstructionSpec(**bundle["core"][role])
            if not math.isclose(
                value.u_value_w_m2k, bundle["roles"][role]["nominal_u_w_m2k"], rel_tol=1e-10
            ):
                raise ValueError(f"Core nominal U mismatch: {role}")
            reverse = bundle["reciprocal"][role]
            dict_to_construction(reverse["honeybee"])
            ConstructionSpec(**reverse["core"])
    return {"honeybee": True, "core": True}

