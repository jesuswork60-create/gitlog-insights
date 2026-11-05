"""Dates, filters, identities, renames, snapshots and settings."""

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from helpers import ALPHA, BETA, at, change, commit

from gitlog_insights.config import ConfigError, Config, discover_config, load_config, parse_config
from gitlog_insights.dates import bucket_key, iter_bucket_keys, parse_bound, parse_git_date
from gitlog_insights.filters import CommitFilter, match_path
from gitlog_insights.identity import IdentityResolver, Mailmap, MailmapError
from gitlog_insights.models import Author
from gitlog_insights.renames import follow_renames
from gitlog_insights.store import SnapshotError, read_snapshot, write_snapshot


class GitDates(unittest.TestCase):
    def test_each_spelling(self):
        expected = datetime(2024, 3, 1, 10, tzinfo=timezone.utc)
        for text in (
            "2024-03-01T10:00:00+00:00",
            "2024-03-01T10:00:00Z",
            "2024-03-01 10:00:00 +0000",
            "Fri Mar 1 10:00:00 2024 +0000",
            "Fri, 1 Mar 2024 10:00:00 +0000",
            "1709287200",
            "1709287200 +0000",
        ):
            self.assertEqual(parse_git_date(text), expected, text)

    def test_raw_form_keeps_the_offset(self):
        parsed = parse_git_date("1709287200 +0530")
        self.assertEqual(parsed.utcoffset(), timedelta(hours=5, minutes=30))
        self.assertEqual(parsed.astimezone(timezone.utc).hour, 10)

    def test_naive_iso_is_taken_as_utc(self):
        self.assertEqual(parse_git_date("2024-03-01T10:00:00").tzinfo, timezone.utc)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_git_date("yesterday-ish")


class Bounds(unittest.TestCase):
    def test_bare_date_covers_the_day_as_end(self):
        self.assertEqual(parse_bound("2024-03-01").hour, 0)
        end = parse_bound("2024-03-01", end=True)
        self.assertEqual((end.hour, end.minute), (23, 59))

    def test_relative_ages_use_the_given_clock(self):
        now = datetime(2024, 3, 31, tzinfo=timezone.utc)
        self.assertEqual(parse_bound("30d", now=now), datetime(2024, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(parse_bound("2w", now=now), now - timedelta(days=14))
        self.assertEqual(parse_bound("1y", now=now), now - timedelta(days=365))

    def test_offset_is_kept(self):
        self.assertEqual(parse_bound("2024-03-01T12:00:00+02:00").utcoffset(), timedelta(hours=2))

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_bound("soon")


class Buckets(unittest.TestCase):
    def test_keys_are_in_utc(self):
        late = datetime(2024, 3, 1, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
        self.assertEqual(bucket_key(late, "day"), "2024-03-02")
        self.assertEqual(bucket_key(late, "month"), "2024-03")
        self.assertEqual(bucket_key(late, "year"), "2024")

    def test_iso_week_can_belong_to_the_next_year(self):
        self.assertEqual(bucket_key(datetime(2024, 12, 30, tzinfo=timezone.utc), "week"), "2025-W01")

    def test_unknown_period(self):
        with self.assertRaises(ValueError):
            bucket_key(at(1), "fortnight")
        with self.assertRaises(ValueError):
            list(iter_bucket_keys(at(1), at(2), "fortnight"))

    def test_iterating_months_crosses_years(self):
        first = datetime(2023, 11, 15, tzinfo=timezone.utc)
        last = datetime(2024, 2, 1, tzinfo=timezone.utc)
        self.assertEqual(
            list(iter_bucket_keys(first, last, "month")),
            ["2023-11", "2023-12", "2024-01", "2024-02"],
        )

    def test_iterating_days_and_weeks(self):
        self.assertEqual(
            list(iter_bucket_keys(at(1), at(3), "day")),
            ["2024-03-01", "2024-03-02", "2024-03-03"],
        )
        # Friday 1 March and Monday 4 March fall in consecutive ISO weeks.
        self.assertEqual(list(iter_bucket_keys(at(1), at(4), "week")), ["2024-W09", "2024-W10"])

    def test_iterating_years(self):
        first = datetime(2022, 6, 1, tzinfo=timezone.utc)
        self.assertEqual(list(iter_bucket_keys(first, at(1), "year")), ["2022", "2023", "2024"])

    def test_every_key_matches_bucket_key_across_a_year_boundary(self):
        first = datetime(2020, 12, 20, tzinfo=timezone.utc)
        last = datetime(2021, 1, 20, tzinfo=timezone.utc)
        keys = list(iter_bucket_keys(first, last, "week"))
        self.assertEqual(keys[0], bucket_key(first, "week"))
        self.assertEqual(keys[-1], bucket_key(last, "week"))
        self.assertEqual(len(keys), len(set(keys)))


class PathMatching(unittest.TestCase):
    def test_directory_pattern(self):
        self.assertTrue(match_path("docs/a/b.md", "docs/"))
        self.assertFalse(match_path("mydocs/a.md", "docs/"))

    def test_basename_pattern_at_any_depth(self):
        self.assertTrue(match_path("a/b/c.lock", "*.lock"))
        self.assertTrue(match_path("c.lock", "*.lock"))
        self.assertFalse(match_path("a.lock/c.txt", "*.lock"))

    def test_path_pattern(self):
        self.assertTrue(match_path("src/a.py", "src/*.py"))
        self.assertFalse(match_path("lib/a.py", "src/*.py"))

    def test_bare_directory_name_matches_its_contents(self):
        self.assertTrue(match_path("vendor/x/y.c", "vendor"))
        self.assertFalse(match_path("vendored/x.c", "vendor"))

    def test_exact_file(self):
        self.assertTrue(match_path("setup.py", "setup.py"))
        self.assertTrue(match_path("pkg/setup.py", "setup.py"))


class Filtering(unittest.TestCase):
    def setUp(self):
        self.history = [
            commit("c", at(3), change("src/a.py"), change("docs/a.md"), author=BETA),
            commit("m", at(2), parents=("x", "y")),
            commit("a", at(1), change("docs/b.md")),
        ]

    def shas(self, **options):
        return [c.sha for c in CommitFilter(**options).apply(self.history)]

    def test_no_rules_keeps_everything(self):
        self.assertEqual(self.shas(), ["c", "m", "a"])

    def test_date_bounds_are_inclusive(self):
        self.assertEqual(self.shas(since=at(2)), ["c", "m"])
        self.assertEqual(self.shas(until=at(2)), ["m", "a"])

    def test_author_match_covers_name_and_email_without_case(self):
        self.assertEqual(self.shas(authors=("BETA",)), ["c"])
        self.assertEqual(self.shas(authors=("alpha@example",)), ["m", "a"])
        self.assertEqual(self.shas(exclude_authors=("beta",)), ["m", "a"])

    def test_exclude_author_beats_include(self):
        self.assertEqual(self.shas(authors=("dev",), exclude_authors=("beta",)), ["m", "a"])

    def test_merges_can_be_dropped(self):
        self.assertEqual(self.shas(include_merges=False), ["c", "a"])

    def test_path_rules_narrow_changes_and_drop_empty_commits(self):
        kept = list(CommitFilter(include=("src/",)).apply(self.history))
        self.assertEqual([c.sha for c in kept], ["c"])
        self.assertEqual(kept[0].paths, ["src/a.py"])

    def test_filtering_does_not_mutate_the_input(self):
        list(CommitFilter(include=("src/",)).apply(self.history))
        self.assertEqual(len(self.history[0].changes), 2)

    def test_exclude_beats_include(self):
        kept = list(CommitFilter(include=("docs/",), exclude=("*a.md",)).apply(self.history))
        self.assertEqual([c.sha for c in kept], ["a"])


class MailmapFile(unittest.TestCase):
    def resolve(self, text, name, email):
        return Mailmap.parse(text).resolve(Author(name, email))

    def test_name_only_form(self):
        self.assertEqual(
            self.resolve("Proper Name <commit@example.com>", "typo", "commit@example.com"),
            Author("Proper Name", "commit@example.com"),
        )

    def test_email_only_form(self):
        self.assertEqual(
            self.resolve("<new@example.com> <old@example.com>", "A", "old@example.com"),
            Author("A", "new@example.com"),
        )

    def test_name_and_email_form(self):
        self.assertEqual(
            self.resolve("Proper <new@example.com> <old@example.com>", "A", "old@example.com"),
            Author("Proper", "new@example.com"),
        )

    def test_four_field_form_needs_the_commit_name(self):
        text = "Proper <new@example.com> Wrong Name <shared@example.com>"
        self.assertEqual(self.resolve(text, "Wrong Name", "shared@example.com").name, "Proper")
        self.assertEqual(self.resolve(text, "Other", "shared@example.com").name, "Other")

    def test_specific_rule_beats_email_rule_in_any_order(self):
        text = (
            "Generic <g@example.com> <shared@example.com>\n"
            "Specific <s@example.com> Wrong Name <shared@example.com>\n"
        )
        self.assertEqual(self.resolve(text, "Wrong Name", "shared@example.com").name, "Specific")
        self.assertEqual(self.resolve(text, "Anyone", "shared@example.com").name, "Generic")

    def test_comments_blank_lines_and_case(self):
        text = "# header\n\nProper <new@example.com> <OLD@example.com>  # trailing\n"
        self.assertEqual(len(Mailmap.parse(text)), 1)
        self.assertEqual(self.resolve(text, "A", "old@EXAMPLE.com").email, "new@example.com")

    def test_unknown_author_is_unchanged(self):
        self.assertEqual(self.resolve("P <n@example.com> <o@example.com>", "A", "z@example.com"), Author("A", "z@example.com"))

    def test_bad_line_is_reported(self):
        with self.assertRaises(MailmapError) as caught:
            Mailmap.parse("fine <a@example.com>\nno brackets here\n")
        self.assertIn("line 2", str(caught.exception))


class Resolver(unittest.TestCase):
    def test_alias_runs_after_the_mailmap(self):
        mailmap = Mailmap.parse("<mid@example.com> <old@example.com>")
        resolver = IdentityResolver(mailmap, {"MID@example.com": "final@example.com"})
        self.assertEqual(resolver.resolve(Author("A", "old@example.com")).email, "final@example.com")

    def test_apply_rewrites_only_what_changes(self):
        resolver = IdentityResolver(None, {"alpha@example.com": "merged@example.com"})
        history = [commit("a", at(1)), commit("b", at(1), author=BETA)]
        out = list(resolver.apply(history))
        self.assertEqual(out[0].author.email, "merged@example.com")
        self.assertIs(out[1], history[1])
        self.assertEqual(history[0].author, ALPHA)


class RenameFollowing(unittest.TestCase):
    def paths(self, history):
        return [c.paths for c in follow_renames(history)]

    def test_history_moves_to_the_newest_name(self):
        history = [
            commit("3", at(3), change("c.py")),
            commit("2", at(2), change("c.py", old="b.py")),
            commit("1", at(1), change("b.py")),
        ]
        self.assertEqual(self.paths(history), [["c.py"], ["c.py"], ["c.py"]])

    def test_chain_of_renames(self):
        history = [
            commit("3", at(3), change("c.py", old="b.py")),
            commit("2", at(2), change("b.py", old="a.py")),
            commit("1", at(1), change("a.py")),
        ]
        self.assertEqual(self.paths(history), [["c.py"], ["c.py"], ["c.py"]])

    def test_swap_in_one_commit_keeps_files_apart(self):
        history = [
            commit("2", at(2), change("b", old="a"), change("a", old="b")),
            commit("1", at(1), change("a", 10), change("b", 20)),
        ]
        out = list(follow_renames(history))
        self.assertEqual(out[0].paths, ["b", "a"])
        by_path = {c.path: c.added for c in out[1].changes}
        self.assertEqual(by_path, {"b": 10, "a": 20})

    def test_name_reused_after_a_rename(self):
        history = [
            commit("3", at(3), change("a.py")),  # a new file took the old name
            commit("2", at(2), change("b.py", old="a.py")),
            commit("1", at(1), change("a.py")),
        ]
        self.assertEqual(self.paths(history), [["a.py"], ["b.py"], ["b.py"]])

    def test_commits_without_renames_are_passed_through(self):
        original = commit("1", at(1), change("a.py"))
        self.assertIs(next(follow_renames([original])), original)


class Snapshots(unittest.TestCase):
    def test_round_trip(self):
        history = [
            commit(
                "abc",
                datetime(2024, 3, 1, 10, tzinfo=timezone(timedelta(hours=2))),
                change("é/a.py", 1, 2, old="b.py"),
                change("logo.png", None, None),
                subject="unicode é",
                parents=("x", "y"),
            )
        ]
        buffer = io.StringIO()
        self.assertEqual(write_snapshot(history, buffer), 1)
        buffer.seek(0)
        [restored] = read_snapshot(buffer)
        self.assertEqual(restored, history[0])
        self.assertEqual(restored.authored_at.utcoffset(), timedelta(hours=2))

    def test_empty_snapshot(self):
        buffer = io.StringIO()
        write_snapshot([], buffer)
        buffer.seek(0)
        self.assertEqual(list(read_snapshot(buffer)), [])

    def test_foreign_files_are_refused(self):
        for text in ("", "hello\n", '{"format": "other", "version": 1}\n', "[]\n"):
            with self.assertRaises(SnapshotError, msg=text):
                read_snapshot(io.StringIO(text))

    def test_future_version_is_refused(self):
        with self.assertRaises(SnapshotError) as caught:
            read_snapshot(io.StringIO('{"format": "gitlog-insights-snapshot", "version": 99}\n'))
        self.assertIn("99", str(caught.exception))

    def test_damaged_row_names_its_line(self):
        text = '{"format": "gitlog-insights-snapshot", "version": 1}\n{"sha": "x"}\n'
        with self.assertRaises(SnapshotError) as caught:
            list(read_snapshot(io.StringIO(text)))
        self.assertIn("line 2", str(caught.exception))


class Settings(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(parse_config({}), Config())

    def test_full_document(self):
        config = parse_config(
            {
                "filters": {"exclude": ["vendor/"], "include": ["src/"], "exclude_authors": ["bot"]},
                "identity": {"mailmap": ".mailmap", "aliases": {"a@example.com": "b@example.com"}},
                "cochange": {"min_support": 3, "max_files": 10},
                "hotspots": {"half_life_days": 30},
            }
        )
        self.assertEqual(config.exclude, ("vendor/",))
        self.assertEqual(config.aliases, {"a@example.com": "b@example.com"})
        self.assertEqual(config.min_support, 3)
        self.assertEqual(config.half_life_days, 30.0)

    def test_misspellings_and_bad_types_are_errors(self):
        for data in (
            {"filter": {}},
            {"filters": {"excludes": []}},
            {"filters": {"exclude": "vendor/"}},
            {"filters": {"exclude": [1]}},
            {"identity": {"mailmap": 3}},
            {"identity": {"aliases": {"a": 1}}},
            {"cochange": {"min_support": 0}},
            {"cochange": {"max_files": True}},
            {"hotspots": {"half_life_days": -1}},
            {"hotspots": {"half_life_days": "long"}},
        ):
            with self.assertRaises(ConfigError, msg=str(data)):
                parse_config(data)

    def test_load_and_discover(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(discover_config(folder), Config())
            path = os.path.join(folder, ".gitlog-insights.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('[filters]\nexclude = ["a/"]\n')
            self.assertEqual(discover_config(folder).exclude, ("a/",))
            self.assertEqual(load_config(path).exclude, ("a/",))

    def test_load_errors_name_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "bad.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not toml at all [")
            with self.assertRaises(ConfigError) as caught:
                load_config(path)
            self.assertIn("bad.toml", str(caught.exception))
            with self.assertRaises(ConfigError):
                load_config(os.path.join(folder, "missing.toml"))


if __name__ == "__main__":
    unittest.main()
