import numpy as np
import pytest

import src.mapper as mapper


class FakeModel:
    """
    Fake embedding model that:
    1. Returns controlled 2D unit vectors for predictable dot-product similarities.
    2. Tracks call counts and encoded texts to verify caching behavior.
    """
    def __init__(self):
        self.call_count = 0
        self.encoded_texts = []

    def encode(self, texts, convert_to_numpy=True):
        self.call_count += 1
        # Convert generator/iterable to list if necessary
        text_list = list(texts)
        self.encoded_texts.extend(text_list)

        embeddings = []
        for text in text_list:
            normalized = str(text).lower().strip()
            if "revenue" in normalized:
                embeddings.append([1.0, 0.0])
            elif "expense" in normalized:
                embeddings.append([0.0, 1.0])
            elif "test_header" in normalized:
                # Encodes to unit vector [1.0, 0.0] so dot product equals 1st coordinate of prototype
                embeddings.append([1.0, 0.0])
            else:
                embeddings.append([0.2, 0.2])
        return np.array(embeddings, dtype=float)


def test_map_headers_uses_max_score_not_average(monkeypatch):
    """
    Discriminator Test:
    Proves that map_headers takes the MAX score per canonical field rather than AVERAGE.

    Setup:
      - Canonical Field X ("revenue"):
          Proto 1 dot product = 0.90
          Proto 2 dot product = 0.30
          => Max = 0.90, Avg = 0.60
      - Canonical Field Y ("expense"):
          Proto 1 dot product = 0.65
          Proto 2 dot product = 0.65
          => Max = 0.65, Avg = 0.65

    Inequalities:
      1. max(revenue) [0.90] > max(expense) [0.65]  --> Max logic selects "revenue"
      2. avg(revenue) [0.60] < max(expense) [0.65]  --> Avg logic would select "expense"
    """
    fake_model = FakeModel()
    monkeypatch.setattr(mapper, "_get_model", lambda: fake_model)

    prototype_embeddings = [
        # Field X: revenue
        ("revenue", "rev_high", np.array([0.90, 0.43589], dtype=float)),
        ("revenue", "rev_low",  np.array([0.30, 0.95394], dtype=float)),
        # Field Y: expense
        ("expense", "exp_mid1", np.array([0.65, 0.75993], dtype=float)),
        ("expense", "exp_mid2", np.array([0.65, 0.75993], dtype=float)),
    ]

    headers = ["test_header"]
    result = mapper.map_headers(headers, prototype_embeddings)

    assert len(result) == 1
    # Max logic must select "revenue" with 0.90 score
    assert result[0]["matched_canonical_field"] == "revenue"
    assert pytest.approx(result[0]["similarity_score"], abs=1e-3) == 0.90


def test_map_headers_groups_by_canonical_field_and_caches_within_call(monkeypatch):
    """
    Verifies output order preservation, result formatting, AND that duplicate headers 
    are deduplicated before model encoding (proving caching occurs).
    """
    fake_model = FakeModel()
    monkeypatch.setattr(mapper, "_get_model", lambda: fake_model)

    prototype_embeddings = [
        ("revenue", "revenue_proto", np.array([1.0, 0.0], dtype=float)),
        ("expense", "expense_proto", np.array([0.0, 1.0], dtype=float)),
    ]

    # "Revenue  " and "Revenue" normalize to the exact same key ("revenue")
    headers = ["Revenue  ", "expense", "Revenue"]
    result = mapper.map_headers(headers, prototype_embeddings)

    # 1. Functional correctness assertions
    assert len(result) == 3
    assert [item["incoming_header"] for item in result] == headers
    assert [item["matched_canonical_field"] for item in result] == ["revenue", "expense", "revenue"]
    assert [item["mapping_flag"] for item in result] == ["Mapped", "Mapped", "Mapped"]
    assert result[0]["similarity_score"] == result[2]["similarity_score"]

    # 2. Caching side-effect assertions:
    # Out of 3 incoming headers, only 2 unique strings should be passed to encode()
    assert len(fake_model.encoded_texts) == 2


def test_load_threshold_reads_config_value():
    assert mapper._load_threshold() == pytest.approx(0.75)


def test_map_headers_sets_flags_for_empty_prototypes(monkeypatch):
    fake_model = FakeModel()
    monkeypatch.setattr("src.mapper._get_model", lambda: fake_model)

    result = mapper.map_headers(["revenue"], [])

    assert len(result) == 1
    assert result[0]["incoming_header"] == "revenue"
    assert result[0]["matched_canonical_field"] is None
    assert result[0]["similarity_score"] == 0.0
    assert result[0]["mapping_flag"] == "No valid prototype found"