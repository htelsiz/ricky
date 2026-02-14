"""merge_conflict_resolver — detect and comment on merge conflicts.

When a PR has merge conflicts, posts analysis and resolution suggestions.
"""

import logging

from ..clients.github import GitHubClient
from ..gemini_client import GeminiClient
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

_CONFLICT_PROMPT = """\
You are Ricky LaFleur from Trailer Park Boys. A PR has merge conflicts.

Given the conflicting files listed below, explain in 2-3 sentences what
probably happened (who changed what) and suggest how to resolve it.
Stay in character. Use Rickyisms. Keep it practical."""


@tool(
    "merge_conflict_resolver",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def merge_conflict_resolver(ctx: WebhookContext) -> None:
    """Check for merge conflicts and post resolution advice."""
    assert ctx.pr is not None

    # GitHub tells us if mergeable — can be None (not yet computed), True, or False
    if ctx.pr.mergeable is not False:
        return

    gh = GitHubClient.from_env()
    gemini = GeminiClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name

    log.info("PR #%d has merge conflicts", ctx.pr.number)

    files = await gh.get_pull_files(owner, repo, ctx.pr.number, ctx.installation_id)
    file_list = [f.get("filename", "") for f in files[:20]]

    diagnosis = await gemini.generate(
        _CONFLICT_PROMPT,
        f"PR #{ctx.pr.number}: merging `{ctx.pr.head_ref}` into `{ctx.pr.base_ref}`\n\n"
        f"Files in this PR:\n" + "\n".join(f"- {f}" for f in file_list),
    )

    if not diagnosis:
        return

    comment = (
        f"**Everyone's stepping on each other's dicks here, boys.**\n\n"
        f"This PR has merge conflicts with `{ctx.pr.base_ref}`.\n\n"
        f"{diagnosis}\n\n"
        f"To fix it:\n"
        f"```bash\n"
        f"git checkout {ctx.pr.head_ref}\n"
        f"git merge {ctx.pr.base_ref}\n"
        f"# resolve conflicts\n"
        f"git add . && git commit\n"
        f"git push\n"
        f"```"
    )

    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id,
        body=comment,
    )
