"""Glue between analyses and renderers: one builder per report name."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from .analysis import authors as authors_mod
from .analysis import churn as churn_mod
from .analysis import cochange as cochange_mod
from .analysis import compare as compare_mod
from .analysis import hotspots as hotspots_mod
from .analysis import messages as messages_mod
from .analysis import ownership as ownership_mod
from .analysis import summary as summary_mod
from .analysis import timeline as timeline_mod
from .models import Commit
from .render.document import Column, Report, Section


@dataclass(slots=True)
class ReportOptions:
    limit: int | None = 20
    sort: str | None = None
    depth: int = 1
    period: str = "month"
    fill_gaps: bool = True
    min_support: int = 2
    max_files: int = 30
    min_coupling: float = 0.0
    file: str | None = None
    metric: str = "lines"
    half_life_days: float = 90.0
    split: datetime | None = None


Builder = Callable[[Sequence[Commit], ReportOptions], Report]

_FILE_COLUMNS = [
    Column("path", "Path", align="left"),
    Column("commits", "Commits"),
    Column("added", "Added"),
    Column("deleted", "Deleted"),
    Column("churn", "Churn"),
    Column("authors", "Authors"),
    Column("last_changed", "Last changed"),
]


def _file_row(stats: churn_mod.FileStats) -> dict:
    return {
        "path": stats.path,
        "commits": stats.commits,
        "added": stats.added,
        "deleted": stats.deleted,
        "churn": stats.churn,
        "authors": len(stats.authors),
        "last_changed": stats.last_changed,
    }


def build_summary(commits: Sequence[Commit], options: ReportOptions) -> Report:
    data = summary_mod.summarize(commits)
    facts = [
        ("commits", data.commits),
        ("merges", data.merges),
        ("authors", data.authors),
        ("files", data.files),
        ("lines_added", data.added),
        ("lines_deleted", data.deleted),
        ("first_commit", data.first_commit),
        ("last_commit", data.last_commit),
        ("span_days", data.span_days),
        ("median_commit_size", float(data.median_commit_size)),
        ("largest_commit", data.largest_commit),
        ("largest_commit_size", data.largest_commit_size),
    ]
    section = Section(
        "summary",
        "Summary",
        [Column("metric", "Metric", align="left"), Column("value", "Value", align="left")],
        [{"metric": key, "value": value} for key, value in facts],
    )
    return Report("summary", [section])


def build_churn(commits: Sequence[Commit], options: ReportOptions) -> Report:
    ranked = churn_mod.rank_files(
        churn_mod.file_stats(commits).values(), by=options.sort or "churn", limit=options.limit
    )
    section = Section("files", "Files by change", _FILE_COLUMNS, [_file_row(s) for s in ranked])
    return Report("churn", [section])


def build_dirs(commits: Sequence[Commit], options: ReportOptions) -> Report:
    ranked = churn_mod.rank_files(
        churn_mod.directory_stats(commits, depth=options.depth).values(),
        by=options.sort or "churn",
        limit=options.limit,
    )
    section = Section(
        "directories", "Directories by change", _FILE_COLUMNS, [_file_row(s) for s in ranked]
    )
    return Report("dirs", [section], {"depth": options.depth})


def build_authors(commits: Sequence[Commit], options: ReportOptions) -> Report:
    ranked = authors_mod.rank_authors(
        authors_mod.author_stats(commits).values(),
        by=options.sort or "commits",
        limit=options.limit,
    )
    section = Section(
        "authors",
        "Author activity",
        [
            Column("name", "Author", align="left"),
            Column("email", "Email", align="left"),
            Column("commits", "Commits"),
            Column("added", "Added"),
            Column("deleted", "Deleted"),
            Column("files", "Files"),
            Column("active_days", "Days"),
            Column("longest_streak", "Streak"),
            Column("first_commit", "First"),
            Column("last_commit", "Last"),
        ],
        [
            {
                "name": s.name,
                "email": s.email,
                "commits": s.commits,
                "added": s.added,
                "deleted": s.deleted,
                "files": len(s.files),
                "active_days": len(s.active_days),
                "longest_streak": s.longest_streak,
                "first_commit": s.first_commit,
                "last_commit": s.last_commit,
            }
            for s in ranked
        ],
    )
    return Report("authors", [section])


def build_cochange(commits: Sequence[Commit], options: ReportOptions) -> Report:
    # With --file the limit applies to that file's partners, not to all pairs.
    pairs = cochange_mod.cochange_pairs(
        commits,
        min_support=options.min_support,
        max_files=options.max_files,
        min_coupling=options.min_coupling,
        limit=None if options.file else options.limit,
    )
    if options.file:
        partners = cochange_mod.partners_of(options.file, pairs)
        if options.limit is not None:
            partners = partners[: options.limit]
        pairs = [pair for _, pair in partners]
    section = Section(
        "pairs",
        f"Files changing with {options.file}" if options.file else "Files changing together",
        [
            Column("a", "File A", align="left"),
            Column("b", "File B", align="left"),
            Column("support", "Shared"),
            Column("coupling", "Coupling"),
            Column("a_to_b", "A->B"),
            Column("b_to_a", "B->A"),
        ],
        [
            {
                "a": pair.a,
                "b": pair.b,
                "support": pair.support,
                "coupling": pair.coupling,
                "a_to_b": pair.confidence_a_to_b,
                "b_to_a": pair.confidence_b_to_a,
            }
            for pair in pairs
        ],
    )
    return Report(
        "cochange",
        [section],
        {"min_support": options.min_support, "max_files": options.max_files},
    )


def build_ownership(commits: Sequence[Commit], options: ReportOptions) -> Report:
    data = ownership_mod.file_ownership(commits, metric=options.metric)
    ordered = sorted(data.values(), key=lambda o: (-o.total_weight, o.path))
    if options.limit is not None:
        ordered = ordered[: options.limit]
    files = Section(
        "files",
        "Main contributor per file",
        [
            Column("path", "Path", align="left"),
            Column("owner", "Owner", align="left"),
            Column("share", "Share"),
            Column("contributors", "People"),
            Column("weight", "Weight"),
        ],
        [
            {
                "path": o.path,
                "owner": o.owner,
                "share": o.owner_share,
                "contributors": o.contributors,
                "weight": o.total_weight,
            }
            for o in ordered
        ],
    )
    footprint = Section(
        "owners",
        "Files per main contributor",
        [Column("owner", "Owner", align="left"), Column("files", "Files")],
        [
            {"owner": owner, "files": count}
            for owner, count in ownership_mod.owner_footprint(data.values())
        ],
    )
    return Report(
        "ownership",
        [files, footprint],
        {
            "metric": options.metric,
            "bus_factor": ownership_mod.bus_factor(data.values()),
            "siloed_files": sum(1 for o in data.values() if o.is_siloed),
        },
    )


def build_hotspots(commits: Sequence[Commit], options: ReportOptions) -> Report:
    ranked = hotspots_mod.hotspots(
        commits, half_life_days=options.half_life_days, limit=options.limit
    )
    section = Section(
        "hotspots",
        "Hotspots",
        [
            Column("path", "Path", align="left"),
            Column("score", "Score"),
            Column("commits", "Commits"),
            Column("churn", "Churn"),
            Column("authors", "Authors"),
            Column("last_changed", "Last changed"),
        ],
        [
            {
                "path": h.path,
                "score": h.score,
                "commits": h.commits,
                "churn": h.churn,
                "authors": h.authors,
                "last_changed": h.last_changed,
            }
            for h in ranked
        ],
    )
    return Report("hotspots", [section], {"half_life_days": options.half_life_days})


def build_timeline(commits: Sequence[Commit], options: ReportOptions) -> Report:
    buckets = timeline_mod.timeline(commits, period=options.period, fill_gaps=options.fill_gaps)
    section = Section(
        "periods",
        f"Activity per {options.period}",
        [
            Column("period", "Period", align="left"),
            Column("commits", "Commits"),
            Column("added", "Added"),
            Column("deleted", "Deleted"),
            Column("authors", "Authors"),
        ],
        [
            {
                "period": b.key,
                "commits": b.commits,
                "added": b.added,
                "deleted": b.deleted,
                "authors": len(b.authors),
            }
            for b in buckets
        ],
    )
    return Report("timeline", [section], {"period": options.period})


def build_rhythm(commits: Sequence[Commit], options: ReportOptions) -> Report:
    grid = timeline_mod.rhythm(commits)
    columns = [Column("day", "Day", align="left")]
    columns += [Column(f"h{hour:02d}", f"{hour:02d}") for hour in range(24)]
    rows = []
    for name, counts in zip(timeline_mod.WEEKDAYS, grid):
        row: dict = {"day": name}
        row.update({f"h{hour:02d}": count for hour, count in enumerate(counts)})
        rows.append(row)
    return Report("rhythm", [Section("grid", "Commits by weekday and hour", columns, rows)])


def build_messages(commits: Sequence[Commit], options: ReportOptions) -> Report:
    stats = messages_mod.message_stats(commits)

    def counted(key: str, title: str, label: str, counter) -> Section:
        ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if options.limit is not None:
            ordered = ordered[: options.limit]
        return Section(
            key,
            title,
            [Column(label, label.capitalize(), align="left"), Column("count", "Count")],
            [{label: name, "count": count} for name, count in ordered],
        )

    return Report(
        "messages",
        [
            counted("kinds", "Commit kinds", "kind", stats.kinds),
            counted("scopes", "Scopes", "scope", stats.scopes),
            counted("fix_prone", "Files most touched by fixes", "path", stats.fix_touches),
        ],
        {
            "commits": stats.total,
            "fix_ratio": stats.fix_ratio,
            "breaking": stats.breaking,
            "empty_subjects": stats.empty_subjects,
            "long_subjects": stats.long_subjects,
        },
    )


def build_compare(commits: Sequence[Commit], options: ReportOptions) -> Report:
    if options.split is None:
        raise ValueError("the compare report needs a split date")
    data = compare_mod.compare_periods(commits, options.split)

    def deltas(key: str, title: str, label: str, items: list[compare_mod.Delta]) -> Section:
        chosen = items if options.limit is None else items[: options.limit]
        return Section(
            key,
            title,
            [
                Column(label, label.capitalize(), align="left"),
                Column("before", "Before"),
                Column("after", "After"),
                Column("change", "Change"),
            ],
            [
                {label: d.key, "before": d.before, "after": d.after, "change": d.change}
                for d in chosen
            ],
        )

    totals = Section(
        "totals",
        "Totals",
        [
            Column("measure", "Measure", align="left"),
            Column("before", "Before"),
            Column("after", "After"),
        ],
        [
            {"measure": "commits", "before": data.commits_before, "after": data.commits_after},
            {"measure": "churn", "before": data.churn_before, "after": data.churn_after},
        ],
    )
    return Report(
        "compare",
        [
            totals,
            deltas("files", "Churn change per file", "path", data.files),
            deltas("authors", "Commit change per author", "author", data.authors),
        ],
        {"split": data.split, "new_authors": data.new_authors, "gone_authors": data.gone_authors},
    )


BUILDERS: dict[str, Builder] = {
    "summary": build_summary,
    "churn": build_churn,
    "dirs": build_dirs,
    "authors": build_authors,
    "cochange": build_cochange,
    "ownership": build_ownership,
    "hotspots": build_hotspots,
    "timeline": build_timeline,
    "rhythm": build_rhythm,
    "messages": build_messages,
    "compare": build_compare,
}
