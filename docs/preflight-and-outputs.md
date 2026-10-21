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

`epsm.output_capabilities(building, weather=weather, engine=engine, settings=settings)`
returns the owner-derived `epsm-output-capabilities/1` catalogue. Each descriptor
states an exact name, resolution, scope, unit and availability. Preflight rejects
required requests absent from this catalogue, inactive conditional fields and
incompatible units. Optional unavailable requests produce warnings. No unit
conversion or postprocessing is inferred. Monthly summaries remain separate
poststudy operations rather than direct engine outputs.

Core supplies normalized demand/annual metrics and conditional delivery/PV
outputs. With complete inputs and inspected weather it resolves exact native
`Zone Mean Air Temperature::ZONE-NAME` keys. Additional free-text
`HourlyOutputRequest` settings remain in `unverified_requests`; merely naming an
EnergyPlus variable cannot establish its existence, key scope or units. They are
usable through Core's existing execution API, but cannot satisfy a required
generic study output contract until an owner-supported descriptor verifies them.
Because Core validates every additional compiler request as required, an
unverified additional request also blocks generic study preflight when the
separate study requirements only ask for known normalized heating.
RC supplies its own signals, selected optics channels and coupled-basement
outputs, and reuses Core's public delivery descriptors. Arbitrary RC zone output
names remain unavailable.

Calendar discovery describes the selected engine interface. The shared-building
RC interface preserves ordinary and leap calendars, including all 8784 leap-year
hours. Its separate standalone `load_epw` API still explicitly rejects leap years;
preflight does not substitute that narrower interface.

Validation checks finite signals, expected units, exact selected annual hour
labels and hourly/annual kWh reconciliation. Its tolerance matches Core result
interpretation: relative 0.001, absolute 1e-6 kWh. It reports `thermal_complete`,
`delivery_complete` and `lca_complete` separately. Incomplete LCA cannot erase
valid thermal results; thermal demand does not imply delivered carrier accounting.
The existing `space_heating_and_fans` boundary is retained; this API does not
add DHW/cooling/plug loads to that boundary.
