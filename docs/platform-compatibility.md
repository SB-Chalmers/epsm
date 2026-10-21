# EPSM-owned platform compatibility

EPSM owns both the supported installed combination and the lightweight daily
metadata guard. Consumers read the promoted manifest on their next normal CI run.

EPSM owns the platform's reviewed combination in
[`compatibility.json`](../compatibility.json). A package keeps its own version and
declared dependency bounds. EPSM records the exact combination that passes the
installed cross-package checks. Other repositories should consume this manifest
when adopting a coordinated combination, instead of maintaining another list.

## Two kinds of evidence

| Record | Meaning | What can update it |
| --- | --- | --- |
| `compatibility.json` | The reviewed release combination: exact versions and immutable source revisions | A reviewed change after the required installed-package and real-engine checks |
| `platform-registry.json` | Repository identities, main branches, selected integration extras and explicit CI-reference exceptions | A reviewed ownership or metadata-policy change |
| `build/platform-candidates.json` | A snapshot of current main revisions, declared versions, dependency requirements and drift from the supported set | The lightweight guard, automatically on its next run |
| `build/ci-references.json` | CI dependency references found at those captured source revisions | The lightweight audit, automatically on its next run |

The candidate report records exact Git identities even if a source change did not
bump its distribution version. It is metadata evidence. It does not certify public
API compatibility, successful installation, numerical equivalence or scientific
accuracy. A new candidate never rewrites the supported manifest automatically.

Current main metadata is checked against current main metadata. Historical
supported pins must be checked against metadata at those exact historical commits;
today's dependency bounds cannot invalidate a previously tested historical set.
Uncommitted local edits are not inspected as released package inputs.

## Automatic, bounded work

The metadata workflow runs one Python 3.13 job on relevant pull requests, relevant
main changes, once daily, and by manual request. It has a five-minute timeout and
cancels superseded runs. Sparse source checkouts retain only package metadata,
version declarations and workflow definitions. No EPSM package is imported or
installed; no model is compiled, no engine runs and no database is queried.

It validates distribution identity, static or literal dynamic versions, supported
Python versions and internal requirements including selected extras and markers.
Missing required metadata/access, an unsatisfied declared constraint, malformed
pins or a stale literal wheel version causes a failure with a report.

The CI-reference audit distinguishes the current main revision, the central
supported pin, another owner's fixed pin, dynamic expressions and explicitly
retained numerical reference checkouts. Another fixed cohort is reported for
review; its existence alone is not proof of an incompatibility. Dynamic references
are labelled unverified rather than evaluated by guessing at workflow expressions.
Exceptions match an exact owner, workflow, checkout path and revision, with a
reason; a changed reference is no longer covered by that exception.

Current full platform checks use two pinned Python lanes. A manual request can
select one Python 3.13 lane using dependency main branches; its receipt records the
actual checked-out revisions. Logging installation, integration and notebook checks
run within those same installed lanes, using the same supported manifest and
wheels. Their verification receipt is retained; there is no second logging matrix.
Full workflows run on PRs into dev/main and pushes to main, avoiding a duplicate
feature-push run. Their scientific checks remain required; this guard does not
replace them. `logging-compatibility.json` is retained as historical release
evidence and no longer selects the active logging matrix.

## Access and local use

The remote guard uses the repository-specific read-only deploy keys already
configured in EPSM for Data, Core, RC, LCA, DB, Studies, Workflows and Viewer. Weather is
public. It checks required key presence before cloning; it never publishes keys or
grants access. Viewer is private and has a separate display handoff; scientific
workers do not install it. Its `package.json`, tracked `VERSION` and Python
distribution versions must agree. The developer handbook has no scientific distribution in
this registry. Studio's application environment remains a separate consumer.

For local checks, install only the small guard requirements into a separate tools
environment. These commands read committed Git objects from the supplied sibling
checkouts and write reports only to the requested locations:

```sh
python -m pip install -r requirements-ci-metadata.txt
python scripts/check_platform_metadata.py --mode main --sources .. \
  --output build/platform-candidates.json --summary build/platform-summary.md
python scripts/audit_ci_references.py --sources .. \
  --metadata build/platform-candidates.json \
  --output build/ci-references.json --summary build/platform-summary.md
python scripts/render_compatibility.py --check
```

Use `--mode pinned` with local clones containing the historical objects to inspect
the supported set. CI's shallow main checkouts do not contain those older commits;
the installed release workflow checks its own exact pinned sources.

After an approved supported-manifest edit, run
`python scripts/render_compatibility.py` to update the bounded README table.
The guard rejects a table that no longer matches the manifest. The matrix and
logging checkout values are generated directly from the same manifest.

## Adopting a changed package

1. The next metadata run captures a new main SHA/version and reports affected
   dependency bounds and CI references. Read the package's migration notes.
2. Update an EPSM candidate branch with the intended exact pins and compatible
   bounds. Workflows participates in the installed scientific cohort; the separate
   display check verifies Core-to-Viewer handoffs.
3. Run the necessary installed checks once for that candidate. Record actual
   versions, source revisions and engine identities using the existing receipt.
4. Promote the tested combination through the normal release review. Regenerate
   the README table. Consumers adopt the central manifest on their next normal CI
   run while retaining their own checkout under test.

## Consumer interface

Each consumer checks out EPSM main read-only into `.ci/platform`, captures that
checkout's full Git SHA once, and runs its matrix generator. The names below are
the consumer's required dependency set; versions and revisions come only from the
central manifest. The consumer itself remains the PR checkout under test.

```sh
python .ci/platform/scripts/compatibility_matrix.py \
  --manifest .ci/platform/compatibility.json --consumer epsm_workflows \
  --packages epsm_data epsm_core epsm_lca epsm_rc epsm \
  --manifest-revision "$PLATFORM_MANIFEST_SHA" --mode pinned
```

The caller sets `PLATFORM_MANIFEST_SHA` to `git -C .ci/platform rev-parse HEAD`.
Matrix rows contain `python`, `mode`, `manifest_revision` and each dependency's
immutable revision. An external consumer's `epsm: self` resolves to that captured
SHA; EPSM's own workflow uses its calling checkout. Unknown dependencies, moving
supported revisions and unresolved `self` values fail before any matrix is emitted.
Default matrices exclude entries with `role: display`; a display handoff can select
Core and Viewer explicitly with `--packages`.

Consumers adopt promoted combinations on their next normal CI run. They do not
dispatch other repositories' checks. Their read-only deploy key grants access to
EPSM's manifest; it does not grant API orchestration permissions. See
[token scope](https://docs.github.com/en/actions/concepts/security/github_token).

## Verify a feature cohort before development merges

`scripts/candidate_cohort.py` captures selected clean feature-branch HEADs without
changing the supported manifest. Use it when related APIs must be tested together
before any of the participating changes reaches `dev`. Sources are sibling Git
checkouts named after the packages. Default selection is the registry's active
scientific packages; `--packages` selects a smaller explicit group.

Install the metadata requirements and the packages' declared build backends in
the builder environment first. The current scientific packages use setuptools;
`python -m pip install -r requirements-ci-metadata.txt build setuptools wheel`
prepares that builder. Build tools do not need to be added to every runtime
environment. Then capture the committed sources and choose the checks:

```sh
python scripts/candidate_cohort.py capture --sources /path/to/checkouts \
  --output /path/to/evidence/candidate.json
python scripts/candidate_cohort.py verify \
  --manifest /path/to/evidence/candidate.json \
  --directory /path/to/evidence/python311 \
  --python /path/to/python3.11 --scenario installed-platform
```

Run a separate verification directory with Python 3.13 for the other supported
lane. A development run on another interpreter is useful evidence for that
interpreter only. `--scenario study-platform` selects the six-evaluation study
acceptance script when that script exists at the captured EPSM revision. A
selected missing script fails; it never becomes a passing or skipped gate.
Without `--scenario`, the check establishes wheel installation, dependency
consistency and isolated owner imports only.

Capture refuses dirty sources and records each actual immutable SHA, version,
local source location and selected extras. Verification checks that those sources
still match, archives the captured commits into its new output directory, builds
one wheel per package and installs all candidate wheels together into a fresh
virtual environment. It removes inherited Python path overrides, checks actual
installed owner paths/versions and runs scenarios outside the source checkouts.
Scientific scenarios keep their own fixtures, prerequisites and numerical
assertions. They must fail when a required engine or service is missing.

The output contains the wheel files, archived sources, environment, stage logs
and `receipt.json`. The receipt records the candidate identity, source commits,
actual wheel hashes, observed interpreter and imports, selected scenarios and
failure/not-run status. Existing output directories are never replaced. A failed
build or scenario leaves its receipt available. Keep outputs outside tracked
source directories or under an explicitly ignored artifact directory.

Use `--dependency-wheels` to supply an additional third-party wheel directory and
`--no-index` for an offline installation. `--requirements` adds declared test or
notebook prerequisites to the isolated environment. The tool invokes commands
with argument lists rather than shell strings. It does not check out branches,
commit files, publish artifacts or update release pins.

After all feature gates pass, merge into `dev` through reviewed PRs and capture
the actual merged cohort again. Conflict resolutions invalidate earlier evidence
for the affected code. After normal release merges, verify tagged sources and
artifacts separately before promoting the supported manifest. The handbook's
study readiness guide records the campaign acceptance criteria and ownership.

A new main commit can differ from the supported release revision without
changing its package version, for example when CI adopts this interface. The
daily report records that drift; it never dispatches downstream suites or silently
promotes a new scientific combination.
