"""Serialize corpus/index mutations and searches across Streamlit sessions and CLIs."""
from functools import lru_cache, wraps
from pathlib import Path
from filelock import FileLock
from contextlib import contextmanager


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


@contextmanager
def preserve_corpus_on_failure(root):
    """Hold the project lock and restore page evidence if indexing fails."""
    with project_lock(Path(root).resolve()):
        path = Path(root) / "data/processed/documents.jsonl"
        previous = path.read_bytes() if path.exists() else None
        try:
            yield
        except BaseException:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                temporary = path.with_suffix(".restore.tmp")
                temporary.write_bytes(previous)
                temporary.replace(path)
            raise
