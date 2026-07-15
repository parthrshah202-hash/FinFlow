from src.ingest import parse_gpay


def test_parse_gpay_extracts_normal_row():
    raw_text = """
    Transaction statement
    ,
    Transaction statement period Sent Received
    01December2025-31May2026 ₹1,76,115.15 ₹1,58,943
    Date&time Transactiondetails Amount
    01Dec,2025 PaidtoRANKHAMBMAHESH PRAKASH ₹2,250
    12:31PM UPITransactionID:570103596583
    PaidbyUnionBankofIndia0070
    """

    result = parse_gpay(raw_text, "sample.pdf")

    assert result is not None
    assert result["rows"][0][1] == "RANKHAMBMAHESH PRAKASH"
    assert result["rows"][0][2] == "570103596583"
    assert result["rows"][0][3] == "₹2,250"
    assert result["rows"][0][4] == "debit"


def test_parse_gpay_keeps_embedded_phone_number_in_details():
    raw_text = """
    Transaction statement
    ,
    Transaction statement period Sent Received
    01December2025-31May2026 ₹1,76,115.15 ₹1,58,943
    Date&time Transactiondetails Amount
    09May,2026 ReceivedfromMr MUFFADAL IQBAL TINWALA 9028996752 ₹200
    10:22AM UPITransactionID:433898330876
    PaidbyUnionBankofIndia0070
    """

    result = parse_gpay(raw_text, "sample.pdf")

    assert result is not None
    assert result["rows"][0][1] == "Mr MUFFADAL IQBAL TINWALA 9028996752"
    assert result["rows"][0][2] == "433898330876"
    assert result["rows"][0][3] == "₹200"
    assert result["rows"][0][4] == "credit"
