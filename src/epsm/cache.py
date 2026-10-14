"""Independent, atomic energy and LCA calculation caches."""

import json
from pathlib import Path
import os
import tempfile

from .results import encode


class EvaluationCache:
    """Optional persistent cache. Only completed energy/assessment is reusable."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else None
        self._memory = {}

    def get(self, kind, key):
        if kind not in {"energy", "lca"}:
            raise ValueError("Cache kind must be energy or lca")
        if (kind, key) in self._memory:
            return json.loads(self._memory[kind, key])
        if self.directory:
            path = self.directory / kind / (key + ".json")
            if path.exists():
                data = json.loads(path.read_text())
                if data.get("key") != key or data.get("format") != 1:
                    raise ValueError(f"Incompatible cache record: {path}")
                return data["value"]
        return None

    def put(self, kind, key, value):
        self._memory[kind, key] = encode(value)
        if self.directory:
            directory = self.directory / kind
            directory.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(encode(dict(format=1, key=key, value=value)))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, directory / (key + ".json"))
            finally:
                Path(name).unlink(missing_ok=True)
