# EPSM

<!-- EPSM introduction: Pocket CAD -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/welcome/epsm-dark.png">
  <img src="docs/assets/welcome/epsm.png" width="160" height="160" alt="EPSM — The platform: an open building cell with one active inner wall.">
</picture>

Welcome to EPSM, a research platform for exploring buildings and renovation
choices. Build a physical model, choose an energy engine and compare energy use
and climate impact through one Python interface. Each evaluation keeps its
inputs, assumptions and results available for inspection.

**[Explore the EPSM platform →](docs/platform.md)**
<!-- /EPSM introduction -->

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/SB-Chalmers/epsm/actions/workflows/ci.yml) [![Releases](https://img.shields.io/badge/releases-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm/releases) [![Issues](https://img.shields.io/badge/issues-GitHub-181717?logo=github&logoColor=white)](https://github.com/SB-Chalmers/epsm/issues)

## From building inputs to renovation choices

![EPSM simulation platform: building inputs, physical model, energy engines, energy and climate assessment, and renovation comparison](docs/assets/welcome/Figure_03a_epsm_simulation_platform.png)

Follow one building from its inputs to an energy and climate comparison.
The figure is conceptual; comparison bars are schematic. See the
[platform guide](docs/platform.md) for package roles, the construction data model
and each engine's scope.

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
| `epsm_core` | 0.8.2 | `18fe2c531e248511c7e8965ddb045acd6bcaddf8` |
| `epsm_data` | 0.6.0 | `d799272d1e3058287b18da9f138197d2e415a594` |
| `epsm_db` | 0.3.0 | `9e29a575f5495b76d5a8553bbe6e20dd4f0e1ff0` |
| `epsm_lca` | 0.2.0 | `dfec3ed0a568e5c4f5375b00881aa5ae8e00f414` |
| `epsm_rc` | 0.9.0 | `8837d3e8afd2d5be70172fd88d74598f1eba74ff` |
| `epsm_studies` | 0.4.0 | `d38ffc053cc4e9f88cb86e15018bf6ce309a65a9` |
| `epsm_viewer` | 0.1.0 | `f2c847b9cd44280b7cf21803acfefa6e49e78b1b` |
| `epsm_workflows` | 0.4.0 | `433a8b6d461ad2016e6f8c046aeaeb16b2861787` |
| `smhi2epw` | 1.3.0 | `6792b2a4d1bc6a7bdcd1bd77b35dd0ff704f2b29` |
<!-- compatibility-table:end -->

</details>

## License

[MIT](LICENSE).

## People and support

Developed at Chalmers University of Technology as part of the EPSM research platform.

**Funding**: Swedish Energy Agency (Project ID: P2024-04053)

**Partners**:

- Lindholmen Science Park AB
- Sinom AB
- Stiftelsen Chalmers Industriteknik

**Team**:

- **Lead Developer**: Sanjay Somanath
- **Principal Investigator**: Alexander Hollberg
- **Contributors**: Yinan Yu, Dag Wästberg

<p align="center">
  <img src="docs/assets/welcome/logos.png" width="100%" alt="Chalmers University of Technology, Chalmers Industriteknik, Sinom, Lindholmen Science Park and Swedish Energy Agency logos">
</p>
