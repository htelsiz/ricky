"""auto_fix — apply Ricky's own review suggestions as commits.

When someone says ``@ricky fix`` on a PR, this tool:
1. Fetches Ricky's inline review comments containing ```suggestion blocks
2. Parses the suggestion replacements (file path + line range + new code)
3. Applies them to the current file contents on the PR branch
4. Commits atomically via the Git Data API (blob → tree → commit → ref)
"""

import logging
import re

from ..clients.github import GitHubClient
from ..config import RickySettings
from ..errors import ApiResponseError
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

# Matches ```suggestion ... ``` blocks in comment bodies
_SUGGESTION_RE = re.compile(
    r"```suggestion\s*\n(.*?)```",
    re.DOTALL,
)

# GitHub Apps appear as "<app-slug>[bot]"
_BOT_SUFFIX = "[bot]"


def _parse_suggestions(comments: list[dict]) -> list[dict]:
    """Extract actionable suggestions from Ricky's review comments.

    Returns a list of dicts:
        {"path": str, "start_line": int, "end_line": int, "replacement": str}

    Each suggestion replaces lines [start_line, end_line] inclusive in the file.
    """
    suggestions: list[dict] = []
    for c in comments:
        body = c.get("body", "")
        match = _SUGGESTION_RE.search(body)
        if not match:
            continue

        path = c.get("path", "")
        if not path:
            continue

        # GitHub review comments: "line" is the end line, "start_line" is the
        # start for multi-line comments.  Single-line comments have start_line=None.
        end_line = c.get("line") or c.get("original_line")
        start_line = c.get("start_line") or c.get("original_start_line") or end_line

        if not end_line:
            continue

        replacement = match.group(1)
        # Strip trailing newline that comes from the fenced block formatting,
        # but preserve internal newlines in multi-line replacements.
        if replacement.endswith("\n"):
            replacement = replacement[:-1]

        suggestions.append({
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "replacement": replacement,
        })

    return suggestions


def _apply_suggestions(original: str, suggestions: list[dict]) -> str:
    """Apply line-range replacements to file content.

    Suggestions must all target the same file.  They are applied in reverse
    line order so that earlier replacements don't shift line numbers for later ones.
    """
    lines = original.split("\n")

    # Sort by start_line descending so we apply bottom-up
    for s in sorted(suggestions, key=lambda s: s["start_line"], reverse=True):
        start = s["start_line"] - 1  # 0-indexed
        end = s["end_line"]          # exclusive upper bound (1-indexed end → 0-indexed exclusive)
        replacement_lines = s["replacement"].split("\n")
        lines[start:end] = replacement_lines

    return "\n".join(lines)


@tool(
    "auto_fix",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky fix"],
)
async def auto_fix(ctx: WebhookContext) -> None:
    """Apply Ricky's review suggestions when someone says @ricky fix."""
    if ctx.comment is None or ctx.issue is None:
        return

    if not re.search(r"@ricky\s+fix\b", ctx.comment.body, re.IGNORECASE):
        return

    gh = GitHubClient.from_env()
    cfg = RickySettings()  # type: ignore[call-arg]

    owner = ctx.repo.owner
    repo = ctx.repo.name
    pr_number = ctx.issue.number

    if not cfg.auto_fix_enabled:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body=(
                "Listen boys, auto-fix is turned off right now. "
                "Set `RICKY_AUTO_FIX_ENABLED=true` if you want me to start "
                "fixing shit myself."
            ),
        )
        return

    if not ctx.issue.has_pull_request:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body="Boys, I can only fix PRs, not regular issues. Open a PR first.",
        )
        return

    log.info("Auto-fix requested on PR #%d in %s/%s", pr_number, owner, repo)

    await gh.post_issue_comment(
        owner, repo, pr_number, ctx.installation_id,
        body="Worst case Ontario, I'll just fix it myself. Give me a minute, boys...",
    )

    # -- 1. Resolve PR head branch + SHA (we only have issue context here) ----
    pr_data = await gh.get_pr(owner, repo, pr_number, ctx.installation_id)
    head_sha = pr_data["head"]["sha"]
    head_ref = pr_data["head"]["ref"]

    # -- 2. Fetch Ricky's review comments with suggestion blocks --------------
    all_comments = await gh.get_pr_comments(
        owner, repo, pr_number, ctx.installation_id,
    )

    # Filter to Ricky's own comments (GitHub App bot suffix)
    ricky_comments = [
        c for c in all_comments
        if c.get("user", {}).get("login", "").endswith(_BOT_SUFFIX)
        and "```suggestion" in (c.get("body") or "")
    ]

    if not ricky_comments:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body=(
                "I don't have any suggestions to apply on this PR, boys. "
                "Nothing to fix here — it's all water under the fridge."
            ),
        )
        return

    suggestions = _parse_suggestions(ricky_comments)
    if not suggestions:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body="Couldn't parse any of my suggestions. That's f**ked.",
        )
        return

    log.info("Found %d suggestions across comments", len(suggestions))

    # -- 3. Group suggestions by file and apply -------------------------------
    by_file: dict[str, list[dict]] = {}
    for s in suggestions:
        by_file.setdefault(s["path"], []).append(s)

    if len(by_file) > cfg.auto_fix_max_files:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body=(
                f"That's {len(by_file)} files to fix — too many at once, boys. "
                f"Max is {cfg.auto_fix_max_files}. Fix some manually first."
            ),
        )
        return

    tree_items: list[dict] = []
    applied_count = 0
    file_names: list[str] = []

    for path, file_suggestions in sorted(by_file.items()):
        # Fetch current file content from PR branch
        content = await gh.fetch_file_raw(
            owner, repo, path, head_ref, ctx.installation_id,
        )
        if content is None:
            log.warning("Could not fetch %s from branch %s, skipping", path, head_ref)
            continue

        fixed = _apply_suggestions(content, file_suggestions)
        if fixed == content:
            log.info("No effective changes in %s, skipping", path)
            continue

        # Create blob with the fixed content
        blob_sha = await gh.create_blob(
            owner, repo, ctx.installation_id, content=fixed,
        )

        tree_items.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha,
        })
        applied_count += len(file_suggestions)
        file_names.append(path)

    if not tree_items:
        await gh.post_issue_comment(
            owner, repo, pr_number, ctx.installation_id,
            body=(
                "I tried applying my suggestions but nothing actually changed. "
                "Looks like they've already been addressed, boys. Decent."
            ),
        )
        return

    # -- 4. Atomic commit: tree → commit → update ref -------------------------
    try:
        commit_data = await gh.get_commit(
            owner, repo, head_sha, ctx.installation_id,
        )
        base_tree_sha = commit_data["tree"]["sha"]

        new_tree_sha = await gh.create_tree(
            owner, repo, ctx.installation_id,
            base_tree=base_tree_sha,
            tree_items=tree_items,
        )

        commit_msg = (
            f"fix: apply {applied_count} review suggestion(s)\n\n"
            f"Applied by Ricky via @ricky fix on PR #{pr_number}.\n"
            f"Files: {', '.join(file_names)}"
        )

        new_commit_sha = await gh.create_git_commit(
            owner, repo, ctx.installation_id,
            message=commit_msg,
            tree_sha=new_tree_sha,
            parent_shas=[head_sha],
        )

        await gh.update_ref(
            owner, repo, ctx.installation_id,
            ref=head_ref,
            sha=new_commit_sha,
        )
    except ApiResponseError as exc:
        if exc.status_code == 422:
            await gh.post_issue_comment(
                owner, repo, pr_number, ctx.installation_id,
                body=(
                    "The branch got updated while I was working on it, boys. "
                    "Can't push without stepping on someone's toes. "
                    "Say `@ricky fix` again on the latest code."
                ),
            )
            return
        raise

    log.info(
        "Applied %d suggestions to %d files on PR #%d (commit %s)",
        applied_count, len(file_names), pr_number, new_commit_sha[:8],
    )

    await gh.post_issue_comment(
        owner, repo, pr_number, ctx.installation_id,
        body=(
            f"Done, boys. Applied {applied_count} suggestion(s) across "
            f"{len(file_names)} file(s):\n\n"
            + "\n".join(f"- `{f}`" for f in file_names)
            + f"\n\nCommit: {new_commit_sha[:8]} — it's not rocket appliances."
        ),
    )
