from __future__ import annotations

import re
import zipfile
from pathlib import Path

from save_issues.export import build_files
from save_issues.github import IssueData


def sanitize_part(value: str) -> str:
    text = value.strip()
    text = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "unknown"


def zip_name(data: IssueData) -> str:
    owner = sanitize_part(data.ref.owner)
    repo = sanitize_part(data.ref.repo)
    return f"{owner}_{repo}_{data.ref.number}.zip"


def write_issue_zip(
    data: IssueData,
    output_dir: Path,
    topic: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / zip_name(data)
    files = build_files(data, topic=topic)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(filename, content.encode("utf-8"))
    return path
