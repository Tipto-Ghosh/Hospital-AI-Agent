import logging
import os
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger("HospitalAI")

def setup_logger():
    """Explicitly initializes the logging configuration when called."""
    # Check if handlers already exist to prevent duplicate setups
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    logs_dir = os.path.join(ROOT_DIR, "logs")
    os.makedirs(logs_dir, exist_ok = True)

    LOG_FILE = f"app_{datetime.now().strftime('%Y_%m_%d_%H_%M')}.log"
    LOG_FILE_PATH = os.path.join(logs_dir, LOG_FILE)

    log_format = "[%(asctime)s] Line: %(lineno)d | %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        filename=LOG_FILE_PATH,
        filemode='a', 
        format=log_format,
        datefmt=date_format,
        level=logging.INFO
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)