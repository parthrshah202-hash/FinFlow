from src.load import get_engine, create_table, insert_data

engine = get_engine()
create_table(engine)

# now check pgAdmin4: does raw_uploads exist under finflow_dev -> Schemas -> public -> Tables?

# Case 1: normal insert
insert_data([{"date": "2024-01-01", "amount": 500}], engine, "test_file.csv", "bank_pdf")
# check pgAdmin4 -> right-click raw_uploads -> View/Edit Data -> All Rows
# does the row show up with raw_data as the JSON blob you'd expect?

# Case 2: the edge case we still owe an answer to
insert_data([], engine, "empty_test.csv", "bank_pdf")
# does this throw, or silently no-op? which one happened?