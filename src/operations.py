"""Serialize corpus/index mutations and searches across Streamlit sessions and CLIs."""
from functools import lru_cache, wraps
from pathlib import Path
from filelock import FileLock


@lru_cache(maxsize=16)
def project_lock(root: str | Path) -> FileLock:
    directory = Path(root) / "data/catalog"
    directory.mkdir(parents=True, exist_ok=True)
    return FileLock(str(directory / "operations.lock"), timeout=1800)


def locked_service(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with project_lock(self._project_root):
            return method(self, *args, **kwargs)
    return wrapped
