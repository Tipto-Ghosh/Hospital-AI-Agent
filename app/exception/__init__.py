import sys
from app.logger import logger

def error_message_detail(error, error_details: sys) -> str:
    """Create a detailed error message with file name, line number, and message."""
    _, _, exc_tb = error_details.exc_info()
    if exc_tb is None:
        return f"Error occurred with message [{str(error)}]"

    file_name = exc_tb.tb_frame.f_code.co_filename
    line_number = exc_tb.tb_lineno

    return (
        f"Error occurred in python script name [{file_name}] at line: [{line_number}] "
        f"with error message [{str(error)}]"
    )


class CustomException(Exception):
    def __init__(self, error_message, error_detail):
        super().__init__(error_message)
        self.error_message = error_message_detail(
            error=error_message,
            error_details=error_detail,
        )
        logger.error(self.error_message, exc_info=True)

    def __str__(self) -> str:
        return self.error_message