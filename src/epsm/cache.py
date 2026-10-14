"""Independent, atomic energy and LCA calculation caches."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from epsm_core.weather import file_sha256

from .results import encode, identity


def materialize_artifacts(value, directory):
    """Copy retained files, explicitly reporting unavailable optional artifacts."""
    value = json.loads(encode(value))
    artifacts, unavailable = {}, []
    for index, (name, source) in enumerate(value.get("artifacts", {}).items()):
        path = Path(source)
        if path.is_file():
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{index}-{path.name}"
            if path.resolve() != target.resolve():
                shutil.copyfile(path, target)
            artifacts[name] = str(target.resolve())
        else:
            unavailable.append(name)
    value["artifacts"] = artifacts
    if unavailable:
        value.setdefault("diagnostics", {})["unavailable_cached_artifacts"] = (
            unavailable
        )
    return value


class EvaluationCache:
    """Cache completed calculations with checksummed, relocatable artifacts.

    Malformed or changed persisted entries fail explicitly. Memory-only caches
    reuse calculated arrays even if optional original engine files were removed;
    the evaluation reports those unavailable files by name.
    """

    def __init__(self, directory=None):
        self.directory = Path(directory).resolve() if directory is not None else None
        self._memory = {}

    def get(self, kind, key):
        if kind not in {"energy", "lca"}:
            raise ValueError("Cache kind must be energy or lca")
        if not self.directory:
            item = self._memory.get((kind, key))
            return json.loads(item) if item is not None else None
        path = self.directory / kind / (key + ".json")
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.get("key") != key or data.get("format") != 2:
            raise ValueError(f"Incompatible cache record: {path}")
        if identity(data["value"]) != data.get("value_sha256"):
            raise ValueError(f"Changed cache calculation: {path}")
        value = data["value"]
        if kind == "energy":
            artifacts = {}
            for name, item in value.get("artifacts", {}).items():
                source = (self.directory / item["path"]).resolve()
                if not source.is_relative_to(self.directory) or not source.is_file():
                    raise ValueError(f"Missing cache artifact: {name}")
                if file_sha256(source) != item["sha256"]:
                    raise ValueError(f"Changed cache artifact: {name}")
                artifacts[name] = str(source)
            value["artifacts"] = artifacts
        return value

    def put(self, kind, key, value):
        if kind not in {"energy", "lca"}:
            raise ValueError("Cache kind must be energy or lca")
        if not self.directory:
            self._memory[kind, key] = encode(value)
            return
        value = json.loads(encode(value))
        directory = self.directory / kind
        directory.mkdir(parents=True, exist_ok=True)
        if kind == "energy":
            value = materialize_artifacts(value, directory / key)
            value["artifacts"] = {
                name: dict(
                    path=str(Path(path).relative_to(self.directory)),
                    sha256=file_sha256(path),
                )
                for name, path in value["artifacts"].items()
            }
        fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(
                    encode(
                        dict(
                            format=2, key=key, value=value, value_sha256=identity(value)
                        )
                    )
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, directory / (key + ".json"))
        finally:
            Path(name).unlink(missing_ok=True)
