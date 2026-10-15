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
