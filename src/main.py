"""Ricky GitHub App — FastAPI webhook endpoint with signature verification."""

import collections
import hashlib
import hmac
import logging
import traceback
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request

from .config import GithubSettings
from .webhook_handler import handle_webhook

# In-memory ring buffer for debug logs (no filesystem needed)
_log_buffer: collections.deque = collections.deque(maxlen=200)


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _log_buffer.append(self.format(record))


logging.basicConfig(level=logging.INFO)
_bh = BufferHandler()
_bh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_bh)

log = logging.getLogger(__name__)

app = FastAPI(title="Ricky", description="Trailer Park Boys Code Reviewer")

_webhook_secret: bytes | None = None


def _get_webhook_secret() -> bytes:
    global _webhook_secret
    if _webhook_secret is None:
        cfg = GithubSettings()  # type: ignore[call-arg]
        _webhook_secret = Path(cfg.webhook_secret_file).read_text().strip().encode()
    return _webhook_secret


def _verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        _get_webhook_secret(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/debug/logs")
async def debug_logs() -> dict:
    return {"logs": list(_log_buffer)}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
) -> dict:
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_data = await request.json()
    log.info("Received event: %s, action: %s", x_github_event, event_data.get("action"))

    try:
        await handle_webhook(x_github_event, event_data)
    except Exception:
        log.error("Webhook handler failed:\n%s", traceback.format_exc())
        raise

    return {"status": "ok"}
