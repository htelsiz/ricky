"""ci_status_reporter — diagnose CI/CD failures and post analysis."""

import logging

from ..clients.github import GitHubClient
from ..gemini_client import GeminiClient
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

_CI_DIAGNOSIS_PROMPT = """\
You are Ricky LaFleur from Trailer Park Boys. A CI/CD build just failed.

Analyze the following CI log output and:
1. Identify the root cause of the failure
2. Explain what went wrong in plain English (Ricky-style)
3. Suggest a specific fix

Keep it short — 2-3 paragraphs max. Stay in character. Use Rickyisms.
The technical advice must be CORRECT even though the delivery is Ricky."""


@tool(
    "ci_status_reporter",
    events=["check_suite"],
    actions=["completed"],
)
async def ci_status_reporter_suite(ctx: WebhookContext) -> None:
    """Handle check_suite.completed — analyze failures."""
    if ctx.check_suite is None:
        return

    if ctx.check_suite.conclusion not in ("failure", "timed_out"):
        return

    if not ctx.check_suite.head_sha or not ctx.check_suite.pr_numbers:
        log.info("Check suite failure but no associated PR, skipping")
        return

    gh = GitHubClient.from_env()
    gemini = GeminiClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name
    pr_number = ctx.check_suite.pr_numbers[0]

    check_runs = await gh.get_check_runs_for_ref(
        owner, repo, ctx.check_suite.head_sha, ctx.installation_id,
    )
    failed_runs = [r for r in check_runs if r.get("conclusion") in ("failure", "timed_out")]
    if not failed_runs:
        return

    failure_details = []
    for run in failed_runs[:3]:
        run_name = run.get("name", "unknown")
        run_id = run.get("id", 0)
        output = run.get("output", {})
        summary = output.get("summary", "") or output.get("text", "")

        if summary:
            failure_details.append(f"### {run_name}\n{summary[:3000]}")
        else:
            failure_details.append(f"### {run_name}\nNo log output available (run ID: {run_id})")

    if not failure_details:
        return

    log_content = "\n\n".join(failure_details)

    diagnosis = await gemini.generate(
        _CI_DIAGNOSIS_PROMPT,
        f"## Failed CI checks for PR #{pr_number}\n\n{log_content}",
    )
    if not diagnosis:
        return

    await gh.post_issue_comment(
        owner, repo, pr_number, ctx.installation_id,
        body=(
            f"**The fuckin' CI broke, boys.** Here's what happened:\n\n"
            f"{diagnosis}\n\n"
            f"---\n"
            f"*{len(failed_runs)} check(s) failed on commit {ctx.check_suite.head_sha[:8]}*"
        ),
    )
    log.info("Posted CI failure diagnosis on PR #%d", pr_number)


@tool(
    "ci_status_reporter_run",
    events=["check_run"],
    actions=["completed"],
)
async def ci_status_reporter_run(ctx: WebhookContext) -> None:
    """Handle check_run.completed — analyze individual failures."""
    if ctx.check_run is None:
        return

    if ctx.check_run.conclusion not in ("failure", "timed_out"):
        return

    if not ctx.check_run.pr_numbers:
        return

    summary = ctx.check_run.output_summary or ctx.check_run.output_text
    if not summary:
        log.info("Check run %s failed but no output, skipping diagnosis", ctx.check_run.name)
        return

    gemini = GeminiClient.from_env()
    diagnosis = await gemini.generate(
        _CI_DIAGNOSIS_PROMPT,
        f"## Failed check: {ctx.check_run.name}\n\n{summary[:5000]}",
    )
    if not diagnosis:
        return

    gh = GitHubClient.from_env()
    pr_number = ctx.check_run.pr_numbers[0]

    await gh.post_issue_comment(
        ctx.repo.owner, ctx.repo.name, pr_number, ctx.installation_id,
        body=(
            f"**`{ctx.check_run.name}` just shit the bed, boys.** "
            f"Here's what I think happened:\n\n{diagnosis}"
        ),
    )
    log.info("Posted CI run failure diagnosis for %s on PR #%d", ctx.check_run.name, pr_number)
