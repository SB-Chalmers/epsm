# Use archetypes with building evidence

`Building.from_record(record, archetype=selected, calendar=...)` first creates the
physical geometry from explicit record facts and caller choices, retains the
independent record evidence, then calls `Building.apply_archetype`. The selected
Data definition remains an assumption. Record observations and their reported
area definitions remain unchanged.

```python
from epsm import Building
from epsm_data import Catalogue

selected = Catalogue.load().for_year("multi_family", 1960, state="existing")
building = Building.from_record(record, storeys=3, storey_height_m=2.8,
    load_reference_area_m2=record.atemp_m2, archetype=selected,
    calendar={"calendar_year": 2023})
print(building.archetype_applications[-1].requirements)
```

This snippet needs an explicit `record` with usable area evidence. Omitting the
archetype preserves gradual authoring. A calendar without an archetype is an
error. Neither this method nor a catalogue construction era selects installed
systems, weather, a site ground boundary or a measured window ratio.

## Independent component evidence

The maintained `epsm.catalogue_application.resolve_building_archetype` compatibility
route now includes a common Data `Archetype` as `selection["archetype"]`. The
existing native construction/glazing fields and complete nominal inspection
bundle remain available. It selects component states from independent source
descriptions; changing windows leaves opaque constructions and airtightness
unchanged. Sources and fallback states are retained in the portable definition.
A changed combination receives a new construction snapshot identity with no
invented intervention year; an unchanged physical combination retains its
catalogue identity.

```python
from epsm.catalogue_application import resolve_building_archetype

selection = resolve_building_archetype(category="multi_family",
    construction_year=1960, climate_zone="SE.Zone3", ventilation="F",
    default_state="existing", component_states={"window": "advanced"},
    component_sources={"window": "project:window-survey"})
building.apply_archetype(selection["archetype"], calendar={"calendar_year": 2023})
```

The default `existing` state is an era representative, not evidence that a
building has never been renovated. Each explicit component selection requires its
own source. Target matching and EPC residuals do not decide which constructions
can load. `epsm.catalogue_release.core_inputs` uses `Catalogue.get` and the public
portable nominal exporter; loading a physical recipe requires no calibration
assessment. The existing function names remain during the coordinated migration.

## Existing stock scenarios

`epsm.legacy_records.EPSMBuilding.from_record` retains its explicit `ubem_v1`
completion policy and mixed-programme behavior. Its Data profile selections now
use Core's public converter. Residential BEN selection, labelled generic
fallbacks, normal/leap-year schedules, assumed office/school calendars and
reference-area conversions retain their prior physical values. These policy
calendars are explicit scenario assumptions; general archetype application does
not generate holidays or calendars.

Legacy overrides can supply `component_states` and `component_sources` together.
The receipt keeps the complete version-4 archetype definition as well as the
component assignment audit. The physical model still distinguishes reported
Atemp (or its labelled geometric fallback) from geometric conditioned area.
Compilation remains an explicit preflight; `preflight=False` never claims
simulation readiness.

The renovation teaching example now applies its catalogue fabric through the
same Building method. It explicitly retains the named teaching preset's
operation, HVAC and envelope assumptions. Renovation steps still use their
existing targeted operations, and children inherit the application history.
