import os
from pathlib import Path
from pdfplumber.utils.exceptions import PdfminerException
from pandas.errors import ParserError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from src.logging_config import get_logger

from src.ingest import parse_pdf, parse_zerodha_tradebook, get_filename
from src.load import get_engine, create_table, insert_data, fetch_prototype_embeddings, get_headers,stamp_mapping_metadata, insert_mapping_log
from src.mapper import map_headers

FOLDER_DISPATCH = {
    "data/BankStatements": (lambda path: parse_pdf(path, "Bank"), "Bank"),
    "data/UPIExports": (lambda path: parse_pdf(path, "UPI"), "UPI"),
    "data/TradeBook": (parse_zerodha_tradebook, "Tradebook"),
}

def main():
    logger = get_logger()
    
    engine = get_engine()
    create_table(engine)

    # Fetch run_id from sequence
    with engine.connect() as connection:
        result = connection.execute(text("SELECT nextval('pipeline_run_id_seq')"))
        run_id = result.scalar()
    logger.info("Fetched run_id: %s", run_id)

    # Validate run_type from environment
    run_type = os.getenv("RUN_TYPE")
    if run_type is None or run_type not in ("dev", "benchmark", "production"):
        logger.error("Invalid or missing RUN_TYPE environment variable: %s", run_type)
        raise ValueError(f"RUN_TYPE must be one of ('dev', 'benchmark', 'production'), got: {run_type}")

    # Fetch prototype embeddings
    prototype_embeddings = fetch_prototype_embeddings(engine)
    if not prototype_embeddings:
        logger.error("prototype_embeddings table is empty; pipeline cannot map headers")
        raise RuntimeError("prototype_embeddings table is empty; pipeline cannot proceed without prototype embeddings")

    skipped_files = []
    db_rejected_files = []
    mapping_rejected_files = []
    inserted_files = []

    for folder, (parser_func, source_type) in FOLDER_DISPATCH.items():
        for file_path in Path(folder).iterdir():
            filename = get_filename(str(file_path))
            try:
                output = parser_func(str(file_path))
                if isinstance(output, list):
                    result = output
                    try:
                        insert_data(result, engine, filename, source_type)
                        inserted_files.append(file_path)
                    except IntegrityError as integ_err:
                        logger.warning("Integrity constraint failed for %s: %s", file_path, integ_err)
                        db_rejected_files.append(file_path)
                    except OperationalError as op_err:
                        logger.warning("DB error inserting %s: %s", file_path, op_err)
                        raise

                    headers = get_headers(result)
                    mapping_results = map_headers(headers, prototype_embeddings)
                    for row in mapping_results:
                        stamp_mapping_metadata(row, run_id, run_type, filename)
                    try:
                        insert_mapping_log(mapping_results, engine)
                    except IntegrityError as integ_err:
                        logger.warning("Integrity constraint failed for %s: %s", file_path, integ_err)
                        mapping_rejected_files.append(file_path)
                    except OperationalError as op_err:
                        logger.warning("DB error inserting %s: %s", file_path, op_err)
                        raise
                else:
                    _, reason = output
                    skipped_files.append(file_path)
                    continue
            except (PdfminerException, UnicodeDecodeError, ParserError) :
                skipped_files.append(file_path)
                continue

    logger.info(
        "Run complete: %d inserted, %d parse-skipped, %d db-rejected, %d mapping-rejected. DB Rejected: %s; Mapping Rejected: %s",
        len(inserted_files),
        len(skipped_files),
        len(db_rejected_files),
        len(mapping_rejected_files),
        db_rejected_files,
        mapping_rejected_files
    )

if __name__ == "__main__":
    main()