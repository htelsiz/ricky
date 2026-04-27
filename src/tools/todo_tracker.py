"""todo_tracker — find newly-added TODO/FIXME/HACK/NOTE comments in PR diffs and
open GitHub issues for the genuine ones.

The model gets the raw unified diff and a Pydantic-derived schema; its response
is validated into typed ``TodoItem`` instances.
"""

import logging

from ..clients.github import GitHubClient
from ..config import RickySettings
from ..gemini_client import GeminiClient
from ..models.github import WebhookContext
from ..models.tools import TodoItem, TodoResponse
from ._registry import tool

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You scan unified diffs for newly-added unfinished-work comments — TODO, FIXME,
HACK, or NOTE markers a developer wrote in a real code comment to flag deferred
work.

Reject anything that is not a real comment marker:
- Placeholders in docs/code (`GLY-XXX`, `feature/GLY-XXX`, `<TODO>`, `${TODO}`)
- Example/redacted values (`user=xxx&port=22`, `password=xxxx`)
- Prose that mentions the concept (READMEs, CLAUDE.md sections discussing how
  to write TODOs)
- String literals or test fixtures that happen to contain the word

Only report comments on lines marked `+` in the diff (newly added). Return an
empty list when nothing genuine was added."""


def _issue_title(t: TodoItem) -> str:
    return f"{t.kind}: {t.title}"


def _issue_body(t: TodoItem, ctx: WebhookContext) -> str:
    link = (
        f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}/blob/"
        f"{ctx.pr.head_sha}/{t.file}#L{t.line}"
    )
    return (
        f"**{t.kind}** in [{t.file}:{t.line}]({link})\n\n"
        f"{t.context}\n\n"
        f"_Detected in PR #{ctx.pr.number} (`{ctx.pr.head_ref}`)._"
    )


@tool(
    "todo_tracker",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
    commands=["@ricky todos"],
)
async def todo_tracker(ctx: WebhookContext) -> None:
    assert ctx.pr is not None
    gh = GitHubClient.from_env()
    cfg = RickySettings()  # type: ignore[call-arg]
    owner, repo = ctx.repo.owner, ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    response = await GeminiClient.from_env().generate_json(
        _SYSTEM_PROMPT,
        f"PR #{ctx.pr.number}: {ctx.pr.title}\n\n{diff}",
        model=TodoResponse,
        thinking_budget=512,
    )
    todos = response.todos if response else []
    if not todos:
        log.info("No genuine TODOs found in PR #%d", ctx.pr.number)
        return

    if cfg.todo_create_issues:
        existing = await gh.list_issues(
            owner, repo, ctx.installation_id, labels=["tech-debt"], state="open",
        )
        seen = {i["title"].strip().lower() for i in existing}
        new_todos = [t for t in todos if _issue_title(t).lower() not in seen]
        for t in new_todos:
            await gh.create_issue(
                owner, repo, ctx.installation_id,
                title=_issue_title(t),
                body=_issue_body(t, ctx),
                labels=["tech-debt"],
            )
        log.info(
            "PR #%d: %d TODO(s), %d new issue(s) opened, %d already tracked",
            ctx.pr.number, len(todos), len(new_todos), len(todos) - len(new_todos),
        )

    summary = "\n".join([
        f"**Found {len(todos)} new TODO(s) in this PR, boys.**",
        "",
        *(f"- `{t.kind}` in `{t.file}:{t.line}` — {t.title}" for t in todos),
    ])
    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id, body=summary,
    )
