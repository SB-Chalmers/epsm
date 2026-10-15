# Apply an archetype to existing geometry

`Building.apply_archetype(archetype, *, mode="replace", calendar=None)` applies a
Data `Archetype` to a geometrically configured EPSM building. It updates the
building in place and returns an immutable `ArchetypeApplicationReport`. A
catalogue selection and a manually authored definition use this same route.

Data owns the material → layer → component → element → construction-set hierarchy,
portable operating profiles, HVAC templates and envelope definitions. Core
validates physical inputs and builds schedules. EPSM combines those definitions
with the building's explicit geometry and project choices.

See the [geometry and archetype notebook](../examples/00_geometry_and_archetype.ipynb)
for an offline example. It deliberately leaves installed systems unresolved.

## Replace and fill missing

`replace` replaces only supplied construction roles and supplied operation,
system or envelope inputs. Omitted sections remain as configured. A partial
custom operating profile overlays its supplied use fields on an existing use;
BEN changes only its selected DHW intensity. Existing independent evidence is
retained for the other fields.

`fill_missing` fills physical elements without constructions and sections without
assignments. It preserves existing operation and HVAC choices, including explicit
zero infiltration. An independent missing thermal-bridge assumption can still be
filled. Invalid supplied values raise even if that mode would retain an existing
choice. Source definitions can legitimately remain incomplete: the report lists
unresolved requirements rather than inventing inputs.

Geometry, orientation, context, opening placement, opening areas and window ratios
are preserved. Applicable window properties update their performance. Assignment
performs no weather, database or engine lookup, and does not create a renovation
stage. Use the existing targeted construction and renovation APIs for those tasks.

## Explicit project choices

Office and school profiles need a mapping with `calendar_year`, `active_dates`
and `calendar_source`. `normal_use`, when supplied, is a boolean. No holiday list
is generated. Residential `calendar_year` selects the supported annual schedule
expansion. Custom profiles contain their own resolved schedules.

The archetype cannot establish an installed ventilation topology, heating carrier,
project reference area, site ground conditions or weather. Selecting a partial
HVAC template does not turn those missing inputs into defaults.

Envelope ACH on `conditioned_volume` can be applied directly. ACH on a TABULA
reference volume stays unresolved until the caller supplies an appropriate
conversion. An infiltration rate per Atemp needs an explicit
`load_reference_area_m2`. By applying that definition, the caller asserts that
this chosen load-reference area is the intended Atemp; the report records that
interpretation separately. Existing measured area evidence is preserved. Explicit
conflicting reference-basis evidence remains unresolved. A
`conditioned_floor_area` policy alone does not establish Atemp.

Whole-building application does not assign a separate common-space or mixed-use
profile. Such supplied inputs appear as unmatched; apartment zoning requiring a
separate common-space assignment remains an explicit requirement.

## Historical records

`building.archetype_applications` is a tuple of immutable application reports.
Each report keeps the full version-4 definition, source references, interpretation
choices, before/after physical identities, applied/replaced/retained/unmatched
paths and remaining requirements. Detailed `to_dict()` exports are detached.
Representations are bounded and perform no I/O.

`Building.to_dict()` / `Building.from_dict()` retain the history; older saved
buildings without that field still load. Copy and renovation children inherit the
history. Each evaluation freezes the reports present when calculation starts.
Later application leaves earlier evaluation records and renovation stages intact.
Physical cache identities remain based on Core inputs.

The development application API requires the exact Data and Core revisions recorded
in `compatibility.json` (and the logging combination in `logging-compatibility.json`).
Core retains version 0.3.0 during development, so its version requirement alone does
not identify a revision that provides `assign_inputs` and the profile resolver.
