# Installed archetype acceptance checks

Build Data, Core, EPSM and their required collaborators as wheels in a clean
virtual environment. Install the built artifacts and run `python -m pip check`.
Run the existing installed platform check and the fresh-kernel examples as well.
The checkout's `compatibility.json` records the coordinated revisions.

```sh
python scripts/record_compatibility.py --mode pinned --output build/compatibility-receipt.json
python scripts/check_archetype_handoff.py --require-wheels \
  --directory build/archetype-handoff --wheels .ci/wheels \
  --compatibility-receipt build/compatibility-receipt.json \
  --energyplus-exe /absolute/path/to/energyplus
```

`record_compatibility.py` expects the dependency source checkouts under `.ci/`,
as in the hosted workflow. It checks the actual commits and installed versions.
The handoff check rejects editable imports and missing/moving revision evidence.
It retains import paths, versions, exact source revisions, wheel SHA-256 hashes
and the actual EnergyPlus version alongside its results.

The check roundtrips both a catalogue selection and an authored definition as
version-4 portable records, applies them to existing geometry through the same
Building API, and verifies retained application reports after Building save/load
and evaluation. Both routes execute annual RC; the catalogue route also executes
EnergyPlus 24.2. These runs use explicit teaching geometry, HVAC, reference area,
site conditions and RC policies. Their answers need not match: the programmes and
envelope inputs differ. This is package connection evidence, not calibration or
scientific validation of a real building.

EnergyPlus is a required prerequisite. The hosted workflow pins Ubuntu 24.04 and
installs the official EnergyPlus 24.2 binary for that operating system. Missing
executables, wrong versions, missing wheels, unresolved inputs and rejected engine
results fail the check. A failure report retains the reason when the check starts;
a workflow prerequisite failure is visible in its job log. Required checks do not
turn missing prerequisites into skips.

`archetype-compatibility-report.json` and the evaluation directories retain the
applied definitions, source records, actual chosen assumptions and energy outputs.
Keep the compatibility receipt with that report. Cleanup of migrated APIs is
gated on successful checks of the maintained consumers and this installed route.
