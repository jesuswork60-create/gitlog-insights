"""Text, Markdown, JSON and CSV renderers."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from typing import Any, Callable

from .document import Column, Report, Section


def _human(value: Any, column: Column) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{column.digits}f}"
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)


def _plain(value: Any) -> Any:
    """Machine formats keep full precision: datetimes become ISO 8601 strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _table_cells(section: Section) -> list[list[str]]:
    return [[_human(row.get(col.key), col) for col in section.columns] for row in section.rows]


def render_text(report: Report) -> str:
    blocks = []
    for section in report.sections:
        lines = [section.title, "-" * len(section.title)]
        if not section.rows:
            lines.append("(nothing to report)")
            blocks.append("\n".join(lines))
            continue
        cells = _table_cells(section)
        titles = [col.title for col in section.columns]
        widths = [
            max(len(titles[i]), *(len(row[i]) for row in cells))
            for i in range(len(titles))
        ]

        def fit(values: list[str]) -> str:
            parts = [
                value.rjust(widths[i]) if section.columns[i].align == "right" else value.ljust(widths[i])
                for i, value in enumerate(values)
            ]
            return "  ".join(parts).rstrip()

        lines.append(fit(titles))
        lines.extend(fit(row) for row in cells)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _markdown_cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|")


def render_markdown(report: Report) -> str:
    blocks = []
    for section in report.sections:
        lines = [f"## {section.title}", ""]
        if not section.rows:
            lines.append("Nothing to report.")
            blocks.append("\n".join(lines))
            continue
        lines.append("| " + " | ".join(col.title for col in section.columns) + " |")
        rules = ("---:" if col.align == "right" else "---" for col in section.columns)
        lines.append("| " + " | ".join(rules) + " |")
        for row in _table_cells(section):
            lines.append("| " + " | ".join(_markdown_cell(cell) for cell in row) + " |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def render_json(report: Report) -> str:
    document = {
        "report": report.name,
        "meta": {key: _plain(value) for key, value in report.meta.items()},
        "sections": {
            section.key: [
                {col.key: _plain(row.get(col.key)) for col in section.columns}
                for row in section.rows
            ]
            for section in report.sections
        },
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def render_csv(report: Report) -> str:
    """One table per section; several sections are separated by a blank line."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for index, section in enumerate(report.sections):
        if index:
            out.write("\n")
        if len(report.sections) > 1:
            out.write(f"# {section.key}\n")
        writer.writerow(col.key for col in section.columns)
        for row in section.rows:
            writer.writerow(_plain(row.get(col.key)) for col in section.columns)
    return out.getvalue()


FORMATS: dict[str, Callable[[Report], str]] = {
    "text": render_text,
    "markdown": render_markdown,
    "json": render_json,
    "csv": render_csv,
}


def render(report: Report, output_format: str) -> str:
    try:
        renderer = FORMATS[output_format]
    except KeyError:
        raise ValueError(f"unknown format {output_format!r}") from None
    return renderer(report)
