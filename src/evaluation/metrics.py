"""Source-location metrics, with unanswerable questions scored separately."""
def source_matches(result, expected):
    return all(getattr(result, key, None) == value for key, value in expected.items())


def score_case(case, results):
    expected = case.get("expected", [])
    if not expected:
        return {"answerable": False, "correct_rejection": not results,
                "hit": None, "reciprocal_rank": None}
    ranks = [i for i, result in enumerate(results, 1)
             if any(source_matches(result, source) for source in expected)]
    return {"answerable": True, "correct_rejection": None,
            "hit": bool(ranks), "reciprocal_rank": 1 / min(ranks) if ranks else 0.}


def summarize(rows):
    positives = [r for r in rows if r["answerable"]]
    negatives = [r for r in rows if not r["answerable"]]
    return {"questions": len(rows), "answerable": len(positives), "unanswerable": len(negatives),
        "hit_at_k": sum(r["hit"] for r in positives) / len(positives) if positives else None,
        "mrr": sum(r["reciprocal_rank"] for r in positives) / len(positives) if positives else None,
        "correct_rejection_rate": sum(r["correct_rejection"] for r in negatives) / len(negatives) if negatives else None}
