import logging
import re
import pdfplumber

logger = logging.getLogger()

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
        result_dict["headers"][index] = header.replace("\n", " ")

    for row_idx, row in enumerate(result_dict["rows"]):
        for cell_idx, cell in enumerate(row):
            if cell is None:
                cell = ""
            result_dict["rows"][row_idx][cell_idx] = cell.replace("\n", " ")


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
        if "UPI Transaction ID" in normalized:
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
        dict: A dictionary with structure {"headers": [...], "rows": [...]} containing
              parsed transactions, or None if parsing fails
    """
    period_pattern = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})'?(\d{2})\s*-\s*(\d{1,2})\s+([A-Za-z]{3})'?(\d{2})")
    period_match = period_pattern.search(raw_text)

    if not period_match:
        logger.warning("No statement period found in Paytm file at %s", file_path)
        return None

    start_day, start_month, start_year_raw, end_day, end_month, end_year_raw = period_match.groups()
    start_year = int(start_year_raw) if len(start_year_raw) == 4 else (2000 + int(start_year_raw))
    end_year = int(end_year_raw) if len(end_year_raw) == 4 else (2000 + int(end_year_raw))

    if start_year != end_year:
        logger.warning(
            "Paytm statement year mismatch for %s: start year %s, end year %s",
            file_path, start_year, end_year,
        )
        return None

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
        return None

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
        return None

    result_dict = {"headers": ["Date & Time", "Transaction Details", "UPI Ref No.", "Amount"], "rows": rows}
    clean_dict(result_dict)
    
    return result_dict


def parse_pdf(file_path, source_type):
    """Parse a PDF received from the user

    Args:
        file_path (string): path of the file stored
        source_type (string): Type of document - Bank statement/UPI transaction/Tradebook

    Returns:
        dict: A dictionary of structure {"headers": [...], "rows": [...]}

    """
    if source_type == "Bank":
        with pdfplumber.open(file_path) as pdf:
            first_page = pdf.pages[0]
            tables = first_page.extract_tables()
            target = ["date", "dt."]
            result_dict = {"headers": [], "rows": []}
            if not tables:
                logger.warning(f"PDF at {file_path} does not have a table on the 1st Page")
                return None
            for table in tables:
                headerRow = table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["headers"] = table[0]
                    result_dict["rows"].extend(table[1:])
                    break
            if not result_dict["headers"]:
                logger.warning(f"PDF at {file_path} does not have a Transaction Table on the 1st Page")
                return None

            total_pages = len(pdf.pages)
            for pageNumber in range(1, total_pages):
                page = pdf.pages[pageNumber]
                table = page.extract_table()
                if table is None:
                    logger.warning(f"PDF at {file_path} does not have a table on the page {pageNumber + 1}")
                    return None
                headerRow = table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["rows"].extend(table[1:])
                else:
                    logger.warning(f"The file at {file_path} does not have a header row for page {pageNumber + 1}")
                    return None

        logger.info(f"Data from PDF at {file_path} extracted successfully")
        clean_dict(result_dict)
        return result_dict

    if source_type == "UPI":
        with pdfplumber.open(file_path) as pdf:
            raw_text_parts = []
            for page in pdf.pages:
                extracted_text = page.extract_text() or ""
                raw_text_parts.append(extracted_text)
            raw_text = "\n".join(raw_text_parts)

            source = detect_upi_source(raw_text)
            if source == "paytm":
                return parse_paytm(raw_text, file_path)
            if source in {"gpay", "phonepe"}:
                logger.warning("UPI source %s is not yet implemented for %s", source, file_path)
                return None
            logger.warning("Unable to detect UPI source for %s", file_path)
            return None

    return None


if __name__ == "__main__":
    # result=parse_pdf(r"C:\FinFlow\data\BankStatements\BS7-SBI_redact.pdf","Bank")
    result = parse_pdf(r"C:\FinFlow\data\UPIExports\UPI5_PAYTM_redact.pdf", "UPI")
    print(result)