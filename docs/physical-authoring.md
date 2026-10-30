# Material-backed insulation authoring

EPSM's public `Building` inherits Core's physical authoring operations. There is
one implementation; EPSM does not maintain another insulation solver.

```python
from epsm import Building
from epsm_data.domain import BuildingElement as Role

building = Building(preset="illustrative-reference")
wall = next(element for element in building.elements if element.role == Role.EXT_WALL)
building.assign_element_u_value(
    0.2,
    component_name=wall.construction.components[0].name,
    layer_index=0,
    element_ids=[wall.identifier],
)
restored = Building.from_dict(building.to_dict())
assert restored.snapshot().sha256 == building.snapshot().sha256
```

The target is nominal opaque U-value in W/(m2 K), using Core's existing total
film resistance of 0.17 m2 K/W. It excludes thermal bridges and ground-transfer
effects. Choose the adjustable physical component and zero-based layer index
explicitly. Bounds are metres, defaulting to 0.001–2.0 m. Unattainable targets,
windows and unequal constituent depths fail without partially changing the
Building. Original materials, fractions and installed identities are retained;
quantities follow actual solved depths.

This authors a draft assumption. It creates no renovation event or material
flow. Use `Building.renovate` for an installed intervention. Existing source
evidence, assessment configuration, snapshots and prior evaluation records keep
their meaning. A saved study using this operation requires the Core feature;
older studies and the EPSM Building interchange format are unchanged.

The cross-package regression is `tests/test_physical_authoring_handoff.py`.
Core owns the detailed solver, atomicity and material-quantity tests.
