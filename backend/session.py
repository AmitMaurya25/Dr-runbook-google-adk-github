"""Browser session recovery helpers. The session id doubles as a bearer code (simulated identity, not authentication)."""
from __future__ import annotations
import re, secrets
_CODE = re.compile(r"^[0-9a-f]{32}$")
def new_session_id() -> str: return secrets.token_hex(16)
def normalise_code(code) -> str: return re.sub(r"\s+", "", str(code or "")).lower()
def is_valid_code(code) -> bool: return bool(_CODE.match(normalise_code(code)))
def resume(store, code):
    sid = normalise_code(code)
    if not _CODE.match(sid): raise ValueError("That is not a valid session code (32 hexadecimal characters).")
    drills = store.list_drills(sid)
    if not drills: raise ValueError("No drills were found for that session code.")
    return sid, drills
