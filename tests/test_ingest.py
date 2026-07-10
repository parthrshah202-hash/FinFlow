from src.ingest import detect_upi_source, parse_paytm


def test_detect_upi_source_detects_paytm_marker():
    raw_text = """
    Some header
    UPI Ref No
    More text
    """
    assert detect_upi_source(raw_text) == "paytm"


def test_parse_paytm_extracts_transaction_fields():
    raw_text = """
    Paytm Statement
    25 NOV'25 - 24 DEC'25
    Date &
    Transaction Details Notes & Tags Your Account Amount
    Time
    24 Dec
    3:36 PM
    Money sent to Vikas Dairu Note: CH202512241 India Post - Rs.300
    UPI ID: 6376905909@ikwik 5362109636 Payment
    UPI Ref No: 535856956952 Tag: Bank - 04
    # Money Transfer
    """

    result = parse_paytm(raw_text, "sample.pdf")

    assert result is not None
    assert result["headers"] == ["Date & Time", "Transaction Details", "UPI Ref No.", "Amount"]
    assert result["rows"][0][0] == "24 Dec 2025 3:36 PM"
    assert result["rows"][0][1] == "Money sent to Vikas Dairu 6376905909@ikwik"
    assert result["rows"][0][2] == "535856956952"
    assert result["rows"][0][3] == "- Rs.300"
