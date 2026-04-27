"""Vertex AI client — sends diff + Ricky persona to Gemini."""

import json
import logging
import re
from pathlib import Path
from typing import TypeVar, overload

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from pydantic import BaseModel, ValidationError

from .config import GcpSettings, GeminiSettings
from .errors import ApiResponseError

T = TypeVar("T", bound=BaseModel)


def _vertex_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema with $defs inlined — Vertex AI's responseSchema does
    not accept $ref/$defs, so resolve them in place."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref:
                return resolve(defs[ref.rsplit("/", 1)[-1]])
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)

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

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        thinking_budget: int | None = None,
        response_mime_type: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        """Call Gemini and return the generated text.

        thinking_budget: 0 disables thinking, -1 = dynamic (default), positive = fixed
                         token budget. Set 0 for short JSON extraction so Gemini 3.1 Pro
                         doesn't burn the output budget on internal reasoning.
        response_mime_type: pass "application/json" for native JSON output (no markdown
                            fences to strip).
        response_schema: JSON schema dict for structured output (requires JSON mime type).
        """
        creds = self._get_credentials()

        generation_config: dict = {
            "temperature": self._gemini.temperature,
            "maxOutputTokens": self._gemini.max_output_tokens,
        }
        if thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        if response_schema:
            generation_config["responseSchema"] = response_schema

        body = {
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": generation_config,
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

    @overload
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: type[T],
        thinking_budget: int = 0,
    ) -> T | None: ...

    @overload
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        thinking_budget: int = 0,
    ) -> dict | list | None: ...

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: type[BaseModel] | None = None,
        thinking_budget: int = 0,
    ):
        """Call Gemini with native JSON mime type and parse the result.

        Pass ``model=`` to get a validated Pydantic instance back; the schema
        is derived from the model and the response is validated against it.
        Without it, returns the raw parsed JSON.

        Defaults thinking_budget=0 since structured extraction rarely benefits
        from extended reasoning.
        """
        raw = await self.generate(
            system_prompt,
            user_prompt,
            thinking_budget=thinking_budget,
            response_mime_type="application/json",
            response_schema=_vertex_schema(model) if model else None,
        )
        if not raw:
            return None
        try:
            if model:
                return model.model_validate_json(raw)
            return json.loads(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("Failed to parse JSON response: %s\nRaw: %s", e, raw[:500])
            return None

    # -- high-level methods ---------------------------------------------------

    async def generate_review(
        self,
        diff: str,
        structured_diff: str,
        pr_title: str,
        pr_body: str,
        styleguide: str,
        existing_feedback: str = "",
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
- Focus on: security vulnerabilities, bugs, logic errors, resource leaks, error handling mistakes, and runtime correctness
- DO NOT comment on: code style, naming conventions, file organization, indentation depth, type annotations, import ordering, or pattern conformance — Julian handles those
- If code is functionally correct but stylistically ugly, leave it for Julian
- Praise genuinely good defensive coding or clever solutions
- Every comment must be in character as Ricky
- DO NOT repeat any feedback already given in the "Existing review comments" section
- If Ricky or Julian already flagged an issue, skip it entirely — focus on NEW issues only
- If there is nothing new to say, return an empty comments list with a short summary
"""

        existing_section = ""
        if existing_feedback:
            existing_section = f"""
**Existing review comments on this PR (DO NOT repeat these points):**
{existing_feedback}

"""

        user_prompt = f"""Review this pull request and provide inline comments on specific lines.

**Title:** {pr_title}

**Description:**
{pr_body}
{existing_section}**Changed lines by file:**
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
