import logging
from datetime import datetime
from pathlib import Path


class Logger:
    def __init__(self) -> None:
        root_dir = Path(__file__).resolve().parents[2]
        logs_dir = root_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        log_file = f"{datetime.now().strftime('%m_%d_%Y_%H_%M_%S')}.log"
        log_file_path = logs_dir / log_file

        log_format = "[%(asctime)s] Line: %(lineno)d | %(name)s - %(levelname)s - %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"

        logging.basicConfig(
            filename=str(log_file_path),
            format=log_format,
            datefmt=date_format,
            level=logging.INFO,
        )

        self.logger = logging.getLogger("multi-agent-ai-system")
        self.logger.setLevel(logging.INFO)

    def get_logger(self) -> logging.Logger:
        return self.logger


logger = Logger().get_logger()