import numpy as np
import pytest
from sqlalchemy import select,inspect

from src.load import get_engine, mapping_log, prototype_embeddings


@pytest.fixture(scope="module")
def engine():
    engine = get_engine()
    yield engine


def test_prototype_embeddings_has_26_rows(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(prototype_embeddings)).fetchall()

    assert len(rows) == 26


@pytest.mark.parametrize(
    ("canonical_field", "prototype_text"),
    [
        ("Amount (Rs)", "Withdrawal Amount (INR)"),
        ("Notes", "Chq./Ref.No"),
        ("Transaction Date", "Txn Date"),
        ("Transaction Details", "Particulars"),
        ("Type", "trade_type"),
    ],
)
def test_prototype_embeddings_known_rows(engine, canonical_field, prototype_text):
    stmt = select(prototype_embeddings).where(
        prototype_embeddings.c.canonical_field == canonical_field,
        prototype_embeddings.c.prototype_text == prototype_text,
    )
    with engine.connect() as connection:
        rows = connection.execute(stmt).fetchall()

    assert len(rows) == 1

    embedding = rows[0][2]
    assert embedding is not None

    if isinstance(embedding, str):
        embedding = [float(value.strip()) for value in embedding.strip("[]").split(",") if value.strip()]
    else:
        embedding = list(np.asarray(embedding, dtype=np.float32))

    assert len(embedding) == 384


def test_mapping_log_table_has_expected_schema(engine):
    expected_columns = [
        "id",
        "run_id",
        "source_filename",
        "incoming_header",
        "matched_canonical_field",
        "similarity_score",
        "mapping_flag",
        "run_type",
        "created_at",
    ]

    inspector = inspect(engine)
    actual_columns = [column["name"] for column in inspector.get_columns("mapping_log")]

    assert actual_columns == expected_columns
