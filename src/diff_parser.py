"""Parse unified diffs into structured file/line data for inline review comments."""

import re


def parse_diff(raw_diff: str) -> list[dict]:
    """Parse a unified diff into per-file changed-line data.

    Returns:
        [{"path": "src/foo.py", "lines": [{"number": 42, "content": "new code"}, ...]}]

    Only added/modified lines are returned since those are the lines
    the GitHub Reviews API allows comments on (side=RIGHT).
    """
    files = []
    # Split into per-file sections
    file_chunks = re.split(r"^diff --git ", raw_diff, flags=re.MULTILINE)

    for chunk in file_chunks:
        if not chunk.strip():
            continue

        # Extract file path from +++ b/path line
        path_match = re.search(r"^\+\+\+ b/(.+)$", chunk, re.MULTILINE)
        if not path_match:
            continue  # binary file or deleted file

        path = path_match.group(1)

        # Skip deleted files (--- a/path with +++ /dev/null)
        if re.search(r"^\+\+\+ /dev/null", chunk, re.MULTILINE):
            continue

        changed_lines = []

        # Find all hunk headers and parse each hunk
        hunk_pattern = re.compile(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@.*$", re.MULTILINE
        )
        hunk_starts = list(hunk_pattern.finditer(chunk))

        for i, hunk_match in enumerate(hunk_starts):
            new_line_num = int(hunk_match.group(1))

            # Get hunk body: from after this @@ to next @@ or end of chunk
            hunk_start = hunk_match.end()
            if i + 1 < len(hunk_starts):
                hunk_end = hunk_starts[i + 1].start()
            else:
                hunk_end = len(chunk)

            hunk_body = chunk[hunk_start:hunk_end]

            for line in hunk_body.split("\n"):
                if line.startswith("+"):
                    content = line[1:]  # strip the leading +
                    changed_lines.append(
                        {"number": new_line_num, "content": content}
                    )
                    new_line_num += 1
                elif line.startswith("-"):
                    pass  # deleted lines don't increment new file line counter
                elif line.startswith("\\"):
                    pass  # "\ No newline at end of file"
                else:
                    # Context line (or empty) — increment new line counter
                    new_line_num += 1

        if changed_lines:
            files.append({"path": path, "lines": changed_lines})

    return files


def build_diff_prompt(parsed: list[dict]) -> str:
    """Format parsed diff data into a structured prompt for Gemini.

    Presents each file's changed lines with line numbers so Gemini
    can reference exact locations in its review comments.
    """
    if not parsed:
        return "(no changed lines found)"

    sections = []
    for file_info in parsed:
        lines_text = "\n".join(
            f"  L{line['number']}: {line['content']}"
            for line in file_info["lines"]
        )
        sections.append(f"File: {file_info['path']}\nChanged lines:\n{lines_text}")

    return "\n\n".join(sections)


def valid_lines_for_path(parsed: list[dict], path: str) -> set[int]:
    """Return the set of valid commentable line numbers for a given file path."""
    for file_info in parsed:
        if file_info["path"] == path:
            return {line["number"] for line in file_info["lines"]}
    return set()
