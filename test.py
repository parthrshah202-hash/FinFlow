
from src.load import get_engine, fetch_prototype_embeddings
from src.mapper import map_headers

engine = get_engine()
prototype_embeddings = fetch_prototype_embeddings(engine)
print(f"Loaded {len(prototype_embeddings)} prototype rows")

headers = [
    "Narration",
    "Value Date",
    "Withdrawal Amt.",
    "Type",
    "price",
    "quantity",
    "Balance",
    "isin",
    "DATE",
    "NARRATION",
    "CHQ.NO.",
    "WITHDRAWAL(DR)",
    "DEPOSIT(CR)",
    "BALANCE",
    "TXN Date",
    "Description",
    "ReferenceNo/ChequeNo",
    "Debit",
    "Credit",
    "Date",
    "Instr No",
    "Particulars",
    "Debits",
    "Credits",
    "Txn Date",
    " Ref No./ChequeNo.",
    "Narration ",
    "Chq./Ref.No. ",
    "Value Dt ",
    " Deposit Amt. ",
    "Closing Balance",
    "S No.",
    "Transaction Date",
    "Cheque Number",
    "Transaction Remarks",
    "WithdrawalAmount (INR)",
    "DepositAmount (INR)",
    "Balance(INR)",
    "Date & time",
    "Transaction details",
    " Amount",
    "Transaction Details",
    "Amount",
    "Date & Time",
    " Notes & Tags",
    " Your Account",
    "symbol",
    "trade_date",
    " exchange",
    " segment",
    " series ",
    "trade_type",
    " auction",
    "price",
    "trade_id",
    " order_id",
    " order_execution_time",
    " expiry_date",
]
results = map_headers(headers, prototype_embeddings)
for r in results:
    print(r)

