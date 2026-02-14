"""Vertex AI client — sends diff + Ricky persona to Gemini."""

import json
import logging
import re
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import GcpSettings, GeminiSettings
from .errors import ApiResponseError

log = logging.getLogger(__name__)

FALLBACK_SYSTEM_PROMPT = (
    "You ARE Ricky LaFleur from Trailer Park Boys. You review code in character. "
    "You butcher sayings (Rickyisms), swear casually, and speak in a working-class, "
    "uneducated but street-smart tone. Your technical advice is CORRECT even though "
    "your explanations sound like Ricky. Never break character."
)


class GeminiClient:
    """Async Gemini client via Vertex AI REST API."""

    service_name = "gemini"

    def __init__(self, gcp: GcpSettings, gemini: GeminiSettings) -> None:
        self._gcp = gcp
        self._gemini = gemini
        self._credentials: service_account.Credentials | None = None

    @classmethod
    def from_env(cls) -> "GeminiClient":
        return cls(GcpSettings(), GeminiSettings())  # type: ignore[call-arg]

    # -- internals ------------------------------------------------------------

    def _get_credentials(self) -> service_account.Credentials:
        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_file(
                self._gcp.sa_key_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials

    def _vertex_url(self) -> str:
        project = self._gcp.project
        if not project:
            p = Path(self._gcp.project_file)
            if p.exists():
                project = p.read_text().strip()
        return (
            f"https://aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/global/"
            f"publishers/google/models/{self._gemini.model}:generateContent"
        )

    def _handle_response(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            raise ApiResponseError(self.service_name, resp.status_code, resp.text)

    # -- core API -------------------------------------------------------------

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini and return the generated text."""
        creds = self._get_credentials()

        body = {
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "temperature": self._gemini.temperature,
                "maxOutputTokens": self._gemini.max_output_tokens,
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._vertex_url(),
                headers={
                    "Authorization": f"Bearer {creds.token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self._gemini.timeout,
            )

        self._handle_response(resp)

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            log.error("Unexpected Gemini response: %s", data)
            return ""

    # -- high-level methods ---------------------------------------------------

    async def generate_review(
        self,
        diff: str,
        structured_diff: str,
        pr_title: str,
        pr_body: str,
        styleguide: str,
    ) -> dict:
        """Generate a structured code review with inline comments.

        Returns:
            {"summary": str, "comments": [{"path": str, "line": int, "body": str}]}
        """
        extra = ""
        if styleguide:
            extra = f"\n\nAdditional coding patterns to enforce:\n{styleguide}"

        system_prompt = FALLBACK_SYSTEM_PROMPT + extra + """

## Your Task
You are reviewing a pull request. Provide your review as a JSON object with a brief summary and detailed inline comments on specific lines of code.

Stay in character as Ricky LaFleur throughout every comment. Use Rickyisms naturally.

## Response Format
You MUST respond with valid JSON only. No markdown fences. No text outside the JSON.

{
  "summary": "Brief 1-3 sentence Ricky-style verdict. Decent! or shit-winds warning.",
  "comments": [
    {
      "path": "src/example.py",
      "line": 42,
      "body": "The comment body in markdown format (see rules below)"
    }
  ]
}

## Comment Body Format
Each comment body MUST follow this structure:

1. Start with a severity badge on its own line — one of:
   `![critical](https://www.gstatic.com/codereviewagent/critical.svg)`
   `![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)`
   `![low](https://www.gstatic.com/codereviewagent/low.svg)`

2. Then a blank line followed by a detailed explanation (2-5 sentences) of the issue or praise, in character as Ricky. Use Rickyisms, malapropisms, and your unique way of explaining things — but the technical advice must be CORRECT.

3. If you have a specific code fix, include a GitHub suggestion block:
   ````
   ```suggestion
   the corrected line(s) of code
   ```
   ````
   The suggestion block replaces the line you're commenting on, so write the corrected version of that line.

## Comment Rules
- "path" must EXACTLY match a file path from the changed lines below
- "line" must EXACTLY match a line number (the number after L) from the changed lines below
- Write as many comments as needed to cover all significant issues — do not limit yourself
- Focus on: security issues, bugs, code quality problems, and praise for decent code
- Every comment must be in character as Ricky
"""

        user_prompt = f"""Review this pull request and provide inline comments on specific lines.

**Title:** {pr_title}

**Description:**
{pr_body}

**Changed lines by file:**
{structured_diff}

**Full diff for additional context:**
```diff
{diff}
```
"""

        raw = await self.generate(system_prompt, user_prompt)
        return _parse_review_response(raw)

    async def generate_reply(self, question: str, context: str) -> str:
        """Generate a reply to an @ricky mention."""
        user_prompt = f"""Someone is asking you a question in a GitHub issue/PR.

**Context:** {context}

**Their message:**
{question}

Reply as Ricky LaFleur. Be helpful but stay in character."""

        return await self.generate(FALLBACK_SYSTEM_PROMPT, user_prompt)


def _parse_review_response(raw: str) -> dict:
    """Parse Gemini's JSON response into a structured review dict.

    Falls back to a summary-only review if JSON parsing fails.
    """
    if not raw:
        return {"summary": "", "comments": []}

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "summary" in parsed:
            comments = parsed.get("comments", [])
            valid_comments = []
            for c in comments:
                if (
                    isinstance(c, dict)
                    and isinstance(c.get("path"), str)
                    and isinstance(c.get("line"), int)
                    and isinstance(c.get("body"), str)
                ):
                    valid_comments.append(c)
                else:
                    log.warning("Dropping malformed comment: %s", c)
            return {"summary": parsed["summary"], "comments": valid_comments}
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("Failed to parse JSON review, falling back to raw text: %s", e)

    return {"summary": raw, "comments": []}
