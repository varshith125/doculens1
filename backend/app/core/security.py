import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "doculens_session"
SESSION_LIFETIME = 86400


class Sessions:
    """Opaque signed sessions; the server retains no user credentials or personal data."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def issue(self) -> str:
        payload = f"{int(time.time())}.{secrets.token_hex(24)}"
        signature = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def owner(self, token: str | None) -> str | None:
        if not token or len(token) > 160:
            return None
        try:
            issued, nonce, signature = token.split(".")
            age = time.time() - int(issued)
            if not 0 <= age < SESSION_LIFETIME or len(nonce) != 48:
                return None
            expected = hmac.new(
                self._key,
                f"{issued}.{nonce}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
        except (ValueError, TypeError):
            return None
        return hashlib.sha256(token.encode()).hexdigest()


def require_owner(request: Request) -> str:
    owner = request.app.state.sessions.owner(request.cookies.get(COOKIE_NAME))
    if not owner:
        raise HTTPException(401, "Start a new session before scanning.")
    return owner
