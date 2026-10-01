"""Korean BM25 (Okapi) and weighted reciprocal-rank fusion.

Cosine scores remain cosine scores: RRF is used for ordering, never confidence.
The token snapshot is keyed by every canonical chunk ID and content hash.
"""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
import logging
from tempfile import NamedTemporaryFile


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi(num_workers=1)


@lru_cache(maxsize=12000)
def tokenize(text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", text).lower()
    # Keep raw identifiers, numbers, and negations alongside Korean morphemes.
    raw = re.findall(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[가-힣]+", text)
    morphs = [t.form.lower() for t in _kiwi().tokenize(text)
              if t.tag.startswith(("N", "V", "M", "SL", "SN"))]
    return tuple(raw + morphs)


class KeywordIndex:
    def __init__(self, candidates, path: Path | None = None):
        self.candidates = {c.chunk_id: c for c in candidates}
        signature = hashlib.sha256(json.dumps(
            sorted((c.chunk_id, c.content_hash) for c in candidates)
        ).encode()).hexdigest()
        tokens = None
        if path and path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if (isinstance(cached, dict) and cached.get("version") == 1
                        and cached.get("signature") == signature
                        and isinstance(cached.get("tokens"), dict)
                        and set(cached["tokens"]) == set(self.candidates)
                        and all(isinstance(value, list) and all(isinstance(t, str) for t in value)
                                for value in cached["tokens"].values())):
                    tokens = cached["tokens"]
            except (ValueError, OSError, KeyError):
                pass
        if tokens is None:
            tokens = {c.chunk_id: list(tokenize(c.content)) for c in candidates}
            if path:
                temporary = None
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                            suffix=".tmp", delete=False) as handle:
                        temporary = Path(handle.name)
                        json.dump({"version": 1, "signature": signature,
                                   "tokens": tokens}, handle, ensure_ascii=False)
                    temporary.replace(path)
                except OSError:
                    logging.getLogger(__name__).warning("검색 캐시를 저장하지 못해 메모리에서 검색합니다.")
                finally:
                    if temporary:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
        self.counts = {key: Counter(value) for key, value in tokens.items()}
        self.df = Counter(term for counts in self.counts.values() for term in counts)
        self.average = sum(map(sum, (c.values() for c in self.counts.values()))) / max(1, len(tokens))

    def search(self, question: str, allowed_ids: set[str], limit: int = 40):
        query = set(tokenize(question))
        results = []
        n = len(self.counts)
        for key in sorted(allowed_ids & self.counts.keys()):
            counts = self.counts[key]
            matched = query & counts.keys()
            if not matched:
                continue
            length = sum(counts.values())
            score = sum(math.log(1 + (n - self.df[t] + .5) / (self.df[t] + .5)) *
                        counts[t] * 2.5 / (counts[t] + 1.5 * (.25 + .75 * length / max(1, self.average)))
                        for t in matched)
            coverage = len(matched) / max(1, len(query))
            results.append((key, score, coverage))
        return sorted(results, key=lambda item: (-item[1], item[0]))[:limit]


def fuse(dense, keyword, *, k=60, dense_weight=.55, keyword_weight=.45):
    scores = Counter()
    for weight, ranking in ((dense_weight, dense), (keyword_weight, keyword)):
        for rank, key in enumerate(ranking, 1):
            scores[key] += weight / (k + rank)
    return sorted(scores, key=lambda key: (-scores[key], key))
