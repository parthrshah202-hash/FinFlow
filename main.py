from pathlib import Path
from pdfplumber.utils.exceptions import PdfminerException
from pandas.errors import ParserError
from sqlalchemy.exc import IntegrityError, OperationalError
import logging

from src.ingest import parse_pdf, parse_zerodha_tradebook, get_filename, logger
from src.load import get_engine, create_table, insert_data

FOLDER_DISPATCH = {
    "data/BankStatements": (lambda path: parse_pdf(path, "Bank"), "Bank"),
    "data/UPIExports": (lambda path: parse_pdf(path, "UPI"), "UPI"),
    "data/TradeBook": (parse_zerodha_tradebook, "Tradebook"),
}

def main():
    logging.basicConfig(
        filename="logs/pipeline.log",
        format='%(asctime)s %(levelname)s: %(message)s',
        filemode='w',
    )
    logger.setLevel(logging.INFO)
    
    engine = get_engine()
    create_table(engine)

    skipped_files = []
    db_rejected_files = []
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
                        continue
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
        "Run complete: %d inserted, %d parse-skipped, %d db-rejected. DB Rejected: %s",
        len(inserted_files),
        len(skipped_files),
        len(db_rejected_files),
        db_rejected_files
    )

if __name__ == "__main__":
    main()