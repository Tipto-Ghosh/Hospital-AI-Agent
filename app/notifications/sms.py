from app.logger import logging 
logger = logging.getLogger(__name__)

def send(phone: str, message: str) -> bool:
    """
    Send an SMS message to the specified phone number.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content to be sent.

    Returns:
        bool: True if the message was sent successfully, False otherwise.
    """
    # Note: This is a stub implementation for now. 
    logger.info(f"sms.send (stub): to={phone}, message={message!r}")
    return True