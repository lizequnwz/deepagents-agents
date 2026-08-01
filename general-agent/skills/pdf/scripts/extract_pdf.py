"""Bounded PDF text extraction for the General Agent runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from pypdf import PdfReader


def _safe_input(raw: str) -> Path:
    path = Path(raw).resolve()
    roots = [
        Path(os.environ[name]).resolve()
        for name in ("GENERAL_AGENT_CHAT_DIR", "GENERAL_AGENT_SHARED_DIR")
        if os.environ.get(name)
    ]
    if not roots or not any(path.is_relative_to(root) for root in roots):
        raise ValueError("Input must be inside the current chat or shared workspace.")
    if not path.is_file() or path.is_symlink():
        raise ValueError("Input must be a regular, non-symlink PDF file.")
    return path


def _output_path(source: Path) -> Path:
    root = Path(os.environ["GENERAL_AGENT_TEMP_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem)[:80] or "document"
    candidate = root / f"{stem}.pdf-text.txt"
    index = 2
    while candidate.exists():
        candidate = root / f"{stem}.pdf-text-{index}.txt"
        index += 1
    return candidate


def _page_delta(text: str, previous: str, seen_lines: set[str]) -> tuple[str, bool]:
    if previous and len(previous) > 1000 and text.startswith(previous):
        return text[len(previous) :].lstrip(), True
    lines = [line.rstrip() for line in text.splitlines()]
    substantial = [line.strip() for line in lines if len(line.strip()) >= 3]
    overlap = sum(line in seen_lines for line in substantial)
    current_lines = set(substantial)
    previous_lines = {
        line.strip() for line in previous.splitlines() if len(line.strip()) >= 3
    }
    previous_coverage = (
        sum(line in current_lines for line in previous_lines) / len(previous_lines)
        if previous_lines
        else 0.0
    )
    cumulative = bool(
        previous
        and substantial
        and (
            (
                len(text) >= len(previous) * 0.8
                and overlap / len(substantial) >= 0.75
            )
            or (
                len(text) >= len(previous) * 1.2
                and previous_coverage >= 0.8
            )
        )
    )
    if cumulative:
        lines = [line for line in lines if line.strip() not in seen_lines]
    return "\n".join(lines).strip(), cumulative


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--max-page-chars", type=int, default=2200)
    args = parser.parse_args()
    source = _safe_input(args.input)
    reader = PdfReader(str(source))
    page_count = len(reader.pages)
    start = max(1, args.start_page)
    end = min(page_count, args.end_page or page_count)
    if start > end:
        raise ValueError("The requested page range is empty.")

    sections: list[str] = []
    seen_lines: set[str] = set()
    previous = ""
    repaired_pages: list[int] = []
    for page_number in range(start, end + 1):
        raw = reader.pages[page_number - 1].extract_text() or ""
        text, repaired = _page_delta(raw, previous, seen_lines)
        if repaired:
            repaired_pages.append(page_number)
        if not args.full and len(text) > args.max_page_chars:
            head = max(1, int(args.max_page_chars * 0.75))
            tail = max(1, args.max_page_chars - head)
            omitted = len(text) - head - tail
            text = (
                text[:head].rstrip()
                + f"\n[... {omitted:,} page characters omitted; rerun this page range with --full ...]\n"
                + text[-tail:].lstrip()
            )
        sections.append(f"===== PAGE {page_number} =====\n{text}".rstrip())
        seen_lines.update(
            line.strip() for line in raw.splitlines() if len(line.strip()) >= 3
        )
        previous = raw

    output = _output_path(source)
    content = "\n\n".join(sections) + "\n"
    output.write_text(content, encoding="utf-8")
    has_text = any(section.partition("\n")[2].strip() for section in sections)
    warnings: list[str] = []
    if not has_text:
        warnings.append("No embedded text found; this may be scanned/image-only and OCR is unavailable.")
    if repaired_pages:
        warnings.append("Cumulative page text was detected and deduplicated.")
    print(
        json.dumps(
            {
                "format": "pdf",
                "source": source.name,
                "page_count": page_count,
                "pages_extracted": [start, end],
                "characters": len(content),
                "mode": "full" if args.full else "summary-view",
                "virtual_path": f"/tmp/{output.name}",
                "shell_path": str(output),
                "warnings": warnings,
                "repaired_pages": repaired_pages,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
