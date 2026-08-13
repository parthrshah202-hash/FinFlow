import logging

def get_logger() -> logging.Logger:
    logging.basicConfig(
            filename="logs/pipeline.log",
            format='%(asctime)s %(levelname)s: %(message)s',
            filemode='w',
        )
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    return logger