"""Input normalisation, injection block, redaction, numeric guard (plan 8.5)."""
from __future__ import annotations
import re, unicodedata
BLOCK_MESSAGE = "That request was blocked by the input policy. Ask about RTO, replication, progress, approvals or the next step."
CONSOLE_HELP = ("I am a read-only status console. Ask about: RTO, replication, progress, approvals, or the next step. "
                "To run or change anything, use the approval workflow on the Runbook tab.")
_INVIS = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_BLOCK = re.compile("|".join([
    r"ignore (all |the )?(previous|above|prior) (instructions|rules)", r"system prompt", r"developer mode", r"jailbreak",
    r"(reveal|show|print|leak).{0,30}(key|secret|token|password|credential)", r"<\s*script", r"javascript:",
    r"union\s+select", r"drop\s+table", r"'\s*or\s*'1'\s*=\s*'1", r";\s*--", r"you are now", r"disregard .{0,20}instructions"]), re.I)
_REDACT = [(re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "[REDACTED_GOOGLE_KEY]"), (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[REDACTED_KEY]"),
           (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
           (re.compile(r"APR-[0-9A-F]{8}"), "APR-[REDACTED]"), (re.compile(r"RBK-[0-9A-F]{8}"), "RBK-[REDACTED]")]
def normalise(text) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = _CTRL.sub(" ", _INVIS.sub("", t))
    return re.sub(r"\s+", " ", t).strip()
def validate_input(text) -> str:
    """Normalise first, then match. Raises ValueError (policy block) or returns the cleaned text."""
    t = normalise(text)
    if not 1 <= len(t) <= 1000 or _BLOCK.search(t):
        raise ValueError(BLOCK_MESSAGE)
    return t
def redact(text) -> str:
    t = str(text)
    for rx, rep in _REDACT:
        t = rx.sub(rep, t)
    return t
def mask_token(token: str | None) -> str:
    return "" if not token else f"{token[:4]}••••{token[-4:]}"
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|s\b|sec|seconds?)", re.I)
def numbers_consistent(text: str, facts: str) -> bool:
    """False if the text states a percentage/seconds figure that is absent from the verified facts."""
    return all(m in facts for m in _NUM.findall(text or ""))
