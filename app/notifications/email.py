from app.logger import logging

logger = logging.getLogger(__name__)


def send(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> bool:
    """
    Send an email to `to_address`.

    This is a stub implementation. To activate real email delivery,
    replace the body below with an SMTP/SendGrid integration (see
    Section 4.4 of the architecture plan). The function contract is:

      - Returns True on successful dispatch or queue.
      - Returns False on any delivery failure (never raises).
      - `to_address` is the recipient's email address.
      - `subject` is the email subject line.
      - `body_text` is the plain-text fallback body.
      - `body_html` is an optional HTML body (None → text only).

    Called by Celery tasks in app/notifications/tasks.py — runs inside
    a worker process, not in the FastAPI request/response cycle.
    """
    logger.info(
        f"email.send (stub): to={to_address} subject={subject!r} "
        f"body_length={len(body_text)} has_html={body_html is not None}"
    )
    return True