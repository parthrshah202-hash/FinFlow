import os

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy import create_engine

from src.ingest import logger

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


def get_engine() -> Engine:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    engine=create_engine(database_url)
    return engine


def create_table(engine: Engine) -> None:
    create_table_statement = text(
        """
        CREATE TABLE IF NOT EXISTS raw_uploads (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_data JSONB NOT NULL,
            uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    with engine.begin() as connection:
        connection.execute(create_table_statement)
    logger.info("Ensured table raw_uploads exists")


def insert_data(data: list[dict], engine: Engine, filename: str, source_type: str) -> None:
    if not data:
        logger.info("No data to insert for %s, skipping", filename)
        return
    rows = [{"filename": filename, "source_type": source_type, "raw_data": row} for row in data]
    with engine.begin() as connection:
        connection.execute(raw_uploads.insert(), rows)
    logger.info("Inserted %s rows into raw_uploads for %s", len(rows), filename)
