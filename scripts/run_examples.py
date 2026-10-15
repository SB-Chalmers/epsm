# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Execute EPSM notebooks in fresh kernels using this installed environment."""

import argparse
import json
import sys
from pathlib import Path


def main():
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager
    from nbclient import NotebookClient
    from nbformat import read, write

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--integration", action="store_true", help="Also run actual annual RC and LCA"
    )
    parser.add_argument(
        "--logging",
        action="store_true",
        help="Run the coordinated logging handoff notebook",
    )
    parser.add_argument("--output", type=Path, default=Path("build/executed-examples"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    kernel = args.output.resolve() / "kernels" / "epsm-examples"
    kernel.mkdir(parents=True, exist_ok=True)
    (kernel / "kernel.json").write_text(
        json.dumps(
            {
                "argv": [
                    sys.executable,
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": "EPSM examples",
                "language": "python",
            }
        ),
        encoding="utf-8",
    )
    manager = KernelSpecManager(kernel_dirs=[str(kernel.parent)])
    notebooks = sorted((root / "examples").glob("0[012]_*.ipynb"))
    if args.integration:
        notebooks.extend(sorted((root / "examples").glob("03_*.ipynb")))
    if args.logging:
        notebooks.extend(sorted((root / "examples").glob("05_logging.ipynb")))
    for path in notebooks:
        notebook = read(path, as_version=4)
        NotebookClient(
            notebook,
            km=KernelManager(kernel_name="epsm-examples", kernel_spec_manager=manager),
            timeout=600,
            resources={"metadata": {"path": str(path.parent)}},
        ).execute(cleanup_kc=True)
        write(notebook, args.output / path.name)
        print(f"Passed fresh-kernel example: {path.name}", flush=True)


if __name__ == "__main__":
    main()
