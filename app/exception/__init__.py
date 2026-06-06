import sys
from typing import Any, Optional

from app.logger import logger


def error_message_detail(error_message: str, error_detail: Optional[Any] = None) -> str:
    """Create a detailed error message.

    Supports two modes:
    1. If error_detail is a plain string, it is appended directly.
    2. If error_detail is the ``sys`` module (or any object with an ``exc_info()``
       method), the current exception traceback is extracted.
    """
    if error_detail is None:
        return f"Error occurred with message [{error_message}]"

    # Plain string detail – just append it
    if isinstance(error_detail, str):
        return f"Error occurred with message [{error_message}] | Detail: {error_detail}"

    # Try sys.exc_info() style (tuple of (type, value, traceback))
    try:
        if hasattr(error_detail, "exc_info"):
            _, _, exc_tb = error_detail.exc_info()
            if exc_tb is not None:
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                return (
                    f"Error occurred in script [{file_name}] at line [{line_number}] "
                    f"with message [{error_message}]"
                )
        # Fallback: if it's a tuple directly (type, value, traceback)
        elif isinstance(error_detail, tuple) and len(error_detail) == 3:
            exc_tb = error_detail[2]
            if exc_tb is not None:
                file_name = exc_tb.tb_frame.f_code.co_filename
                line_number = exc_tb.tb_lineno
                return (
                    f"Error occurred in script [{file_name}] at line [{line_number}] "
                    f"with message [{error_message}]"
                )
    except Exception:
        pass

    # Last resort: use the string representation of the detail
    return f"Error occurred with message [{error_message}] | Detail: {str(error_detail)}"


class CustomException(Exception):
    def __init__(self, error_message: str, error_detail: Optional[Any] = None):
        super().__init__(error_message)
        self.error_message = error_message_detail(
            error_message=error_message,
            error_detail=error_detail,
        )
        logger.error(self.error_message, exc_info=True)

    def __str__(self) -> str:
        return self.error_message