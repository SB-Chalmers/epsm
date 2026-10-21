# Prepare a case and check its outputs

`epsm.preflight(building, weather, engine, settings, outputs)` inspects an explicit
case without running a simulation. It composes Core readiness, selected
weather verification and engine-owned capability checks. The Building is not
changed. The public `epsm_rc.preflight` owns RC reduction policy validation;
EPSM does not copy RC physics or import its private helpers.

An explicitly supplied `energyplus=` executable is verified through Core's
public compiler constructor, including its version command and IDD. No
simulation runs. Without an explicit executable, installation verification is
deferred to execution preparation.

```python
from epsm import preflight, validate_outputs

outputs = [
    {"name": "space_heating_demand_kwh", "resolution": "hourly",
     "required": True, "level": "building", "unit": "kWh"},
    {"name": "delivered_energy", "resolution": "annual",
     "required": True, "level": "building"},
    {"name": "lca", "resolution": "assessment",
     "required": False, "level": "building"},
]
report = preflight(building, weather, "epsm_rc", settings, outputs)
assert report["ready"], report["diagnostics"]
coverage = validate_outputs(evaluation, outputs)
assert coverage["ready"], coverage["diagnostics"]
```

The example requires an authored Building, inspected Weather, explicit RCSettings
and an already calculated evaluation. Missing delivery/assessment settings stay
actionable diagnostics. Ready preflight means the stated input/capability checks
passed; it does not guarantee later engine acceptance or empirical accuracy.

Omitted requirements request hourly heating and annual delivered carrier energy.
Strings are shortcuts, such as
`validate_outputs(evaluation, ["space_heating_demand_kwh"])`. Missing optional
outputs produce warnings; required failures make `ready` false. Arbitrary RC
per-zone output requests are reported as unsupported.

Validation checks finite signals, expected units, exact selected annual hour
labels and hourly/annual kWh reconciliation. Its tolerance matches Core result
interpretation: relative 0.001, absolute 1e-6 kWh. It reports `thermal_complete`,
`delivery_complete` and `lca_complete` separately. Incomplete LCA cannot erase
valid thermal results; thermal demand does not imply delivered carrier accounting.
The existing `space_heating_and_fans` boundary is retained; this API does not
add DHW/cooling/plug loads to that boundary.
