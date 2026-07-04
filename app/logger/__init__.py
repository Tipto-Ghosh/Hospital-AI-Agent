import logging
import os
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger("HospitalAI")

def setup_logger(log_to_file: bool = os.getenv("LOG_TO_FILE", "True").lower() == "true"):
    """Explicitly initializes the logging configuration when called."""
    # Check if handlers already exist to prevent duplicate setups
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    log_format = "[%(asctime)s] Line: %(lineno)d | %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # add a console handler 
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root_logger.addHandler(console_handler)
    
    
    # add a file handler
    if log_to_file:
        log_dir = os.path.join(ROOT_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        LOG_FILE = f"app_{datetime.now().strftime('%Y_%m_%d_%H_%M')}.log"
        LOG_FILE_PATH = os.path.join(log_dir, LOG_FILE)
        
        file_handler = logging.FileHandler(LOG_FILE_PATH , mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        root_logger.addHandler(file_handler)
        root_logger.setLevel(logging.INFO)