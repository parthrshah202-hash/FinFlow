import pytest
import math
import numpy as np

from src.mapper import map_headers


def create_unit_vector(similarity_target: float) -> list[float]:
    x = math.sqrt(1.0 - similarity_target ** 2)
    return [similarity_target, x]


class VectorFakeModel:
    def __init__(self, header_vector: np.ndarray):
        self.header_vector = header_vector

    def encode(self, *args, **kwargs):
        return np.array([self.header_vector])


@pytest.mark.parametrize(
    "similarity_target, expected_flag",
    [
        (0.75, "Mapped"),         # Exact boundary: >= 0.75 must be "Mapped"
        (0.749, "Review needed"), # Just below boundary: < 0.75 must trigger "Review needed"
        (0.90, "Mapped"),         # Sanity check: clearly above boundary
    ],
)
def test_threshold_boundaries(monkeypatch, similarity_target, expected_flag):
    v_header = np.array([1.0, 0.0])
    v_proto = np.array(create_unit_vector(similarity_target))

    fake_model = VectorFakeModel(header_vector=v_header)
    monkeypatch.setattr("src.mapper._get_model", lambda: fake_model)

    prototype_embeddings = [("domain_a", "canonical_target", v_proto)]

    results = map_headers(
        headers=["sample_header"],
        prototype_embeddings=prototype_embeddings
    )

    assert results[0]["mapping_flag"] == expected_flag
    assert math.isclose(results[0]["similarity_score"], similarity_target, abs_tol=1e-5)