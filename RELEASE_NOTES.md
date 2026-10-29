# Release 0.5.0 — LoD2 catalogue handoffs (candidate, 29 October 2026)

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

EPSM 0.5.0 requires Data 0.7.0, Core 0.9.0 and LCA 0.3.0; the `rc` extra
requires RC 0.11.0. `compatibility-candidate.json` names that cohort for the
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
