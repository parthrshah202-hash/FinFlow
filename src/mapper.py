import json
from pathlib import Path
from src.logging_config import get_logger
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

logger = get_logger()

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - exercised only if dependency is absent
    SentenceTransformer = None


_MODEL = None


def _load_threshold() -> float:
    thresholds_path = Path(__file__).resolve().parent.parent / "config" / "thresholds.json"
    with thresholds_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    return float(payload["mapping_confidence_threshold"])


def _get_model():
    global _MODEL
    if _MODEL is None:
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers is required to map headers")
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL


def map_headers(headers: list[str], prototype_embeddings: list[tuple[str, str, np.ndarray]]) -> list[dict]:
    model = _get_model()
    cache: dict[str, tuple[str | None, float]] = {}
    threshold = _load_threshold()

    if not prototype_embeddings:
        return [
            {
                "incoming_header": header,
                "matched_canonical_field": None,
                "similarity_score": 0.0,
                "mapping_flag": "No valid prototype found",
            }
            for header in headers
        ]

    prototype_fields = [field for field, _, _ in prototype_embeddings]
    prototype_vectors = np.vstack([embedding.reshape(1, -1) for _, _, embedding in prototype_embeddings])

    results: list[dict] = []
    for header in headers:
        normalized_key = header.strip().lower()
        cached_result = cache.get(normalized_key)
        if cached_result is not None:
            matched_canonical_field, similarity_score = cached_result
        else:
            header_embedding = np.asarray(
                model.encode([header], convert_to_numpy=True), dtype=float
            ).reshape(1, -1)
            similarity_scores = cosine_similarity(header_embedding, prototype_vectors)[0]

            grouped_scores: dict[str, float] = {}
            for canonical_field, score in zip(prototype_fields, similarity_scores):
                previous_score = grouped_scores.get(canonical_field)
                if previous_score is None or score > previous_score:
                    grouped_scores[canonical_field] = float(score)

            matched_canonical_field, similarity_score = max(
                grouped_scores.items(), key=lambda item: item[1], default=(None, 0.0)
            )
            cache[normalized_key] = (matched_canonical_field, similarity_score)

        mapping_flag = "Mapped" if similarity_score >= threshold else "Review needed"

        results.append(
            {
                "incoming_header": header,
                "matched_canonical_field": matched_canonical_field,
                "similarity_score": similarity_score,
                "mapping_flag": mapping_flag,
            }
        )

    return results
