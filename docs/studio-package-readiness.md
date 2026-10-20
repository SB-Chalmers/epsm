# Package readiness for Studio

EPSM 0.3.1 coordinates the package combination in
[`compatibility.json`](../compatibility.json). The [generated version table](../README.md#tested-package-combination)
is the authoritative current list; packages keep independent release versions.

## Released boundaries

- Core owns physical building inputs and neutral `.scene()` data using `epsm.scene/1`.
  Viewer owns browser and notebook display, with no renderer dependency in Core.
- Workflows owns prepared studies, authenticated attempts/results, checksummed
  assets and runtime verification. Schema 3 plans bind each case to a content-addressed
  engine fingerprint. Prepare older plans again; no migration is provided.
- RC and EnergyPlus remain separate engines. Studio can select either backend.
  The accepted common annual boundary is space heating and ventilation fans.
- Studies owns the released comparison helpers. Uncommitted grouping, assessment
  and notebook experiments are excluded from this release.
- DB supplies portable `BuildingRecord` inputs and stored-height evidence. Missing
  model heights remain explicit unresolved inputs until the caller supplies an
  assumption with provenance. GIS Lake is an unconfirmed delivery option still
  under development; the acceptance gate needs no live database or provider.
- Studio owns application adapters, authentication, drafts, caches, permissions,
  jobs and deployment. This release implements no Studio or production changes.

## Acceptance evidence

The normal installed-package lanes run on Python 3.11 and 3.13 with EnergyPlus
24.2. Each lane retains source revisions, installed versions, wheel hashes and
actual executable identity. Existing logging checks and fresh-kernel examples
share these lanes.

The workflow handoff runs a bounded two-row grid and six-row Jansen design for
both engines. It checks ordered outputs, unchanged physical inputs, finite annual
values, nonempty EnergyPlus settings round trips, retained controlled failures,
explicit retries and completed resume without duplicate attempts. This tiny Jansen
check establishes execution and bookkeeping, not sensitivity-estimator accuracy
or equivalence between the engines. Numerical comparisons remain in RC's owner CI.

The portable-record gate executes actual RC and renovation LCA and exports a
schema-validated scene. A separate Python 3.13/Node 22 display lane passes released
Core scenes through installed Python Viewer and the public JavaScript geometry
API. Viewer owner CI covers browser interaction, notebook display, licenses and
clean artifact installation, including source-to-wheel rebuild without Node.

Viewer is delivered through the private [GitHub release](https://github.com/SB-Chalmers/epsm_viewer/releases/tag/v0.1.0).
Authenticate with access to that repository before downloading:

```sh
gh release download v0.1.0 --repo SB-Chalmers/epsm_viewer --dir viewer-release
cd viewer-release
shasum -a 256 -c SHA256SUMS
python -m pip install epsm_viewer-0.1.0-py3-none-any.whl
npm install ./epsm_viewer-0.1.0.tgz
```

The Python notebook extra is optional. No public registry publication is required.

## Keeping the platform coordinated

[Central compatibility management](platform-compatibility.md) separates the tested
manifest from daily current-main metadata. Consumers select dependency names,
resolve revisions from EPSM and retain their own checkout under test. A promoted
combination reaches each consumer on its next normal CI run. The five-minute
metadata job reports drift and incompatible declarations without running engines
or dispatching downstream suites.
