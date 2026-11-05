"""Command line front end."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, Iterator, Sequence, TextIO

from . import __version__
from .collect import GitError, stream_git_log
from .config import Config, ConfigError, discover_config, load_config
from .dates import PERIODS, parse_bound
from .filters import CommitFilter
from .identity import IdentityResolver, Mailmap, MailmapError
from .models import Commit
from .parser import LogParseError, LogParser
from .render import FORMATS, render
from .renames import follow_renames
from .reports import BUILDERS, ReportOptions
from .store import SnapshotError, read_snapshot, write_snapshot

EXIT_OK = 0
EXIT_ERROR = 2


class UsageError(Exception):
    pass


def _bound(end: bool):
    def convert(text: str):
        try:
            return parse_bound(text, end=end)
        except ValueError:
            raise argparse.ArgumentTypeError(f"cannot read date {text!r}") from None

    return convert


def _common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    source = common.add_argument_group("history source")
    source.add_argument("--repo", default=None, help="repository to read (default: current directory)")
    source.add_argument("--input", default=None, help="saved 'git log --numstat' output, or - for stdin")
    source.add_argument("--snapshot", default=None, help="read a snapshot made by the snapshot command")
    source.add_argument("--rev", default=None, help="revision or range to log")
    source.add_argument("--all", action="store_true", dest="all_refs", help="log every ref")
    source.add_argument("--strict", action="store_true", help="fail on lines the parser does not understand")

    narrowing = common.add_argument_group("filters")
    narrowing.add_argument("--since", type=_bound(False), help="date, or an age like 30d, 2w, 6m, 1y")
    narrowing.add_argument("--until", type=_bound(True), help="date, or an age like 30d")
    narrowing.add_argument("--author", action="append", default=[], help="name or email substring; repeatable")
    narrowing.add_argument("--exclude-author", action="append", default=[], help="repeatable")
    narrowing.add_argument("--include", action="append", default=[], help="path pattern; repeatable")
    narrowing.add_argument("--exclude", action="append", default=[], help="path pattern; repeatable")
    narrowing.add_argument("--no-merges", action="store_true")
    narrowing.add_argument("--no-renames", action="store_true", help="keep each file's history under the name it had")

    identity = common.add_argument_group("identity and settings")
    identity.add_argument("--mailmap", default=None, help="mailmap file to apply")
    identity.add_argument("--config", default=None, help="settings file (default: .gitlog-insights.toml in the repo)")

    output = common.add_argument_group("output")
    output.add_argument("--format", choices=sorted(FORMATS), default="text", dest="output_format")
    output.add_argument("--limit", type=int, default=20, help="rows per table; 0 means all")
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitlog-insights",
        description="Report on churn, authors, ownership and co-change from git history.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    common = _common_parser()

    commands.add_parser("summary", parents=[common], help="overview of the history")
    churn = commands.add_parser("churn", parents=[common], help="files by lines changed")
    churn.add_argument("--sort", choices=["churn", "commits", "authors", "added", "deleted", "path"])
    dirs = commands.add_parser("dirs", parents=[common], help="directories by lines changed")
    dirs.add_argument("--depth", type=int, default=1)
    dirs.add_argument("--sort", choices=["churn", "commits", "authors", "added", "deleted", "path"])
    authors = commands.add_parser("authors", parents=[common], help="activity per author")
    authors.add_argument("--sort", choices=["commits", "churn", "files", "days"])
    cochange = commands.add_parser("cochange", parents=[common], help="files that change together")
    cochange.add_argument("--min-support", type=int)
    cochange.add_argument("--max-files", type=int)
    cochange.add_argument("--min-coupling", type=float, default=0.0)
    cochange.add_argument("--file", help="only show partners of this file")
    ownership = commands.add_parser("ownership", parents=[common], help="main contributor per file")
    ownership.add_argument("--metric", choices=["lines", "commits"], default="lines")
    hotspots = commands.add_parser("hotspots", parents=[common], help="recent concentrated change")
    hotspots.add_argument("--half-life", type=float, dest="half_life_days")
    timeline = commands.add_parser("timeline", parents=[common], help="activity per calendar period")
    timeline.add_argument("--period", choices=PERIODS, default="month")
    timeline.add_argument("--no-gaps", action="store_true", help="omit periods without commits")
    commands.add_parser("rhythm", parents=[common], help="commits by weekday and hour")
    commands.add_parser("messages", parents=[common], help="commit kinds and fix-prone files")
    compare = commands.add_parser("compare", parents=[common], help="before and after a date")
    compare.add_argument("--split", type=_bound(False), required=True, help="date dividing the two periods")
    snapshot = commands.add_parser("snapshot", parents=[common], help="save parsed history to a file")
    snapshot.add_argument("--output", "-o", default="-", help="file to write, or - for stdout")
    return parser


def _load_settings(args: argparse.Namespace) -> Config:
    if args.config:
        return load_config(args.config)
    if args.input or args.snapshot:
        return Config()
    return discover_config(args.repo or ".")


def _build_resolver(args: argparse.Namespace, config: Config) -> IdentityResolver | None:
    mailmap_path = args.mailmap or config.mailmap
    mailmap = None
    if mailmap_path:
        if not args.mailmap and not os.path.isabs(mailmap_path):
            mailmap_path = os.path.join(args.repo or ".", mailmap_path)
        try:
            with open(mailmap_path, encoding="utf-8") as handle:
                mailmap = Mailmap.parse(handle.read())
        except OSError as exc:
            raise UsageError(f"cannot read mailmap {mailmap_path}: {exc.strerror}") from exc
    if mailmap is None and not config.aliases:
        return None
    return IdentityResolver(mailmap, config.aliases)


def _read_commits(args: argparse.Namespace, parser: LogParser, stdin: TextIO) -> Iterator[Commit]:
    sources = sum(1 for value in (args.input, args.snapshot, args.repo) if value)
    if sources > 1:
        raise UsageError("choose one of --repo, --input and --snapshot")
    if args.snapshot:
        with open(args.snapshot, encoding="utf-8") as handle:
            yield from read_snapshot(handle)
    elif args.input == "-":
        yield from parser.parse(stdin)
    elif args.input:
        with open(args.input, encoding="utf-8", errors="replace") as handle:
            yield from parser.parse(handle)
    else:
        lines = stream_git_log(
            args.repo or ".", since=args.since, revision=args.rev, all_refs=args.all_refs
        )
        yield from parser.parse(lines)


def _commit_pipeline(
    args: argparse.Namespace, config: Config, parser: LogParser, stdin: TextIO
) -> Iterable[Commit]:
    """Source, then identities, then renames, then filters.

    Order matters: author filters should see corrected identities, and path
    filters should see the current name of a file. Renames must run before any
    filter can remove the commits that record them.
    """
    commits: Iterable[Commit] = _read_commits(args, parser, stdin)
    resolver = _build_resolver(args, config)
    if resolver is not None:
        commits = resolver.apply(commits)
    if not args.no_renames:
        commits = follow_renames(commits)
    commit_filter = CommitFilter(
        since=args.since,
        until=args.until,
        authors=tuple(args.author),
        exclude_authors=tuple(args.exclude_author) + config.exclude_authors,
        include=tuple(args.include) + config.include,
        exclude=tuple(args.exclude) + config.exclude,
        include_merges=not args.no_merges,
    )
    return commit_filter.apply(commits)


def _report_options(args: argparse.Namespace, config: Config) -> ReportOptions:
    if args.limit < 0:
        raise UsageError("--limit cannot be negative")
    min_support = getattr(args, "min_support", None)
    max_files = getattr(args, "max_files", None)
    half_life = getattr(args, "half_life_days", None)
    depth = getattr(args, "depth", 1)
    if depth < 1:
        raise UsageError("--depth must be at least 1")
    if half_life is not None and half_life <= 0:
        raise UsageError("--half-life must be positive")
    return ReportOptions(
        limit=args.limit or None,
        sort=getattr(args, "sort", None),
        depth=depth,
        period=getattr(args, "period", "month"),
        fill_gaps=not getattr(args, "no_gaps", False),
        min_support=config.min_support if min_support is None else min_support,
        max_files=config.max_files if max_files is None else max_files,
        min_coupling=getattr(args, "min_coupling", 0.0),
        file=getattr(args, "file", None),
        metric=getattr(args, "metric", "lines"),
        half_life_days=config.half_life_days if half_life is None else half_life,
        split=getattr(args, "split", None),
    )


def _run(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    config = _load_settings(args)
    parser = LogParser(strict=args.strict)
    commits = _commit_pipeline(args, config, parser, stdin)

    if args.command == "snapshot":
        if args.output == "-":
            count = write_snapshot(commits, stdout)
        else:
            with open(args.output, "w", encoding="utf-8") as handle:
                count = write_snapshot(commits, handle)
        print(f"saved {count} commits", file=stderr)
        return EXIT_OK

    options = _report_options(args, config)
    history = list(commits)
    report = BUILDERS[args.command](history, options)
    stdout.write(render(report, args.output_format))
    if parser.skipped_lines or parser.skipped_commits:
        print(
            f"warning: ignored {parser.skipped_lines} unreadable lines "
            f"and {parser.skipped_commits} incomplete commits",
            file=stderr,
        )
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        return _run(args, stdin, stdout, stderr)
    except BrokenPipeError:
        # The reader went away, as with `| head`. Not an error worth reporting.
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass
        return EXIT_OK
    except (
        ConfigError,
        GitError,
        LogParseError,
        MailmapError,
        SnapshotError,
        UsageError,
        ValueError,
    ) as exc:
        print(f"gitlog-insights: {exc}", file=stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"gitlog-insights: {exc.filename or 'error'}: {exc.strerror}", file=stderr)
        return EXIT_ERROR
