import pdfplumber
import logging

logger=logging.getLogger()

def clean_dict(result_dict):
    """Clean the extracted result dict in place

    Args:
        result_dict (dictionary): The raw extracted dictionary
        
    Returns:
        None
    """
    for index,header in enumerate(result_dict["headers"]):
        if header is None:
            header=''
        result_dict["headers"][index]=header.replace("\n"," ")
        
    for row_idx, row in enumerate(result_dict["rows"]):
        for cell_idx, cell in enumerate(row):
            if cell is None:
                cell=''
            result_dict["rows"][row_idx][cell_idx] = cell.replace("\n", " ")


def parse_pdf(file_path,source_type):
    """Parse a PDF received from the user

    Args:
        file_path (string): path of the file stored
        source_type (string): Type of document - Bank statement/UPI transaction/Tradebook
        
    Returns:
        dict: A dictionary of structure {"headers": [...], "rows": [...]}

    """
    if source_type=="Bank":
        with pdfplumber.open(file_path) as pdf:
            first_page=pdf.pages[0]
            tables=first_page.extract_tables()
            target=["date","dt."]
            result_dict = {"headers": [], "rows": []}
            if not tables:
                logger.warning(f"PDF at {file_path} does not have a table on the 1st Page")
                return None
            for table in tables:
                headerRow=table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["headers"] = table[0]
                    result_dict["rows"].extend(table[1:])
                    break
            if not result_dict["headers"]:
                logger.warning(f"PDF at {file_path} does not have a Transaction Table on the 1st Page")
                return None
                
            total_pages=len(pdf.pages)
            for pageNumber in range(1,total_pages):
                page=pdf.pages[pageNumber]
                table=page.extract_table()
                if table is None:
                    logger.warning(f"PDF at {file_path} does not have a table on the page {pageNumber+1}")
                    return None
                headerRow=table[0]
                has_match = any(sub in cell.lower() for cell in headerRow if cell is not None for sub in target)
                if has_match:
                    result_dict["rows"].extend(table[1:])
                else:
                    logger.warning(f"The file at {file_path} does not have a header row for page {pageNumber+1}")
                    return None
        
        logger.info(f"Data from PDF at {file_path} extracted successfully")
        clean_dict(result_dict)
        return result_dict
    
if __name__=="__main__":
    result=parse_pdf("C:\FinFlow\data\BankStatements\BS7-SBI_redact.pdf","Bank")
    print(result)