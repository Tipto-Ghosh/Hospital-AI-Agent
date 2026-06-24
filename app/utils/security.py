"""
Input sanitization and prompt-injection detection.
 
These are defensive, best-effort layers: they reduce the surface area
for malicious input reaching the LLM or being stored verbatim, but they
are NOT a substitute for the structural defenses already in place
elsewhere in this codebase (parameterized queries via SQLAlchemy,
ContextVar-scoped patient_id rather than LLM-supplied patient_id,
explicit confirmation before any write, etc.).
 
sanitize_input is applied to raw patient message text at the API
boundary (app/api/middleware.py / app/api/routes/chat.py) before the
text enters LangGraph state. check_for_injection is a separate,
non-mutating scan used to FLAG suspicious input for logging/monitoring
- it does not block the message outright, since legitimate patient
messages can occasionally contain phrases that superficially resemble
injection attempts (e.g. a patient pasting instructions a doctor gave
them).
"""

import re
import unicodedata
from app.logger import logging

logger = logging.get_logger(__name__)

_SUSPICIOUS_UNICODE_CHARS: list[str] = [
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u202a",  # left-to-right embedding
    "\u202b",  # right-to-left embedding
    "\u202c",  # pop directional formatting
    "\u202d",  # left-to-right override
    "\u202e",  # right-to-left override
    "\ufeff",  # zero-width no-break space / BOM
]

# Matches any HTML/XML-like tag, e.g. <script>, </div>, <br/>.
_HTML_TAG_PATTERN = re.compile(r"<[^>]*>")

# common prompt injection patterns.
_INJECTION_PATTERNS: list[str] = [
    "ignore previous instructions",
    "ignore the previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "disregard the above",
    "forget everything above",
    "forget your instructions",
    "you are now",
    "act as if",
    "pretend you are",
    "new instructions:",
    "system prompt",
    "reveal your prompt",
    "reveal your instructions",
    "what is your system prompt",
    "print your instructions",
    "override your guidelines",
    "bypass your safety",
    "jailbreak",
    "developer mode",
    "do anything now",
    "dan mode",
]

_INJECTION_PATTERN_RE = re.compile(
    "|".join(re.escape(p) for p in _INJECTION_PATTERNS),
    re.IGNORECASE,
)

def sanitize_input(text: str, max_length: int = 4000) -> str:
    """Sanitize patient input by removing suspicious Unicode characters and HTML tags."""
    if not text:
        return ""
 
    normalized = unicodedata.normalize("NFKC", text)
    for char in _SUSPICIOUS_UNICODE_CHARS:
        normalized = normalized.replace(char, "")
    
    without_tags = _HTML_TAG_PATTERN.sub("", normalized)
    cleaned_chars = []
    
    for char in without_tags:
        if char in ("\t", "\n", "\r"):
            cleaned_chars.append(char)
            continue
        category = unicodedata.category(char)
        if category in ("Cc", "Cf"):
            continue
        cleaned_chars.append(char)
    without_control_chars = "".join(cleaned_chars)
 
    collapsed = re.sub(r"[ \t]+", " ", without_control_chars)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    trimmed = collapsed.strip()
 
    if len(trimmed) > max_length:
        logger.warning(f"sanitize_input: input truncated from {len(trimmed)} to {max_length} characters")
        trimmed = trimmed[:max_length]
 
    return trimmed

def check_for_injection(text: str) -> bool:
    """
    Scan text for common prompt-injection phrasings.
 
    This is a detection signal, not a filter - it does not modify or
    block the input. Callers (typically API middleware or the
    supervisor node) decide what to do with a True result, such as
    logging a security event or routing to stricter handling.
 
    Parameters
    ----------
    text   The text to scan (typically already passed through
           sanitize_input).
 
    Returns
    -------
    True if any known injection phrase is found (case-insensitive
    substring match), False otherwise. Never raises - empty or
    None-like input returns False.
    """
    if not text:
        return False
 
    matched = _INJECTION_PATTERN_RE.search(text)
    if matched:
        logger.warning(f"check_for_injection: suspicious pattern matched: {matched.group(0)!r}")
        return True
    
    return False