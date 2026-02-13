"""Vertex AI client — sends diff + Ricky persona to Gemini 3 Pro."""

import logging
import os
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview")

_credentials = None

FALLBACK_SYSTEM_PROMPT = (
    "You ARE Ricky LaFleur from Trailer Park Boys. You review code in character. "
    "You butcher sayings (Rickyisms), swear casually, and speak in a working-class, "
    "uneducated but street-smart tone. Your technical advice is CORRECT even though "
    "your explanations sound like Ricky. Never break character."
)


def _get_credentials():
    global _credentials
    if _credentials is None:
        key_path = os.environ.get(
            "GCP_SA_KEY_FILE", "/secrets/gcp-service-account.json"
        )
        _credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    if not _credentials.valid:
        _credentials.refresh(Request())
    return _credentials


def _vertex_url() -> str:
    project = GCP_PROJECT
    if not project:
        project_file = os.environ.get("GCP_PROJECT_FILE", "/secrets/gcp-project")
        p = Path(project_file)
        if p.exists():
            project = p.read_text().strip()
    return (
        f"https://aiplatform.googleapis.com/v1beta1/"
        f"projects/{project}/locations/global/"
        f"publishers/google/models/{GEMINI_MODEL}:generateContent"
    )


async def generate_review(
    diff: str,
    pr_title: str,
    pr_body: str,
    styleguide: str,
) -> str:
    """Generate a code review using Gemini 3 Pro."""
    # Always use Ricky's persona — repo styleguide is supplemental patterns
    extra = ""
    if styleguide:
        extra = f"\n\nAdditional coding patterns to enforce:\n{styleguide}"
    system_prompt = FALLBACK_SYSTEM_PROMPT + extra

    user_prompt = f"""Review this pull request.

**Title:** {pr_title}

**Description:**
{pr_body}

**Diff:**
```diff
{diff}
```

Provide a code review as Ricky LaFleur. Include:
1. A Ricky-style summary of what the PR does
2. Any bugs, security issues, or code quality problems you spot
3. Suggestions for improvement
4. An overall verdict (Decent! or shit-winds warning)

Keep your review concise but thorough. Use Rickyisms naturally."""

    return await _call_gemini(system_prompt, user_prompt)


async def generate_reply(question: str, context: str) -> str:
    """Generate a reply to an @ricky mention."""
    user_prompt = f"""Someone is asking you a question in a GitHub issue/PR.

**Context:** {context}

**Their message:**
{question}

Reply as Ricky LaFleur. Be helpful but stay in character."""

    return await _call_gemini(FALLBACK_SYSTEM_PROMPT, user_prompt)


async def _call_gemini(system_prompt: str, user_prompt: str) -> str:
    """Call Gemini via Vertex AI REST API."""
    creds = _get_credentials()

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _vertex_url(),
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120.0,
        )

    if resp.status_code != 200:
        logger.error("Gemini API error: %d %s", resp.status_code, resp.text)
        return ""

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        logger.error("Unexpected Gemini response: %s", data)
        return ""
