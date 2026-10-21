# epsm

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SB-Chalmers/epsm/actions/workflows/ci.yml) [![Releases](https://img.shields.io/badge/releases-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm/releases) [![Issues](https://img.shields.io/badge/issues-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm/issues)

Build, simulate and compare buildings and renovation options through one Python
interface. EPSM connects physical building models, energy engines and lifecycle
climate assessment, retaining the inputs and results of each evaluation.

<a id="install-and-examples"></a>

## Getting started

Requires Python 3.11+, Git and access to the EPSM dependency repositories.

```sh
git clone https://github.com/SB-Chalmers/epsm.git
cd epsm
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  "epsm_data @ git+https://github.com/SB-Chalmers/epsm_data.git@main" \
  "epsm_core @ git+https://github.com/SB-Chalmers/epsm_core.git@main" \
  "epsm_lca @ git+https://github.com/SB-Chalmers/epsm_lca.git@main" \
  "epsm_rc @ git+https://github.com/SB-Chalmers/epsm_rc.git@main" \
  -e '.[rc,examples]'
```

```python
from epsm import Building

building = Building(preset="illustrative-reference")
print(building)
```

The preset supplies teaching assumptions. Start with the worked notebooks to
provide your own building inputs and EPW weather, then run RC energy and climate
comparisons. EnergyPlus simulations need a separate EnergyPlus installation.

## Documentation

- [Detailed guide and shared development environment](docs/guide.md)
- [Worked notebooks](examples/README.md)
- [Platform and package overview](docs/platform.md)
- [Compatibility and verification](docs/platform-compatibility.md)
- [Release notes](RELEASE_NOTES.md)

<details>
<summary>Tested package combination</summary>

### Tested package combination

[compatibility.json](compatibility.json) records the reviewed versions and exact
commits. See the [detailed guide](docs/guide.md#tested-package-combination) for scope.

<!-- compatibility-table:start -->
| Package | Version | Tested commit |
| --- | --- | --- |
| `epsm` | 0.4.0 | `self` |
| `epsm_core` | 0.8.2 | `1ea867d849b808bc9f879f2fb740c54a51754295` |
| `epsm_data` | 0.6.0 | `bc8449402b9e0dbe0ea85ff76c954cf36d209f86` |
| `epsm_db` | 0.3.0 | `9e29a575f5495b76d5a8553bbe6e20dd4f0e1ff0` |
| `epsm_lca` | 0.2.0 | `00141d0500e717b4f18a9d69e158f0af2aae1934` |
| `epsm_rc` | 0.9.0 | `8837d3e8afd2d5be70172fd88d74598f1eba74ff` |
| `epsm_studies` | 0.4.0 | `d38ffc053cc4e9f88cb86e15018bf6ce309a65a9` |
| `epsm_viewer` | 0.1.0 | `f2c847b9cd44280b7cf21803acfefa6e49e78b1b` |
| `epsm_workflows` | 0.4.0 | `433a8b6d461ad2016e6f8c046aeaeb16b2861787` |
| `smhi2epw` | 1.3.0 | `6792b2a4d1bc6a7bdcd1bd77b35dd0ff704f2b29` |
<!-- compatibility-table:end -->

</details>

## License

[MIT](LICENSE).
