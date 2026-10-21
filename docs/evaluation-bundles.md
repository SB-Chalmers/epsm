# Portable evaluation bundles

`Evaluation.save_bundle(directory)` saves an existing evaluation without running
an engine or LCA. `Evaluation.load_bundle(directory)` verifies and eagerly
restores it. Existing destinations are refused. Ordinary in-memory results,
`to_dict()` and simulation's legacy `evaluation.json` remain available.

```python
from epsm import Evaluation, load_bundle_metadata

directory = evaluation.save_bundle("outputs/retained-baseline")
metadata = load_bundle_metadata(directory)
assert metadata["id"] == evaluation.id
restored = Evaluation.load_bundle(directory)
assert restored.energy.run_id == evaluation.energy.run_id
```

Here `evaluation` is a previously calculated Evaluation. Its `energy_id` and
the raw engine's content identity, `energy.run_id`, have distinct meanings. Older
energy dictionaries without `run_id` remain readable; no identity is invented.

Fresh simulation normalization captures `energy.diagnostics.physical_inputs_sha256`
from the exact resolved Core spec supplied to the engine, together with its
`weather_sha256`, `calendar_year` and original `building_snapshot_id`. Conflicting
identity supplied by an engine raises an error. Both engines use the same
boundary. The evaluation's `state_id` records the current captured state; a
reused energy calculation retains the original engine snapshot identity.
Legacy cache entries without physical/weather/calendar evidence are recomputed;
conflicting cache identities fail explicitly. Existing saved evaluations remain
readable, but missing provenance is never reconstructed by an archive reader.

The stored format is `epsm-evaluation-bundle/1`, independently of the producer's
package version. The directory contains:

- `manifest.json`: completion marker, evaluation ID and checksummed references.
- `metadata.json`: full evaluation metadata, including snapshot, weather,
  material path, assessment, scalars, units, diagnostics and LCA.
  `energy.hourly` and `energy.time_axis` are removed; `energy.hourly_signals`
  lists retained names.
- `arrays/hourly-0000.npy`, and so on: one array per hourly signal.
- `arrays/time-axis.npy`: the original hour labels as strings.
- `artifacts/`: copies of available raw engine files.
- `weather.epw`: selected weather bytes, when weather is present.

The manifest structure is below; checksum strings are placeholders:

```json
{
  "format": "epsm-evaluation-bundle/1",
  "evaluation_id": "evaluation-id",
  "metadata": {"path": "metadata.json", "sha256": "..."},
  "arrays": {
    "hourly": {
      "space_heating_demand_kwh": {
        "path": "arrays/hourly-0000.npy", "sha256": "...",
        "dtype": "float64", "shape": [8760]
      }
    },
    "time_axis": {
      "path": "arrays/time-axis.npy", "sha256": "...",
      "dtype": "<U13", "shape": [8760]
    }
  },
  "artifacts": {"errors": {"path": "artifacts/0000-eplusout.err", "sha256": "..."}},
  "inputs": {"weather": {"path": "weather.epw", "sha256": "..."}}
}
```

Every path is relative to the bundle directory. `metadata.energy.artifacts`
contains the same paths as `manifest.artifacts`; weather paths are relative too.
Loading a complete Evaluation resolves these paths to its new directory. The
weather checksum must match its captured identity. Missing optional raw engine
files are named in `energy.diagnostics.unavailable_bundle_artifacts`; missing
selected weather is an error. Saving does not change the original evaluation.

Studies and other consumers can read this documented manifest and metadata with
the standard library, without importing EPSM. Arrays can be read independently
using `numpy.load(path, allow_pickle=False)`. The manifest supplies shape, dtype
and checksum; scalar/hourly units remain in `metadata.energy.units`. LCA retains
its own versioned payload.

`load_bundle_metadata` checks all file hashes without decoding arrays.
`verify=False` skips hashing but still checks paths and existence. Consumers
listing many studies can instead verify metadata first and verify each array
when explicitly opened.

Readers reject escaped paths, symbolic links, malformed/nonfinite JSON,
unsupported versions and changed hashes. Saving stages complete files, reserves
a new destination using atomic directory creation, and publishes the manifest
last. Ordinary failures clean up the incomplete destination. An interrupted
process may leave a directory without a manifest; readers reject it. This is
not a power-loss transaction.
