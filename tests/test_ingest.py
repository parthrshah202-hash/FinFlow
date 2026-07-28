import os
import sys
from pathlib import Path
import pandas as pd
import pdfplumber
import pytest
from pypdf import PdfWriter
from pdfplumber.utils.exceptions import PdfminerException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest import (
    detect_upi_source,
    parse_gpay,
    parse_paytm,
    parse_pdf,
    parse_phonepe,
    parse_zerodha_tradebook,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gpay_pdf_path() -> Path:
    return PROJECT_ROOT / "data" / "UPIExports" / "UPI1-GPAY_redact.pdf"


@pytest.fixture
def phonepe_pdf_path() -> Path:
    return PROJECT_ROOT / "data" / "UPIExports" / "UPI2-PHONEPE_redact.pdf"


@pytest.fixture
def paytm_pdf_path() -> Path:
    return PROJECT_ROOT / "data" / "UPIExports" / "UPI5_PAYTM_redact.pdf"


@pytest.fixture
def bank_pdf_path() -> Path:
    return PROJECT_ROOT / "data" / "BankStatements" / "BS7-SBI_redact.pdf"


@pytest.fixture
def zerodha_csv_path() -> Path:
    return PROJECT_ROOT / "data" / "TradeBook" / "TradeBook1-Zeroda_redact.csv"


@pytest.fixture
def gpay_raw_text(gpay_pdf_path: Path) -> str:
    with pdfplumber.open(gpay_pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@pytest.fixture
def phonepe_raw_text(phonepe_pdf_path: Path) -> str:
    with pdfplumber.open(phonepe_pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@pytest.fixture
def paytm_raw_text(paytm_pdf_path: Path) -> str:
    with pdfplumber.open(paytm_pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@pytest.fixture
def zero_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "zero_pages.pdf"
    writer = PdfWriter()
    with path.open("wb") as fh:
        writer.write(fh)
    return path


@pytest.fixture
def corrupt_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a pdf at all")
    return path


@pytest.fixture
def wrong_columns_csv(tmp_path: Path) -> Path:
    path = tmp_path / "wrong_columns.csv"
    pd.DataFrame({"wrong": [1], "headers": [2]}).to_csv(path, index=False)
    return path


@pytest.fixture
def empty_zerodha_csv(tmp_path: Path) -> Path:
    path = tmp_path / "empty.csv"
    df = pd.DataFrame(
        {
            "symbol": [],
            "isin": [],
            "trade_date": [],
            "exchange": [],
            "segment": [],
            "series": [],
            "trade_type": [],
            "auction": [],
            "quantity": [],
            "price": [],
            "trade_id": [],
            "order_id": [],
            "order_execution_time": [],
            "expiry_date": [],
        }
    )
    df.to_csv(path, index=False)
    return path


def test_detect_upi_source_gpay_phonepe_paytm(gpay_raw_text: str, phonepe_raw_text: str, paytm_raw_text: str) -> None:
    assert detect_upi_source(gpay_raw_text) == "gpay"
    assert detect_upi_source(phonepe_raw_text) == "phonepe"
    assert detect_upi_source(paytm_raw_text) == "paytm"


def test_detect_upi_source_unrecognized() -> None:
    assert detect_upi_source("some unrelated statement text") is None


def test_parse_paytm_golden_path(paytm_raw_text: str, paytm_pdf_path: Path) -> None:
    result = parse_paytm(paytm_raw_text, str(paytm_pdf_path))
    assert isinstance(result, list)
    assert result
    assert all("Filename" in row for row in result)
    assert all(row["Filename"] == paytm_pdf_path.name for row in result)
    assert any(row.get("UPI Ref No.") for row in result)
    assert any(row.get("Amount") for row in result)


def test_parse_paytm_year_mismatch() -> None:
    raw_text = "Statement period 01 Jan'22 - 31 Dec'23"
    assert parse_paytm(raw_text, "dummy.pdf") == (None, "statement year mismatch")


def test_parse_paytm_no_period_found() -> None:
    raw_text = "No period details available here"
    assert parse_paytm(raw_text, "dummy.pdf") == (None, "no statement period found")


def test_parse_gpay_golden_path(gpay_raw_text: str, gpay_pdf_path: Path) -> None:
    result = parse_gpay(gpay_raw_text, str(gpay_pdf_path))
    assert isinstance(result, list)
    assert result
    assert all("Filename" in row for row in result)
    assert all(row["Filename"] == gpay_pdf_path.name for row in result)
    assert any(row.get("Type") in {"debit", "credit"} for row in result)


def test_parse_gpay_unrecognized_transaction_type() -> None:
    raw_text = "31Jan,2024 10:00AM Some transaction details 100"
    result = parse_gpay(raw_text, "dummy.pdf")
    assert isinstance(result, list)
    assert result
    assert result[0]["Type"] == ""


def test_parse_phonepe_golden_path(phonepe_raw_text: str, phonepe_pdf_path: Path) -> None:
    result = parse_phonepe(phonepe_raw_text, str(phonepe_pdf_path))
    assert isinstance(result, list)
    assert result
    assert all("Filename" in row for row in result)
    assert all(row["Filename"] == phonepe_pdf_path.name for row in result)
    assert any(row.get("UTR No.") for row in result)


def test_parse_phonepe_no_transactions_found() -> None:
    raw_text = "No transaction lines here at all"
    assert parse_phonepe(raw_text, "dummy.pdf") == (None, "no transactions found")


def test_parse_pdf_bank_golden_path(bank_pdf_path: Path) -> None:
    result = parse_pdf(str(bank_pdf_path), "Bank")
    assert isinstance(result, list)
    assert result
    assert all("Filename" in row for row in result)
    assert all(row["Filename"] == bank_pdf_path.name for row in result)


def test_parse_pdf_zero_pages_bank(zero_page_pdf: Path) -> None:
    assert parse_pdf(str(zero_page_pdf), "Bank") == (None, "pdf has zero pages")


def test_parse_pdf_zero_pages_upi(zero_page_pdf: Path) -> None:
    assert parse_pdf(str(zero_page_pdf), "UPI") == (None, "pdf has zero pages")


def test_parse_pdf_unsupported_source_type(bank_pdf_path: Path) -> None:
    assert parse_pdf(str(bank_pdf_path), "Tradebook") == (None, "unsupported source_type")


def test_parse_pdf_corrupt_file_raises(corrupt_pdf: Path) -> None:
    with pytest.raises(PdfminerException):
        parse_pdf(str(corrupt_pdf), "Bank")


def test_parse_pdf_upi_dispatches_correctly(gpay_pdf_path: Path, gpay_raw_text: str) -> None:
    direct = parse_gpay(gpay_raw_text, str(gpay_pdf_path))
    dispatched = parse_pdf(str(gpay_pdf_path), "UPI")
    assert isinstance(dispatched, list)
    assert dispatched == direct


def test_parse_zerodha_golden_path(zerodha_csv_path: Path) -> None:
    result = parse_zerodha_tradebook(str(zerodha_csv_path))
    assert isinstance(result, list)
    assert result
    assert all("Filename" in row for row in result)
    assert all(row["Filename"] == zerodha_csv_path.name for row in result)
    for row in result:
        assert all(value is None or not pd.isna(value) for value in row.values())


def test_parse_zerodha_wrong_columns(wrong_columns_csv: Path) -> None:
    assert parse_zerodha_tradebook(str(wrong_columns_csv)) == (None, "unexpected file headers")


def test_parse_zerodha_empty_file(empty_zerodha_csv: Path) -> None:
    assert parse_zerodha_tradebook(str(empty_zerodha_csv)) == (None, "file is empty")
