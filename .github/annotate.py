"""Echo the tail of a failed CI step as a GitHub workflow annotation.

Why this exists: downloading job logs from the Actions API needs admin rights on the
repository, while annotations are readable by anyone on a public repo. Without this, a
contributor looking at a red tick can see only "Process completed with exit code 1", which
is not enough to act on and not enough to review.

Annotations are single-line, so newlines are percent-encoded per the workflow-command spec;
GitHub renders them back as line breaks.

Usage: python .github/annotate.py <title> <logfile> [max_bytes]
"""

from __future__ import annotations

import pathlib
import sys

MAX_BYTES = 8000


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: annotate.py <title> <logfile> [max_bytes]", file=sys.stderr)
        return 2

    title, path = argv[1], pathlib.Path(argv[2])
    limit = int(argv[3]) if len(argv) > 3 else MAX_BYTES

    if not path.exists():
        print(f"::error title={title}::step failed before writing {path}")
        return 0

    text = path.read_text(encoding="utf-8", errors="replace")[-limit:]
    # The workflow-command escapes. Order matters: '%' must be encoded first or it would
    # corrupt the escapes introduced after it.
    for raw, encoded in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A"), ("::", "%3A%3A")):
        text = text.replace(raw, encoded)
    print(f"::error title={title} failed::{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
