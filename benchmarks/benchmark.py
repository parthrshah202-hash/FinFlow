import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import token_set_ratio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.load import fetch_prototype_embeddings, get_engine
from src.mapper import map_headers


def exact_match(header: str, canonical_fields: list[str]) -> tuple[str, float]:
    for field in canonical_fields:
        if header == field:
            return field, 1.0
    return "", 0.0


def fuzzy_match(header: str, canonical_fields: list[str]) -> tuple[str, float]:
    if not canonical_fields:
        return "", 0.0

    best_field = canonical_fields[0]
    best_score = 0.0

    for field in canonical_fields:
        score = token_set_ratio(header, field) / 100.0
        if score > best_score:
            best_field = field
            best_score = score

    return best_field, best_score


def sentence_transformer_match(header: str, prototype_embeddings: list[tuple[str, str, np.ndarray]]) -> tuple[str, float]:
    result = map_headers([header], prototype_embeddings)[0]
    matched_field = result.get("matched_canonical_field")
    if matched_field is None:
        matched_field = ""
    return matched_field, float(result.get("similarity_score", 0.0))


def run_benchmark() -> None:
    project_root = Path(__file__).resolve().parents[1]
    mapping_path = project_root / "benchmarks" / "data" / "Mapping.csv"
    schema_path = project_root / "config" / "schema.json"
    thresholds_path = project_root / "config" / "thresholds.json"
    output_path = project_root / "benchmarks" / "output" / "benchmark_results.csv"

    # FIX 1: Prevent pandas from converting "NULL" to NaN
    mapping_df = pd.read_csv(mapping_path, keep_default_na=False)

    with schema_path.open("r", encoding="utf-8") as handle:
        canonical_fields = json.load(handle)["canonical_fields"]

    # FIX 2: Fail-loud validation guard
    valid_target_headers = set(canonical_fields) | {"NULL"}
    invalid_headers = set(mapping_df["Correct_header"]) - valid_target_headers
    assert not invalid_headers, (
        f"Invalid values found in Correct_header: {invalid_headers}. "
        f"Expected subset of: {valid_target_headers}"
    )

    with thresholds_path.open("r", encoding="utf-8") as handle:
        thresholds = json.load(handle)
    st_threshold = float(thresholds.get("mapping_confidence_threshold", 0.75))
    fuzzy_threshold = float(thresholds.get("fuzzy_confidence_threshold", 0.0))

    engine = get_engine()
    prototype_embeddings = fetch_prototype_embeddings(engine)

    output_rows: list[dict] = []
    for row in mapping_df.to_dict(orient="records"):
        raw_header = row["raw_header"]
        source = row["source_file"]
        ground_truth = row["Correct_header"]
        is_null_row = ground_truth == "NULL"

        exact_match_result, exact_score = exact_match(raw_header, canonical_fields)
        fuzzy_match_result, fuzzy_score = fuzzy_match(
            raw_header, canonical_fields
        )
        st_match_result, st_score = sentence_transformer_match(
            raw_header, prototype_embeddings
        )

        if is_null_row:
            exact_correct = exact_match_result == ""
            fuzzy_threshold_pass = fuzzy_score < fuzzy_threshold
            fuzzy_top1_correct = fuzzy_threshold_pass
            st_threshold_pass = st_score < st_threshold
            st_top1_correct = st_threshold_pass
        else:
            exact_correct = exact_match_result == ground_truth
            fuzzy_top1_correct = fuzzy_match_result == ground_truth
            fuzzy_threshold_pass = (
                fuzzy_top1_correct and fuzzy_score >= fuzzy_threshold
            )
            st_top1_correct = st_match_result == ground_truth
            st_threshold_pass = st_top1_correct and st_score >= st_threshold

        output_rows.append(
            {
                "header": raw_header,
                "source": source,
                "ground_truth": ground_truth,
                "exact_match_result": exact_match_result,
                "fuzzy_match_result": fuzzy_match_result,
                "fuzzy_score": fuzzy_score,
                "st_match_result": st_match_result,
                "st_score": st_score,
                "exact_correct": exact_correct,
                "fuzzy_top1_correct": fuzzy_top1_correct,
                "fuzzy_threshold_pass": fuzzy_threshold_pass,
                "st_top1_correct": st_top1_correct,
                "st_threshold_pass": st_threshold_pass,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df = pd.DataFrame(
        output_rows,
        columns=[
            "header",
            "source",
            "ground_truth",
            "exact_match_result",
            "fuzzy_match_result",
            "fuzzy_score",
            "st_match_result",
            "st_score",
            "exact_correct",
            "fuzzy_top1_correct",
            "fuzzy_threshold_pass",
            "st_top1_correct",
            "st_threshold_pass",
        ],
    )
    output_df.to_csv(output_path, index=False)

if __name__ == "__main__":
    run_benchmark()
