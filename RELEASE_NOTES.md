# Release candidate 0.8.0rc2 — Sveby shading, neighbours, SE.06 builds, type checks and fewer rejected runs (27 November 2026)

A candidate for 0.8.0. It replaces 0.8.0rc1, which was never published. The default
`ubem_v1` model policy gains the nine changes below. Results calibrated against 0.7.0 need
rechecking. Each change has a `ModelPolicy` switch that restores the earlier behaviour.
The candidate combination moves to Core 0.10.3 (`180f87f`), Data 0.9.0rc2 (`571f1e2`) and
Database 0.6.1 (`ae7e38c`); the other packages are unchanged.

## Fewer rejected runs

- Neighbours placed by EPSM no longer creep back over the target after their outline is
  cleaned, and short edges left by that clip are removed. Core used to reject these
  models with "Context building … overlaps target geometry" or near-coincident vertices.
- `EPSMBuilding.simulate` turns on Core's context-shadow retry
  (`recover_context_shadows=True`) unless the caller turns it off. It acts only after a
  shadow-capacity rejection and records any approximation; with Core 0.10.3 its last step
  drops neighbours lower than 5° above the horizon.
- Receipts, docs and comments describe each change in plain words instead of internal
  version numbers.

## Sveby window solar shading

Record-based models (`EPSMBuilding.from_record`) previously left the window solar factor
at 1.0 for every type, while `apply_archetype` took Core's Sveby total factor (0.50 for
housing; offices and schools only when a calendar was supplied). Both routes now apply
Sveby's occupant factor for blinds and curtains by default: 0.71 for single-family houses
and offices and 0.65 for schools. Multi-family is not applied (1.0). This is a tested model
choice from a held-out comparison, not a sourced value (Sveby gives 0.71). Fixed
obstructions are modelled as geometry, so the 0.50 total is not the default.
`ModelPolicy(solar_shading=...)` and `apply_archetype(..., solar_shading=...)` accept
`"behaviour"` (default), `"total"` (0.50; schools 0.65), `None` (off, as before) or a number
in (0, 1]. Authored `building_assumptions` facade values are kept as written.

## Heat-pump COP by pump type

Heat-pump delivery passes the building's EPC heat-pump type (`epsm_db.epc_systems`) and
era to Data's `heating_delivery_template`, so the seasonal COP follows the pump type when
Data supports it (Data 0.9.0rc1: ground 2.75, exhaust air 2.4 before 2006 and 2.75 from
2006, 3.0 from 2022, air–water 2.4, air–air 2.0). With Data 0.8.0 the field average 2.75
still applies. The receipt records `heat_pump_type`.

## Single-family storey check

When a single-family house's storey count is inferred from its LiDAR height, rather than
taken from valid EPC storeys, it is checked against the EPC Atemp, or the Lantmäteriet
register living area (`totalBoarea`) when there is no EPC. With more than 3 storeys, or an
area below 0.6 of footprint × storeys, the house gets clamp(round(area / (0.88 ×
footprint)), 1, 3) storeys at the typical floor height with a compact roof, and the
receipt says so. A conditioned basement's share is taken off Atemp first. The cause is
tree canopy: unclassified LiDAR points include vegetation, so houses built after their
area was scanned, on wooded plots, got 3–8 storeys. `single_family_storey_check=False`
restores the earlier behaviour.

## Single-family slab edge and household electricity

- **Insulated slab edge beam.** An insulated single-family slab on grade with no basement
  gets a vertical edge beam (Swedish kantelement practice; EPS-bygg *Grundboken* p. 69
  gives typical edge-beam ψ of 0.25–0.06 W/mK): 100 mm of the slab's own insulation, never
  thicker than that insulation, 0.3 m below the slab. Before this, Kiva left the slab edge
  bare.
- **BEN småhus household electricity.** Single-family houses use 30 kWh/m² Atemp with 70 %
  usable as heat (BEN, BFS 2016:12, table 2:1), instead of the multi-family Sveby value of
  21 kWh/m².
- `single_family_slab_edge_insulation_m=0, single_family_household_electricity_kwh_m2=None`
  restores the earlier behaviour.

## FTX among several ventilation systems

An EPC that ticks FTX together with other systems (for example F+FTX or FT+FTX) is modelled
as FTX at the observed-FTX template. The EPC has no per-system shares, and a building with
an FTX unit recovers heat on at least part of its air; STIL2 (2005) and STIL3 (ER 2025:25)
found no exhaust-only or natural-draught offices. Before, such a certificate was
"conflicting" and the era default ran. `ventilation_conflict_ftx=False` restores the earlier behaviour.

## Shading-only neighbours

Database-backed records get the lake's building components within 100 m as shading-only
neighbours, at their representative height, with overlaps resolved tallest first and
checked against the prepared footprint. Callers can pass their own rows
(`context_rows=...`); a portable record without rows gets no context and the receipt says
so. `context_radius_m=None` turns it off.

## Single-family SE.06 later-build envelope

SE.06 covers houses built 2006–2021, but the energy
rules tightened inside that span. From 1 February 2009 (BBR 16, BFS 2008:20) electrically
heated new buildings, heat-pump småhus included, had their own lower limit (95/75/55 kWh/m²
in zones I–III, against 150/130/110), and from 2012 (BBR 19, BFS 2011:6) the other limit fell
to 130/110/90 with Um 0.50 → 0.40 W/m²K. Measured heat-pump heating halves across the era
(about 43 kWh/m² for houses built 2006–08, 21 for 2017–21), while the model's heat demand was
flat. A single-family SE.06 house in the existing state that is heat pump or direct electric
and built 2009 or later, or built 2012 or later with any carrier, now gets the SE.06 advanced
constructions, windows and airtightness (the SE.07 values) through `component_states`. Its
observed ventilation is kept. The receipt names the rule, and the archetype assignment records
each component's source. This is an as-built representative, not a renovation. The size of
the change comes from the catalogue's authored values, not a measured survey of these houses.
Caller-chosen `component_states` win. `single_family_se06_later_build=False` restores the earlier behaviour.

A pre-registered test on fresh single-family SE.06 houses supported the change; the figures
are kept with the study, not in these notes.

## School SE.06 earlier-build envelope

School SE.06 covers 2006–2021. BBR 19 (BFS 2011:6), in force from 2012, lowered the limit for
non-electric lokaler from 100 to 80 kWh/m² in zone III and Um from 0.70 to 0.60 W/m²K. Schools
built before 2012 measure clearly more heat per m² than later ones, while the model used one
envelope for all. A school SE.06 in the existing state built before 2012 now gets the school
SE.05 existing wall, roof and window (whole catalogue constructions). Its era, ventilation,
airtightness and operation stay SE.06. The receipt records `school_earlier_build`, and the
archetype assignment names the donor. The size of the change comes from the catalogue's SE.05
values, not a measured survey. Caller-chosen `component_states` turn it off for that building.
`school_se06_earlier_build=False` restores the earlier behaviour.

A pre-registered test on school SE.06 supported the change; the figures are kept with the
study, not in these notes.

## Office SE.06 earlier-build envelope

The BBR 19 limit (BFS 2011:6) behind the school rule above applies to every
non-residential building, offices included. An office SE.06 in the existing state built
before 2012 now gets the office SE.05 existing wall, roof and window, with SE.06
ventilation, airtightness and operation. The receipt records `office_earlier_build`.
`office_se06_earlier_build=False` restores the earlier behaviour. It was checked on every
stored office SE.06 building, so it is calibrated rather than validated on held-out
buildings; the figures are kept with the study.

# Release 0.7.0 — measured stock operation (21 November 2026)

Sveby normal use stays the default. `ModelPolicy(operating_standard="measured")` and
`resolve_building_archetype(..., operating_standard="measured")` select Data's
observed stock operation: the multifamily setpoint by era, a self-draught total air
change net of the building's infiltration, and office flow and hours. Uses with no
adopted value keep normal use and say so.

In the default `ubem_v1` policy, heat-pump delivery takes the seasonal COP from
Data's `heating_delivery_template`, so modelled heat-pump electricity rises by about
9 % (COP 2.75 against 3.0), and `ModelPolicy.heat_pump_cop` is removed. Ventilation and
heating carriers are read through `epsm_db.epc_systems`; on 94,189 certificates from
the lake, including 23,835 with mixed carriers, carriers are unchanged.

The supported manifest moves to Data 0.8.0 (`bfcdb4d`) and Database 0.6.0 (`121ac59`), which add
these interfaces; the core requirement is now Data 0.8.0 and the `database` extra requires
Database 0.6.0. Core 0.10.0, RC 0.12.0, LCA 0.5.0, Studies 0.5.1, Workflows 0.6.2, smhi2epw
1.3.0 and Viewer 0.1.0 are unchanged. `epsm.__version__` now matches the package version.

# Release 0.6.2 — RC 0.12.0 in the supported combination (13 November 2026)

The supported manifest moves to RC 0.12.0 (`59102e1`), LCA 0.5.0 (`0c996ac`),
Studies 0.5.1 (`2b47429`) and Workflows 0.6.2 (`7249101`). RC's default thermal
model is now ISO 52016-1 with named settings (`thermal_model`, `window_optics`,
`solar_time`, `heat_recovery`), so default RC results change: about +11 % space
heating on the illustrative reference building. Settings saved with the former
`epsm_rc_5r1c_v1` profile still load and keep their 5R1C results. Examples, the
guide and tests pass explicit airflow and ground choices to `RCSettings` instead
of the deprecated `RCSettings.from_policy(...)`, and the `rc` and `all` extras
require RC 0.12.0. Core 0.10.0, Data 0.7.0, Database 0.5.0, smhi2epw 1.3.0 and
Viewer 0.1.0 are unchanged. The measured-use and EPC-systems work on `dev`, which
needs unreleased Data and Database changes, is not part of this release.

# Release 0.6.1 — Workflows 0.6.1 in the supported combination (2 November 2026)

The supported manifest moves to Workflows 0.6.1 (`690831d`: the campaign fixes
from the first Vera smoke run — packing a `stock_diversity` study with more
than one context passes the strata check, and the campaign worker acknowledges
the RC 0.11 approximations so RC columns are populated instead of NULL). Core
0.10.0, Data 0.7.0, RC 0.11.0, LCA 0.4.0, Database 0.5.0, Studies 0.5.0,
smhi2epw 1.3.0 and Viewer 0.1.0 are unchanged. No EPSM code changes; dependency
lower bounds stay at Core 0.9.0 and Workflows 0.5.0. A Vera environment installs
the released wheels `epsm_core`, `epsm_data` and `epsm_workflows[campaign]` from
this release.

# Release 0.6.0 — Core 0.10.0 and Workflows 0.6.0 in the supported combination (31 October 2026)

The supported manifest moves to Core 0.10.0 (`8a26072`: `solve_element_insulation`
and `Building.assign_element_u_value`, material-backed U-value authoring for
physical elements, and a self-draught natural exchange set from a measured total
air change) and Workflows 0.6.0 (`0537909`: dataset authoring with owner-backed
physical bindings, bounded Vera execution and the `epsm_workflows.campaign`
training-data packer and runner, extra `campaign`, CLI `epsm-campaign`). Data
0.7.0, RC 0.11.0, LCA 0.4.0, Database 0.5.0, Studies 0.5.0, smhi2epw 1.3.0 and
Viewer 0.1.0 are unchanged. No EPSM code changes; dependency lower bounds stay at
Core 0.9.0 and Workflows 0.5.0. A Vera environment installs the released wheels
`epsm_core`, `epsm_data` and `epsm_workflows[campaign]` from this release;
Workflows 0.6.0 requires Core 0.10.0 for envelope U-value solving.

# Release 0.5.1 — Core 0.9.1 and LCA 0.4.0 in the supported combination (30 October 2026)

The supported manifest moves to Core 0.9.1 (`9a0f02f`, the installing measure
recorded per material occurrence) and LCA 0.4.0 (`62e78df`: carbon and cost
payback, discounting, factor trajectories and B4 replacements). Data 0.7.0,
RC 0.11.0, Database 0.5.0, Workflows 0.5.0, Studies 0.5.0, smhi2epw 1.3.0 and
Viewer 0.1.0 are unchanged. No EPSM code changes: `AssessmentSettings` saved by
EPSM buildings in format 1 still load, and EPSM does not read LCA renovation
reports, whose format 2 rejects older files. Dependency lower bounds stay at
Core 0.9.0 and LCA 0.3.0. Consumers that install the supported wheels from the
EPSM release pick up the new combination on their next `ci` run; LCA's
replacement-carbon checks need Core 0.9.1 and no longer skip.

# Release 0.5.0 — LoD2 catalogue handoffs (29 October 2026)

EPSM consumes the frozen LoD2 catalogue through `core_inputs` and
`resolve_building_archetype`; legacy aliases and SE.07 resolve in Data. Generic
buildings borrow the matching multifamily construction and residential
operation with the donor recorded; an explicit `BASEMENT_FLOOR` is the soil slab
and `GROUND_FLOOR` the basement ceiling; naturally ventilated programmes keep
their normal-use outdoor-air timetable as an equivalent-flow assumption. Record
assembly reads GIS-lake evidence, runs SE.07 without a renovation state, takes
each system's airflow and heat recovery from Data's ventilation templates and
window ratios from its facade assumptions, maps EPC exhaust-with-recovery by
heating carrier, and forwards the catalogue's thermal-bridge surcharge to Core.

Record assembly reads `epsm_db` directly (`epsm_db.records`, `epsm_db.enums`,
`epsm_db.weather`); the retired `sweden_ubem` package is no longer imported.

EPSM 0.5.0 requires Data 0.7.0, Core 0.9.0 and LCA 0.3.0; the `rc` extra
requires RC 0.11.0 and the `database` extra Database 0.5.0. `compatibility-candidate.json` names that cohort for the
candidate release verification. `compatibility.json` keeps the 0.4.0 supported
combination until the candidate's installed checks pass and the cohort is
released; Workflows 0.4.0 and Studies 0.4.0 declare `epsm_core<0.9`, so the
promoted manifest also needs their updated releases.

# Release 0.4.0 — study platform

Add portable, checksummed evaluation bundles with external hourly signals and retained engine-run identity. Public preflight delegates engine-owned capability checks; output validation separates thermal, delivery and assessment completeness. Existing in-memory and dictionary result interfaces remain readable.

Both engine results now capture the actual resolved physical/weather/calendar
identity at normalization. Conflicting raw or cached identities are rejected;
legacy caches without this evidence are recomputed rather than relabelled.

Preflight composes public Core/RC output discovery and rejects unsupported required
names, resolutions, scopes, inactive channels and incompatible units before
execution. Optional unavailable signals remain warnings. Core 0.8.2 supplies the
new owner descriptor handoff; extra free-text EnergyPlus variables stay explicitly
unverified rather than being advertised as guaranteed study outputs.

Cohort verification tooling builds and installs immutable wheel combinations and
records required scenario evidence. The study acceptance harness exercises paired
annual energy and complete declared renovation impacts. Candidate verification
and promotion of the supported release manifest remain separate operations.

# Release 0.3.0 — 15 October 2026

Catalogue selections and custom authored archetypes share Building.apply_archetype(), with explicit replace/fill choices, retained application reports and visible unresolved inputs. Record assembly, component-state selection and renovation handovers use the same shared definitions.

EPSM requires Data 0.6.0 and Core 0.4.0; the optional database integration requires Database 0.3.0. See [archetype application](docs/archetype-application.md), [consumer migration](docs/archetype-consumers.md) and [installed acceptance checks](docs/archetype-installed-checks.md).

Required acceptance covers installed wheels, portable exchange, saved reports, actual annual RC and EnergyPlus 24.2 execution, and fresh-kernel examples. These checks establish software integration using explicit teaching assumptions, not empirical building validation.

# Release 0.2.0 — 15 October 2026

Application-owned console and JSONL configuration, record/catalogue handoffs, evaluation caches and engine/LCA delegation.

Libraries emit through Python's standard logging without configuring output.
Instrumented operations accept optional keyword-only `log_context`; identifiers
stay separate from scientific inputs, saved models and cache keys. INFO shows
major stages; DEBUG adds decisions and timing. Standalone commands support
`--log-level`, including `OFF`, where the package provides a command.

The EPSM application configures the combined stderr and optional DEBUG JSONL
output with `configure_logging`; `enabled=False` disables both destinations.
Existing callers and supported older collaborator signatures remain supported.
No new mandatory dependency is introduced by the logging implementation.

The coordinated release was requested for manual review and local validation
because GitHub refused to start several hosted jobs due to account billing.
Hosted checks that did not run are not counted as passes. See the
[coordinated verification record](https://github.com/SB-Chalmers/epsm_development/blob/main/docs/logging-verification.md)
for exact tested revisions, executed checks and remaining limitations.
