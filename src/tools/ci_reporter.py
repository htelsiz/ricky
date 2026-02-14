"""ci_status_reporter — diagnose CI/CD failures and post analysis.

Triggers on check_suite.completed or check_run.completed when the conclusion
is a failure. Fetches logs, uses Gemini to diagnose, posts a comment.
"""

from __future__ import annotations

import logging

from ..clients.github import GitHubClient
from ..gemini_client import _call_gemini, FALLBACK_SYSTEM_PROMPT
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

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
async def ci_status_reporter_suite(data: dict) -> None:
    """Handle check_suite.completed — analyze failures."""
    check_suite = data.get("check_suite", {})
    conclusion = check_suite.get("conclusion", "")

    if conclusion not in ("failure", "timed_out"):
        return

    repo = data["repository"]
    installation_id = data["installation"]["id"]
    owner = repo["owner"]["login"]
    repo_name = repo["name"]

    head_sha = check_suite.get("head_sha", "")
    if not head_sha:
        return

    # Find the associated PR (if any)
    prs = check_suite.get("pull_requests", [])
    if not prs:
        logger.info("Check suite failure on %s but no associated PR, skipping", head_sha[:8])
        return

    pr_number = prs[0]["number"]

    # Get failed check runs for this suite
    check_runs = await _gh.get_check_runs_for_ref(owner, repo_name, head_sha, installation_id)
    failed_runs = [r for r in check_runs if r.get("conclusion") in ("failure", "timed_out")]

    if not failed_runs:
        return

    # Build a summary of failures
    failure_details = []
    for run in failed_runs[:3]:  # Cap at 3 to avoid huge prompts
        run_name = run.get("name", "unknown")
        run_id = run.get("id", 0)

        # Try to get the output summary (available without actions:read)
        output = run.get("output", {})
        summary = output.get("summary", "") or output.get("text", "")

        if summary:
            failure_details.append(f"### {run_name}\n{summary[:3000]}")
        else:
            failure_details.append(f"### {run_name}\nNo log output available (run ID: {run_id})")

    if not failure_details:
        return

    log_content = "\n\n".join(failure_details)

    # Ask Gemini to diagnose
    diagnosis = await _call_gemini(
        _CI_DIAGNOSIS_PROMPT,
        f"## Failed CI checks for PR #{pr_number}\n\n{log_content}",
    )

    if not diagnosis:
        return

    comment_body = (
        f"**The fuckin' CI broke, boys.** Here's what happened:\n\n"
        f"{diagnosis}\n\n"
        f"---\n"
        f"*{len(failed_runs)} check(s) failed on commit {head_sha[:8]}*"
    )

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body=comment_body,
    )

    logger.info("Posted CI failure diagnosis on PR #%d", pr_number)


@tool(
    "ci_status_reporter_run",
    events=["check_run"],
    actions=["completed"],
)
async def ci_status_reporter_run(data: dict) -> None:
    """Handle check_run.completed — analyze individual failures."""
    check_run = data.get("check_run", {})
    conclusion = check_run.get("conclusion", "")

    if conclusion not in ("failure", "timed_out"):
        return

    repo = data["repository"]
    installation_id = data["installation"]["id"]
    owner = repo["owner"]["login"]
    repo_name = repo["name"]

    # Find associated PR
    prs = check_run.get("pull_requests", [])
    if not prs:
        return

    pr_number = prs[0]["number"]
    run_name = check_run.get("name", "unknown")

    # Get output from the check run itself
    output = check_run.get("output", {})
    summary = output.get("summary", "") or output.get("text", "")

    if not summary:
        logger.info("Check run %s failed but no output, skipping diagnosis", run_name)
        return

    # Cap log size
    log_text = summary[:5000]

    diagnosis = await _call_gemini(
        _CI_DIAGNOSIS_PROMPT,
        f"## Failed check: {run_name}\n\n{log_text}",
    )

    if not diagnosis:
        return

    comment_body = (
        f"**`{run_name}` just shit the bed, boys.** Here's what I think happened:\n\n"
        f"{diagnosis}"
    )

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body=comment_body,
    )

    logger.info("Posted CI run failure diagnosis for %s on PR #%d", run_name, pr_number)
