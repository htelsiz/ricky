"""Parse unified diffs into structured file/line data for inline review comments."""

import re


def parse_diff(raw_diff: str) -> list[dict]:
    """Parse a unified diff into per-file line data.

    Returns:
        [{"path": "src/foo.py", "lines": [
            {"number": 42, "content": "new code", "type": "add"},
            {"number": 43, "content": "unchanged", "type": "context"},
        ]}]

    Tracks both added lines (+) and context lines (unchanged lines visible
    in the diff hunk). GitHub's Reviews API allows comments on ANY line
    visible in the diff, not just added lines.
    """
    files = []
    file_chunks = re.split(r"^diff --git ", raw_diff, flags=re.MULTILINE)

    for chunk in file_chunks:
        if not chunk.strip():
            continue

        path_match = re.search(r"^\+\+\+ b/(.+)$", chunk, re.MULTILINE)
        if not path_match:
            continue

        path = path_match.group(1)

        if re.search(r"^\+\+\+ /dev/null", chunk, re.MULTILINE):
            continue

        lines = []

        hunk_pattern = re.compile(
            r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@.*$", re.MULTILINE
        )
        hunk_starts = list(hunk_pattern.finditer(chunk))

        for i, hunk_match in enumerate(hunk_starts):
            new_line_num = int(hunk_match.group(1))

            hunk_start = hunk_match.end()
            if i + 1 < len(hunk_starts):
                hunk_end = hunk_starts[i + 1].start()
            else:
                hunk_end = len(chunk)

            hunk_body = chunk[hunk_start:hunk_end]

            for line in hunk_body.split("\n"):
                if line.startswith("+"):
                    lines.append({
                        "number": new_line_num,
                        "content": line[1:],
                        "type": "add",
                    })
                    new_line_num += 1
                elif line.startswith("-"):
                    pass  # deleted lines don't appear in new file
                elif line.startswith("\\"):
                    pass  # "\ No newline at end of file"
                elif line.startswith(" ") or line == "":
                    content = line[1:] if line.startswith(" ") else ""
                    lines.append({
                        "number": new_line_num,
                        "content": content,
                        "type": "context",
                    })
                    new_line_num += 1

        if lines:
            files.append({"path": path, "lines": lines})

    return files


def build_diff_prompt(parsed: list[dict]) -> str:
    """Format parsed diff data into a structured prompt for Gemini.

    Shows each file's lines with line numbers and change type markers
    so Gemini can reference exact locations and write valid suggestions.
    """
    if not parsed:
        return "(no changed lines found)"

    sections = []
    for file_info in parsed:
        lines_text = "\n".join(
            f"  L{line['number']}: {'+ ' if line['type'] == 'add' else '  '}{line['content']}"
            for line in file_info["lines"]
        )
        sections.append(f"File: {file_info['path']}\nLines (+ = added/changed, blank = context):\n{lines_text}")

    return "\n\n".join(sections)


def valid_lines_for_path(parsed: list[dict], path: str) -> set[int]:
    """Return the set of valid commentable line numbers for a given file path.

    Includes both added and context lines since GitHub allows
    commenting on any line visible in the diff.
    """
    for file_info in parsed:
        if file_info["path"] == path:
            return {line["number"] for line in file_info["lines"]}
    return set()
