# EPSM-owned platform compatibility

Status: implemented on `codex/platform-compatibility-guard`; activation requires
merging this branch. No package release or supported-version upgrade is implied.

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
actual checked-out revisions. Logging checks consume the same supported manifest.
Full workflows run on PRs into dev/main and pushes to main, avoiding a duplicate
feature-push run. Their scientific checks remain required; this guard does not
replace them. `logging-compatibility.json` is retained as historical release
evidence and no longer selects the active logging matrix.

## Access and local use

The remote guard uses the repository-specific read-only deploy keys already
configured in EPSM for Data, Core, RC, LCA, DB, Studies and Workflows. Weather is
public. It checks required key presence before cloning; it never publishes keys or
grants access. Viewer is explicitly unpublished and excluded until its repository
and read access exist. The developer handbook has no scientific distribution in
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
   bounds. Include Workflows in the installed cohort before advertising its full
   compatibility; its current integration fixtures need updating first.
3. Run the necessary installed checks once for that candidate. Record actual
   versions, source revisions and engine identities using the existing receipt.
4. Promote the tested combination through the normal release review. Regenerate
   the README table. Consumers adopt the central manifest through their own review.

Per-package workflows still contain independently maintained dependency checkouts.
This increment audits them; it does not rewrite or merge changes into other
repositories. A later rollout can make each consumer read the central manifest,
or use a read/write GitHub App to open focused update PRs. Keep its permissions
separate from this read-only guard. GitHub's default token is scoped to its own
repository; sharing a private reusable workflow also needs the documented access
setting. See [token scope](https://docs.github.com/en/actions/concepts/security/github_token)
and [private workflow sharing](https://docs.github.com/en/actions/how-tos/reuse-automations/share-across-private-repositories).

The first audit is expected to expose older pins, including EPSM's supported
Core/RC 0.4 cohort. That is a backlog to assess, not permission to claim that every
latest main combination has already passed the scientific release gates.
