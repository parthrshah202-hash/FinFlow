import os

import numpy as np
from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Column, DateTime, Float, Integer, MetaData, Table, Text, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from src.logging_config import get_logger

logger = get_logger()

metadata = MetaData()
raw_uploads = Table(
    "raw_uploads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("filename", Text, nullable=False),
    Column("source_type", Text, nullable=False),
    Column("raw_data", JSONB, nullable=False),
    Column("uploaded_at", DateTime, nullable=False, server_default=func.now()),
)

prototype_embeddings = Table(
    "prototype_embeddings",
    metadata,
    Column("canonical_field", Text, primary_key=True),
    Column("prototype_text", Text, primary_key=True),
    Column("embedding", Vector(384), nullable=False),
)

mapping_log = Table(
    "mapping_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, nullable=False),
    Column("source_filename", Text, nullable=False),
    Column("incoming_header", Text, nullable=False),
    Column("matched_canonical_field", Text, nullable=False),
    Column("similarity_score", Float, nullable=False),
    Column("mapping_flag", Text, nullable=True),
    Column(
        "run_type",
        Text,
        nullable=False,
    ),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint("run_type IN ('dev', 'benchmark', 'production')", name="ck_mapping_log_run_type"),
)


def get_engine() -> Engine:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    engine=create_engine(database_url)
    return engine


def create_table(engine: Engine) -> None:
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE SEQUENCE IF NOT EXISTS pipeline_run_id_seq"))
    logger.info("Ensured tables exist: raw_uploads, prototype_embeddings, mapping_log; pipeline_run_id_seq sequence ensured")


def insert_data(data: list[dict], engine: Engine, filename: str, source_type: str) -> None:
    if not data:
        logger.info("No data to insert for %s, skipping", filename)
        return
    rows = [{"filename": filename, "source_type": source_type, "raw_data": row} for row in data]
    with engine.begin() as connection:
        connection.execute(raw_uploads.insert(), rows)
    logger.info("Inserted %s rows into raw_uploads for %s", len(rows), filename)


def fetch_prototype_embeddings(engine: Engine) -> list[tuple[str, str, np.ndarray]]:
    query = select(
        prototype_embeddings.c.canonical_field,
        prototype_embeddings.c.prototype_text,
        prototype_embeddings.c.embedding,
    )
    with engine.connect() as connection:
        result = connection.execute(query)
        rows = [(row[0], row[1], np.array(row[2],dtype=np.float32)) for row in result.fetchall()]
    logger.info("Fetched %s rows from prototype_embeddings", len(rows))
    return rows


def get_headers(data: list[dict]) -> list[str]:
    return list(data[0].keys())


def stamp_mapping_metadata(row: dict, run_id: int, run_type: str, filename: str) -> None:
    row["run_id"] = run_id
    row["run_type"] = run_type
    row["source_filename"] = filename


def insert_mapping_log(data: list[dict], engine: Engine) -> None:
    if not data:
        logger.info("No data to insert for mapping_log, skipping")
        return
    with engine.begin() as connection:
        connection.execute(mapping_log.insert(), data)
    logger.info("Inserted %s rows into mapping_log", len(data))

    
if __name__ == "__main__":
    engine = get_engine()
    create_table(engine)
