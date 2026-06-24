""" 
Cross-cutting utility tools available to every agent.

get_current_datetime exists specifically so agents never hardcode a
"today" or "now" value - LLMs have a training cutoff and no innate
sense of the actual current date/time, so any agent reasoning about
"tomorrow", "this Friday", or "is this appointment in the past" must
call this tool rather than guessing from its own training data.
 
validate_date_format normalizes whatever date string a patient or LLM
produces into a strict ISO 8601 date, so downstream repository calls
(which all expect date.fromisoformat()-compatible strings) never choke
on ambiguous formats like "11/05/2024" or "5 Nov 2024".
"""

from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Optional
from langchain_core.tools import tool
from pydantic import BaseModel
from app.logger import logging

logger = logging.get_logger(__name__)

class CurrentDateTimeResult(BaseModel):
    """The current date and time, in multiple convenient forms."""
    iso_datetime: str  # full ISO 8601 datetime
    iso_date: str       # just the date portion
    day_of_week: str    # e.g. "Thursday"
    timezone: str = "UTC"

class DateValidationResult(BaseModel):
    """The result of validating and normalizing a date string."""
    valid: bool
    normalized_date: Optional[str] = None
    error: Optional[str] = None

# Accepted input formats for validate_date_format, tried in order.
# ISO format is attempted first via date.fromisoformat() (fast path);
# these cover the most common alternate formats a patient might type.
_ACCEPTED_DATE_FORMATS: list[str] = [
    "%Y-%m-%d",   # 2024-11-05
    "%d-%m-%Y",   # 05-11-2024
    "%d/%m/%Y",   # 05/11/2024
    "%m/%d/%Y",   # 11/05/2024
    "%d %B %Y",   # 5 November 2024
    "%d %b %Y",   # 5 Nov 2024
    "%B %d, %Y",  # November 5, 2024
    "%b %d, %Y",  # Nov 5, 2024
]

@tool
async def get_current_datetime() -> CurrentDateTimeResult:
    """
    Get the current date and time (UTC).
 
    Agents must call this tool instead of assuming or hardcoding
    "today's date" - an LLM's training data has a fixed cutoff and does
    not reflect the actual current date. Always call this before
    resolving relative date references like "tomorrow", "next Friday",
    or "in two weeks".
 
    Returns
    -------
    CurrentDateTimeResult with the current datetime in ISO 8601 format,
    the date portion alone, and the day of the week.
    """
    now = datetime.now(timezone.utc)
    result = CurrentDateTimeResult(
        iso_datetime=now.isoformat(),
        iso_date=now.date().isoformat(),
        day_of_week=now.strftime("%A"),
    )
    logger.info(f"get_current_datetime() -> {result.iso_datetime}")
    return result

@tool
async def validate_date_format(date_str: str) -> DateValidationResult:
    """
    Validate and normalize a date string into ISO 8601 (YYYY-MM-DD).
 
    Accepts several common alternate formats (DD-MM-YYYY, DD/MM/YYYY,
    MM/DD/YYYY, "5 November 2024", "Nov 5, 2024", etc.) in addition to
    ISO format itself, and normalizes any of them to YYYY-MM-DD.
 
    Parameters
    ----------
    date_str   The date string to validate, in any of the accepted formats.
 
    Returns
    -------
    DateValidationResult with valid=true and normalized_date set on
    success, or valid=false and an error message on failure. Never
    raises - malformed input always produces a result with
    valid=false rather than an exception.
    """
    cleaned = date_str.strip()
 
    if not cleaned:
        return DateValidationResult(valid=False, error="Date string is empty.")
 
    try:
        parsed = date.fromisoformat(cleaned)
        logger.info(f"validate_date_format({date_str!r}) -> valid (ISO fast path): {parsed.isoformat()}")
        return DateValidationResult(valid=True, normalized_date=parsed.isoformat())
    except ValueError:
        pass
 
    for fmt in _ACCEPTED_DATE_FORMATS:
        try:
            parsed_dt = datetime.strptime(cleaned, fmt)
            normalized = parsed_dt.date().isoformat()
            logger.info(f"validate_date_format({date_str!r}) -> valid (format={fmt!r}): {normalized}")
            return DateValidationResult(valid=True, normalized_date=normalized)
        except ValueError:
            continue
 
    logger.info(f"validate_date_format({date_str!r}) -> invalid, no matching format")
    return DateValidationResult(
        valid=False,
        error=f"Could not parse {date_str!r} as a date. Please use YYYY-MM-DD format.",
    )
 

utility_tools = [get_current_datetime, validate_date_format]