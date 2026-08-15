import logging
import re
import os
import pandas as pd
import pdfplumber
from src.logging_config import get_logger
from pandas.errors import ParserError
from pdfplumber.utils.exceptions import PdfminerException

logger = get_logger()


def headers_to_dicts(result_dict: dict) -> list[dict]:
    """Convert a {"headers": [...], "rows": [[...], ...]} structure into a list of dicts,
    zipping each row against the headers list.

    Args:
        result_dict (dict): dict with keys "headers" (list of str) and "rows" (list of lists)

    Returns:
        list[dict]: one dict per row, keyed by header name
    """
    return [dict(zip(result_dict["headers"], row)) for row in result_dict["rows"]]


def get_filename(filepath: str) -> str:
    """Extract the base filename from a full file path.

    Args:
        filepath (str): full path to the source file

    Returns:
        str: the base filename (e.g. "statement.pdf")
    """
    return os.path.basename(filepath)


def attach_filename(list_of_dicts: list[dict], filename: str) -> None:
    """Attach the source filename to every dict in a list, in place, under the key "Filename".

    Args:
        list_of_dicts (list[dict]): rows already converted to dicts
        filename (str): filename to attach to every row

    Returns:
        None (mutates list_of_dicts in place)
    """
    for row in list_of_dicts:
        row["Filename"] = filename


def clean_dict(result_dict):
    """Clean the extracted result dict in place

    Args:
        result_dict (dictionary): The raw extracted dictionary

    Returns:
        None
    """
    for index, header in enumerate(result_dict["headers"]):
        if header is None:
            header = ""
        result_dict["headers"][index] = str(header).replace("\n", " ")

    for row_idx, row in enumerate(result_dict["rows"]):
        if isinstance(row, dict):
            for key, cell in list(row.items()):
                if cell is None:
                    row[key] = ""
                else:
                    row[key] = str(cell).replace("\n", " ")
        else:
            for cell_idx, cell in enumerate(row):
                if cell is None:
                    cell = ""
                result_dict["rows"][row_idx][cell_idx] = str(cell).replace("\n", " ")


def detect_upi_source(raw_text):
    """Detect the UPI statement source from raw extracted text.

    Args:
        raw_text (str): Raw text extracted from a UPI PDF statement.

    Returns:
        str or None: Detected source identifier. Returns "gpay" for Google Pay,
            "phonepe" for PhonePe, "paytm" for Paytm, or None if the source
            could not be determined.
    """
    lines = raw_text.splitlines()
    window_lines = lines[:30]
    for line in window_lines:
        normalized = line.strip()
        if "UPITransactionID" in normalized:
            return "gpay"
        if "UTR No." in normalized:
            return "phonepe"
        if "UPI Ref No" in normalized:
            return "paytm"

    snippet = " | ".join(line.strip() for line in window_lines if line.strip())
    logger.warning("Unable to detect UPI source from text snippet: %s", snippet)
    return None


def parse_paytm(raw_text, file_path):
    """Parse Paytm UPI transaction statement and extract transaction details.

    Args:
        raw_text (str): Raw text content extracted from the Paytm PDF statement
        file_path (str): Path to the source PDF file for logging purposes

    Returns:
        list[dict]: A list of dictionaries representing parsed transactions with attached filenames on success. On failure, returns (None, str) with a reason string.
    """
    period_pattern = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})'?(\d{2})\s*-\s*(\d{1,2})\s+([A-Za-z]{3})'?(\d{2})")
    period_match = period_pattern.search(raw_text)

    if not period_match:
        logger.warning("No statement period found in Paytm file at %s", file_path)
        return None, "no statement period found"

    start_day, start_month, start_year_raw, end_day, end_month, end_year_raw = period_match.groups()
    start_year = int(start_year_raw) if len(start_year_raw) == 4 else (2000 + int(start_year_raw))
    end_year = int(end_year_raw) if len(end_year_raw) == 4 else (2000 + int(end_year_raw))

    if start_year != end_year:
        logger.warning(
            "Paytm statement year mismatch for %s: start year %s, end year %s",
            file_path, start_year, end_year,
        )
        return None, "statement year mismatch"

    statement_year = start_year

    # Step 1: strip blank lines, preserve line breaks for header removal
    raw_blob = "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())

    # Step 2: remove repeated multi-line page headers ("Date & ... Amount\nTime")
    header_pattern = re.compile(
        r"Date\s*&.*?Transaction Details.*?Notes\s*&\s*Tags.*?Your Account.*?Amount\nTime",
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned_blob = re.sub(header_pattern, "", raw_blob)
    lines = [line.strip() for line in cleaned_blob.splitlines() if line.strip()]

    # Step 3: locate transaction boundaries
    transaction_blobs = []
    index = 0
    while index < len(lines):
        line = lines[index]
        date_match = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})\b", line)
        if not date_match or index + 1 >= len(lines):
            index += 1
            continue
        if not re.match(r"^\d{1,2}:\d{2}\s*[AP]M$", lines[index + 1], flags=re.IGNORECASE):
            index += 1
            continue

        end_index = index + 1
        for candidate_index in range(index + 2, len(lines)):
            if "UPI Ref No:" in lines[candidate_index]:
                end_index = candidate_index
                break

        transaction_lines = lines[index:end_index + 1]
        transaction_blobs.append((date_match, lines[index + 1].strip(), " ".join(transaction_lines)))
        index = end_index + 1

    if not transaction_blobs:
        logger.warning("No Paytm transactions found in file at %s", file_path)
        return None, "no transactions found"

    rows = []
    for date_match, time_value, transaction_blob in transaction_blobs:
        day, month = date_match.groups()
        date_time = f"{day} {month} {statement_year} {time_value}"

        blob_without_date = transaction_blob[date_match.end():].strip()
        blob_without_time = re.sub(re.escape(time_value), "", blob_without_date, count=1).strip()

        description_match = re.match(
            r"^(.*?)(?=\s*(?:Note:|Tag:|UPI Ref No:|$))",
            blob_without_time,
            flags=re.IGNORECASE,
        )
        description = description_match.group(1).strip() if description_match else blob_without_time.strip()

        upi_id_match = re.search(r"UPI ID:\s*([A-Za-z0-9@.-]+)", transaction_blob, flags=re.IGNORECASE)
        upi_id = upi_id_match.group(1).strip() if upi_id_match else ""

        transaction_details = f"{description} {upi_id}".strip()

        ref_match = re.search(r"UPI Ref No:\s*(\d+)", transaction_blob, flags=re.IGNORECASE)
        ref_no = ref_match.group(1).strip() if ref_match else ""

        amount_match = re.search(r"([+-]\s*Rs\.\s*\d[\d,]*)", transaction_blob, flags=re.IGNORECASE)
        amount = amount_match.group(1).strip() if amount_match else ""

        rows.append([date_time, transaction_details, ref_no, amount])

    if not rows:
        logger.warning("No Paytm transactions parsed from file at %s", file_path)
        return None, "no transactions parsed"

    result_dict = {"headers": ["Date & Time", "Transaction Details", "UPI Ref No.", "Amount"], "rows": rows}
    clean_dict(result_dict)

    result = headers_to_dicts(result_dict)
    filename = get_filename(file_path)
    attach_filename(result, filename)
    return result

def parse_gpay(raw_text, file_path):
    """Parse Google Pay UPI transaction statement and extract transaction details.

    Args:
        raw_text (str): Raw text content extracted from the Google Pay PDF statement
        file_path (str): Path to the source PDF file for logging purposes
        
    Returns:
        list[dict]: A list of dictionaries representing parsed transactions with attached filenames on success. On failure, returns (None, str) with a reason string.
    """
    raw_blob = "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())

    header_pattern = re.compile(r"Transaction statement.*?Date&time Transactiondetails Amount", flags=re.IGNORECASE | re.DOTALL)
    cleaned_blob = re.sub(header_pattern, "", raw_blob)

    footer_pattern = re.compile(r"Note:.*?Page\d+of\d+", flags=re.IGNORECASE | re.DOTALL)
    cleaned_blob = re.sub(footer_pattern, "", cleaned_blob)

    lines = [line.strip() for line in cleaned_blob.splitlines() if line.strip()]

    transaction_blocks = []
    current_block = []
    date_pattern = re.compile(r"(\d{2}[A-Za-z]{3},\d{4})")
    end_pattern = re.compile(r"Paidby[A-Za-z]+")

    for line in lines:
        if date_pattern.search(line):
            if current_block:
                transaction_blocks.append(current_block)
            current_block = [line]
        elif current_block:
            current_block.append(line)
            if end_pattern.search(line):
                transaction_blocks.append(current_block)
                current_block = []

    if current_block:
        transaction_blocks.append(current_block)

    if not transaction_blocks:
        logger.warning("No GPay transactions found in file at %s", file_path)
        return None, "no transactions found"

    rows = []
    for transaction_lines in transaction_blocks:
        if not transaction_lines:
            continue

        first_line = transaction_lines[0]
        date_match = date_pattern.search(first_line)
        date_value = date_match.group(1).strip() if date_match else ""

        time_value = ""
        if len(transaction_lines) > 1:
            time_match = re.search(r"(\d{2}:\d{2}[AP]M)", transaction_lines[1], flags=re.IGNORECASE)
            time_value = time_match.group(1).strip() if time_match else ""

        if "Paidto" in first_line:
            transaction_type = "debit"
            label = "Paidto"
        elif "Receivedfrom" in first_line:
            transaction_type = "credit"
            label = "Receivedfrom"
        else:
            transaction_type = ""
            label = ""
            logger.warning("Unhandled GPay transaction type in %s: %s", file_path, first_line.strip())

        details_match = None
        if label:
            details_match = re.search(
                rf"{re.escape(label)}(.+?)(₹?[\d,]+\.?\d*)\s*$",
                first_line,
            )
            if details_match:
                transaction_details = details_match.group(1).strip()
                amount_value = details_match.group(2).strip()
            else:
                transaction_details = ""
                amount_value = ""
                logger.warning(
                    "Failed to extract details/amount from GPay line in %s: %s",
                    file_path,
                    first_line.strip(),
                )
        else:
            transaction_details = ""
            amount_value = ""

        upi_match = re.search(r"UPITransactionID:(\d+)", "\n".join(transaction_lines))
        upi_id = upi_match.group(1).strip() if upi_match else ""

        rows.append(
            [
                f"{date_value} {time_value}".strip(),
                transaction_details,
                upi_id,
                amount_value,
                transaction_type,
            ]
        )

    result_dict = {"headers": ["Date & Time", "Transaction Details", "UPI Transaction ID", "Amount", "Type"], "rows": rows}
    clean_dict(result_dict)

    result = headers_to_dicts(result_dict)
    filename = get_filename(file_path)
    attach_filename(result, filename)
    return result

def parse_phonepe(raw_text, file_path):
    """Parse PhonePe UPI transaction statement and extract transaction details.

    Args:
        raw_text (str): Raw text content extracted from the PhonePe PDF statement
        file_path (str): Path to the source PDF file for logging
        
    Returns:
        list[dict]: A list of dictionaries representing parsed transactions with attached filenames on success. On failure, returns (None, str) with a reason string.
    """
    raw_blob = "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())
    
    raw_blob = re.sub(r"([A-Za-z]{3})(\d{1,2},)", r"\1 \2", raw_blob) 
    raw_blob = re.sub(r"(\d{4})(\d{1,2}:\d{2})", r"\1 \2", raw_blob) 

    header_pattern = re.compile(
        r"Transaction Statement for.*?Date Transaction Details Type Amount",
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned_blob = re.sub(header_pattern, "", raw_blob)

    column_header_pattern = re.compile(r"Date Transaction Details Type Amount", flags=re.IGNORECASE)
    cleaned_blob = re.sub(column_header_pattern, "", cleaned_blob)

    footer_pattern = re.compile(
        r"Page\s+\d+\s+of\s+\d+.*?This is a system generated statement\. For any queries, contact us at ?https://support\.phonepe\.com/statement\.",
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned_blob = re.sub(footer_pattern, "", cleaned_blob)

    disclaimer_pattern = re.compile(r"This is an automatically generated statement.*$", flags=re.IGNORECASE | re.DOTALL)
    cleaned_blob = re.sub(disclaimer_pattern, "", cleaned_blob)

    lines = [line.strip() for line in cleaned_blob.splitlines() if line.strip()]

    date_pattern = re.compile(r"^([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\b")
    type_amount_pattern = re.compile(
        r"^([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s+(.*?)\s+(DEBIT|CREDIT)\s+(₹?[\d,]+\.?\d*)\s*$",
        flags=re.IGNORECASE,
    )
    end_pattern = re.compile(r"^(Paid by|Credited to)\b", flags=re.IGNORECASE)
    time_pattern = re.compile(r"^(\d{1,2}:\d{2}\s*[ap]m)\b", flags=re.IGNORECASE)

    transaction_blocks = []
    current_block = None

    for line in lines:
        if date_pattern.match(line):
            if current_block is not None:
                transaction_blocks.append(current_block)
            current_block = [line]
            continue

        if current_block is None:
            continue

        if end_pattern.match(line):
            current_block.append(line)
            transaction_blocks.append(current_block)
            current_block = None
            continue

        current_block.append(line)

    if current_block is not None:
        transaction_blocks.append(current_block)

    if not transaction_blocks:
        logger.warning("No PhonePe transactions found in file at %s", file_path)
        return None, "no transactions found"

    rows = []
    for transaction_lines in transaction_blocks:
        if not transaction_lines:
            continue

        first_line = transaction_lines[0]
        type_amount_match = type_amount_pattern.match(first_line)
        
        if not type_amount_match:
            logger.warning("Failed to extract type/amount from PhonePe line in %s: %s", file_path, first_line.strip())
            continue

        date_value = type_amount_match.group(1).strip()
        transaction_details = type_amount_match.group(2).strip()
        transaction_type = type_amount_match.group(3).lower()
        amount_value = type_amount_match.group(4).strip()

        time_value = ""
        if len(transaction_lines) > 1:
            time_line = transaction_lines[1].strip()
            time_match = time_pattern.match(time_line)
            if time_match:
                time_value = time_match.group(1).strip()
                remainder = time_line[time_match.end():].strip()
                if remainder and not remainder.lower().startswith("transaction id"):
                    if transaction_details:
                        transaction_details = f"{transaction_details} {remainder}"
                    else:
                        transaction_details = remainder

        utr_match = re.search(r"UTR No\.\s*(\d+)", "\n".join(transaction_lines), flags=re.IGNORECASE)
        utr_no = utr_match.group(1).strip() if utr_match else ""

        rows.append(
            [
                f"{date_value} {time_value}".strip(),
                transaction_details.strip(),
                utr_no,
                amount_value,
                transaction_type,
            ]
        )

    if not rows:
        logger.warning("No PhonePe transactions parsed from file at %s", file_path)
        return None, "no transactions parsed"

    result_dict = {"headers": ["Date & Time", "Transaction Details", "UTR No.", "Amount", "Type"], "rows": rows}

    clean_dict(result_dict)

    result = headers_to_dicts(result_dict)
    filename = get_filename(file_path)
    attach_filename(result, filename)
    return result

def parse_pdf(file_path, source_type):
    """Parse a PDF received from the user

    Args:
        file_path (string): path of the file stored
        source_type (string): Type of document - Bank statement/UPI transaction/Tradebook

    Returns:
        list[dict]: A list of structured dictionaries representing transaction records on success. On failure, returns (None, str) with a reason string.

    """
    if source_type == "Bank":
        try:
            pdf = pdfplumber.open(file_path)
        except PdfminerException as e:
            logger.warning(f"Unable to open PDF at {file_path}: {e}")
            raise

        with pdf:
            if len(pdf.pages) == 0:
                logger.warning(f"PDF at {file_path} has zero pages")
                return None, "pdf has zero pages"
            first_page = pdf.pages[0]
            tables = first_page.extract_tables()
            target = ["date", "dt."]
            result_dict = {"headers": [], "rows": []}
            if not tables:
                logger.warning(f"PDF at {file_path} does not have a table on the 1st Page")
                return None, "no table found on first page"
            for table in tables:
                headerRow = table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["headers"] = table[0]
                    result_dict["rows"].extend(table[1:])
                    break
            if not result_dict["headers"]:
                logger.warning(f"PDF at {file_path} does not have a Transaction Table on the 1st Page")
                return None, "no transaction table found on first page"

            total_pages = len(pdf.pages)
            for pageNumber in range(1, total_pages):
                page = pdf.pages[pageNumber]
                table = page.extract_table()
                if table is None:
                    logger.warning(f"PDF at {file_path} does not have a table on the page {pageNumber + 1}")
                    return None, f"no table found on page {pageNumber + 1}"
                headerRow = table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["rows"].extend(table[1:])
                else:
                    logger.warning(f"The file at {file_path} does not have a header row for page {pageNumber + 1}")
                    return None, f"no header row match on page {pageNumber + 1}"

            if not result_dict["rows"]:
                logger.warning(f"No Bank transactions parsed from file at {file_path}")
                return None, "no transactions parsed"
        
        logger.info(f"Data from PDF at {file_path} extracted successfully")
        clean_dict(result_dict)

        result = headers_to_dicts(result_dict)
        filename = get_filename(file_path)
        attach_filename(result, filename)
        return result

    if source_type == "UPI":
        try:
            pdf = pdfplumber.open(file_path)
        except PdfminerException as e:
            logger.warning(f"Unable to open PDF at {file_path}: {e}")
            raise

        with pdf:
            if len(pdf.pages) == 0:
                logger.warning(f"PDF at {file_path} has zero pages")
                return None, "pdf has zero pages"
            raw_text_parts = []
            for page in pdf.pages:
                extracted_text = page.extract_text() or ""
                raw_text_parts.append(extracted_text)
            raw_text = "\n".join(raw_text_parts)

            source = detect_upi_source(raw_text)
            if source == "paytm":
                return parse_paytm(raw_text, file_path)
            if source == "gpay":
                return parse_gpay(raw_text, file_path)
            if source == "phonepe":
                return parse_phonepe(raw_text, file_path)
            logger.warning("Unable to detect UPI source for %s", file_path)
            return None, "unable to detect UPI source"

    logger.warning(f"Unsupported source_type '{source_type}' for file {file_path}")
    return None, "unsupported source_type"


def parse_zerodha_tradebook(filepath: str) -> list[dict]:
    """Parse Zerodha tradebook CSV file and extract trade transaction details.

    Args:
        filepath (str): Path to the Zerodha tradebook CSV file for logging and ingestion

    Returns:
        list[dict]: A list of dictionaries representing individual trade records with sanitized fields on success. On failure, returns (None, str) with a reason string.
    """
    expected_columns = {
        "symbol",
        "isin",
        "trade_date",
        "exchange",
        "segment",
        "series",
        "trade_type",
        "auction",
        "quantity",
        "price",
        "trade_id",
        "order_id",
        "order_execution_time",
        "expiry_date",
    }
    try:
        df = pd.read_csv(filepath, dtype={"trade_id": str, "order_id": str})
    except (UnicodeDecodeError, ParserError) as e:
        logger.warning(f"Unable to read CSV at {filepath}: {e}")
        raise

    if set(df.columns) != expected_columns:
        logger.warning("file with expected headers not uploaded: %s", filepath)
        return None, "unexpected file headers"

    if df.shape[0] == 0:
        logger.warning("File is empty: %s", filepath)
        return None, "file is empty"

    filename = get_filename(filepath)
    rows = []

    for _, row in df.iterrows():
        row_dict = {
            "trade_date": row["trade_date"],
            "symbol": row["symbol"],
            "trade_type": row["trade_type"],
            "quantity": row["quantity"],
            "price": row["price"],
            "trade_id": row["trade_id"],
            "isin": row["isin"],
            "exchange": row["exchange"],
            "series": row["series"],
            "segment": row["segment"],
            "auction": row["auction"],
            "order_id": row["order_id"],
            "order_execution_time": row["order_execution_time"],
            "Filename": filename,
        }

        for key, value in row_dict.items():
            if pd.isna(value):
                row_dict[key] = None

        rows.append(row_dict)

    if not rows:
        logger.warning("No Zerodha tradebook rows parsed from file at %s", filepath)
        return None, "no rows parsed"

    return rows
    