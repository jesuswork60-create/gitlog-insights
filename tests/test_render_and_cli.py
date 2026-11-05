import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from helpers import MACHINE_LOG

from gitlog_insights.cli import main
from gitlog_insights.render import Column, Report, Section, render


def sample_report():
    columns = [Column("path", "Path", align="left"), Column("score", "Score"), Column("when", "When")]
    rows = [
        {"path": "a|b.py", "score": 1.23456, "when": datetime(2024, 3, 1, 10, tzinfo=timezone.utc)},
        {"path": "long/name.py", "score": 10.0, "when": None},
    ]
    return Report("demo", [Section("files", "Files", columns, rows)], {"note": 1})


class Renderers(unittest.TestCase):
    def test_text_alignment_and_values(self):
        lines = render(sample_report(), "text").splitlines()
        self.assertEqual(lines[0], "Files")
        self.assertEqual(lines[1], "-----")
        self.assertEqual(lines[2], "Path          Score        When")
        self.assertEqual(lines[3], "a|b.py         1.23  2024-03-01")
        self.assertEqual(lines[4], "long/name.py  10.00           -")

    def test_markdown_escapes_pipes(self):
        text = render(sample_report(), "markdown")
        self.assertIn("## Files", text)
        self.assertIn("| --- | ---: | ---: |", text)
        self.assertIn("a\\|b.py", text)

    def test_json_keeps_full_precision(self):
        document = json.loads(render(sample_report(), "json"))
        self.assertEqual(document["report"], "demo")
        self.assertEqual(document["meta"], {"note": 1})
        row = document["sections"]["files"][0]
        self.assertEqual(row["score"], 1.23456)
        self.assertEqual(row["when"], "2024-03-01T10:00:00+00:00")
        self.assertIsNone(document["sections"]["files"][1]["when"])

    def test_csv_round_trip(self):
        rows = list(csv.reader(io.StringIO(render(sample_report(), "csv"))))
        self.assertEqual(rows[0], ["path", "score", "when"])
        self.assertEqual(rows[1][0], "a|b.py")
        self.assertEqual(rows[2][2], "")

    def test_csv_labels_multiple_sections(self):
        report = sample_report()
        report.sections.append(Section("more", "More", [Column("x", "X")], [{"x": 1}]))
        text = render(report, "csv")
        self.assertIn("# files\n", text)
        self.assertIn("\n\n# more\nx\n1\n", text)

    def test_empty_sections(self):
        report = Report("demo", [Section("s", "Nothing", [Column("x", "X")])])
        self.assertIn("(nothing to report)", render(report, "text"))
        self.assertIn("Nothing to report.", render(report, "markdown"))
        self.assertEqual(json.loads(render(report, "json"))["sections"]["s"], [])

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            render(sample_report(), "yaml")


class CliHarness(unittest.TestCase):
    def run_cli(self, *argv, stdin=MACHINE_LOG):
        out, err = io.StringIO(), io.StringIO()
        code = main(list(argv), stdin=io.StringIO(stdin), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def report(self, *argv, stdin=MACHINE_LOG):
        code, out, err = self.run_cli(*argv, "--input", "-", "--format", "json", stdin=stdin)
        self.assertEqual(code, 0, err)
        return json.loads(out)


class Reports(CliHarness):
    def test_summary(self):
        rows = self.report("summary")["sections"]["summary"]
        facts = {row["metric"]: row["value"] for row in rows}
        self.assertEqual(facts["commits"], 3)
        self.assertEqual(facts["authors"], 2)
        self.assertEqual(facts["largest_commit"], "c1")

    def test_churn_follows_renames_by_default(self):
        rows = self.report("churn")["sections"]["files"]
        by_path = {row["path"]: row for row in rows}
        self.assertEqual(by_path["src/new/util.py"]["added"], 21)
        self.assertNotIn("src/old/util.py", by_path)

    def test_no_renames_flag(self):
        rows = self.report("churn", "--no-renames")["sections"]["files"]
        self.assertIn("src/old/util.py", {row["path"] for row in rows})

    def test_churn_sort_and_limit(self):
        rows = self.report("churn", "--sort", "commits", "--limit", "1")["sections"]["files"]
        self.assertEqual([row["path"] for row in rows], ["src/core.py"])

    def test_limit_zero_means_all(self):
        self.assertEqual(len(self.report("churn", "--limit", "0")["sections"]["files"]), 3)

    def test_dirs(self):
        rows = self.report("dirs", "--depth", "1")["sections"]["directories"]
        self.assertEqual(rows[0]["path"], "src")

    def test_authors(self):
        rows = self.report("authors")["sections"]["authors"]
        self.assertEqual(rows[0]["email"], "alpha@example.com")
        self.assertEqual(rows[0]["commits"], 2)

    def test_cochange_and_partner_view(self):
        rows = self.report("cochange", "--min-support", "1")["sections"]["pairs"]
        self.assertTrue(any(r["a"] == "src/core.py" and r["b"] == "src/new/util.py" for r in rows))
        rows = self.report("cochange", "--min-support", "1", "--file", "assets/logo.png")["sections"]["pairs"]
        self.assertEqual(len(rows), 2)

    def test_ownership_meta(self):
        document = self.report("ownership")
        self.assertIn("bus_factor", document["meta"])
        self.assertEqual(document["sections"]["files"][0]["owner"], "alpha@example.com")

    def test_hotspots_timeline_rhythm_messages(self):
        self.assertTrue(self.report("hotspots", "--half-life", "10")["sections"]["hotspots"])
        periods = self.report("timeline", "--period", "day")["sections"]["periods"]
        self.assertEqual([p["period"] for p in periods], ["2024-03-01", "2024-03-02", "2024-03-03"])
        self.assertEqual(len(self.report("rhythm")["sections"]["grid"]), 7)
        document = self.report("messages")
        kinds = {row["kind"]: row["count"] for row in document["sections"]["kinds"]}
        self.assertEqual(kinds, {"feat": 1, "fix": 1, "other": 1})
        self.assertEqual(document["sections"]["fix_prone"][0]["path"], "src/core.py")

    def test_compare(self):
        document = self.report("compare", "--split", "2024-03-02")
        self.assertEqual(document["meta"]["gone_authors"], [])
        totals = {row["measure"]: row for row in document["sections"]["totals"]}
        self.assertEqual(totals["commits"]["before"], 1)
        self.assertEqual(totals["commits"]["after"], 2)

    def test_text_format_default(self):
        code, out, _ = self.run_cli("churn", "--input", "-")
        self.assertEqual(code, 0)
        self.assertIn("src/core.py", out)
        self.assertIn("Files by change", out)


class Filters(CliHarness):
    def test_dates(self):
        rows = self.report("summary", "--since", "2024-03-02", "--until", "2024-03-02")["sections"]["summary"]
        self.assertEqual({r["metric"]: r["value"] for r in rows}["commits"], 1)

    def test_author(self):
        rows = self.report("authors", "--author", "beta")["sections"]["authors"]
        self.assertEqual([r["email"] for r in rows], ["beta@example.com"])

    def test_paths_see_the_current_name(self):
        rows = self.report("churn", "--include", "src/new/")["sections"]["files"]
        self.assertEqual(rows[0]["added"], 21)

    def test_exclude(self):
        rows = self.report("churn", "--exclude", "*.png")["sections"]["files"]
        self.assertNotIn("assets/logo.png", {r["path"] for r in rows})


class Errors(CliHarness):
    def test_bad_date_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            with _quiet_stderr():
                main(["summary", "--since", "soon"], stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(caught.exception.code, 2)

    def test_two_sources(self):
        code, _, err = self.run_cli("summary", "--input", "-", "--repo", ".")
        self.assertEqual(code, 2)
        self.assertIn("choose one", err)

    def test_missing_input_file(self):
        code, _, err = self.run_cli("summary", "--input", "no-such-file.log")
        self.assertEqual(code, 2)
        self.assertIn("no-such-file.log", err)

    def test_strict_mode(self):
        code, _, err = self.run_cli("summary", "--input", "-", "--strict", stdin="garbage\n")
        self.assertEqual(code, 2)
        self.assertIn("line 1", err)

    def test_lenient_mode_warns(self):
        code, _, err = self.run_cli("summary", "--input", "-", stdin="garbage\n" + MACHINE_LOG)
        self.assertEqual(code, 0)
        self.assertIn("ignored 1 unreadable", err)

    def test_negative_limit(self):
        code, _, err = self.run_cli("churn", "--input", "-", "--limit", "-1")
        self.assertEqual(code, 2)
        self.assertIn("--limit", err)

    def test_bad_depth(self):
        code, _, _ = self.run_cli("dirs", "--input", "-", "--depth", "0")
        self.assertEqual(code, 2)

    def test_repo_that_is_not_a_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            code, _, err = self.run_cli("summary", "--repo", folder)
        self.assertEqual(code, 2)
        self.assertTrue(err)


class Files(CliHarness):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def path(self, name):
        return os.path.join(self.folder.name, name)

    def test_snapshot_then_report(self):
        target = self.path("history.jsonl")
        code, _, err = self.run_cli("snapshot", "--input", "-", "-o", target, "--no-renames")
        self.assertEqual(code, 0)
        self.assertIn("saved 3 commits", err)
        code, out, _ = self.run_cli("churn", "--snapshot", target, "--format", "json")
        self.assertEqual(code, 0)
        by_path = {r["path"]: r for r in json.loads(out)["sections"]["files"]}
        # Renames are followed on the way out of the snapshot too.
        self.assertEqual(by_path["src/new/util.py"]["added"], 21)

    def test_snapshot_to_stdout(self):
        code, out, _ = self.run_cli("snapshot", "--input", "-")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 4)

    def test_mailmap_flag_merges_identities(self):
        mailmap = self.path("mailmap")
        with open(mailmap, "w", encoding="utf-8") as handle:
            handle.write("Alpha Dev <alpha@example.com> <beta@example.com>\n")
        rows = self.report("authors", "--mailmap", mailmap)["sections"]["authors"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["commits"], 3)

    def test_config_file(self):
        config = self.path("settings.toml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write(
                '[filters]\nexclude = ["*.png"]\nexclude_authors = ["beta"]\n'
                '[cochange]\nmin_support = 1\n'
            )
        document = self.report("cochange", "--config", config)
        self.assertEqual(document["meta"]["min_support"], 1)
        rows = self.report("churn", "--config", config)["sections"]["files"]
        self.assertNotIn("assets/logo.png", {r["path"] for r in rows})

    def test_cli_flag_overrides_config(self):
        config = self.path("settings.toml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("[cochange]\nmin_support = 5\n")
        document = self.report("cochange", "--config", config, "--min-support", "1")
        self.assertEqual(document["meta"]["min_support"], 1)

    def test_bad_config_is_reported(self):
        config = self.path("settings.toml")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write("[filters]\nexcludes = []\n")
        code, _, err = self.run_cli("summary", "--input", "-", "--config", config)
        self.assertEqual(code, 2)
        self.assertIn("excludes", err)


class _quiet_stderr:
    """argparse writes usage errors straight to sys.stderr."""

    def __enter__(self):
        import sys

        self._saved = sys.stderr
        sys.stderr = io.StringIO()

    def __exit__(self, *exc_info):
        import sys

        sys.stderr = self._saved


@unittest.skipUnless(shutil.which("git"), "git is not available")
class RealRepository(CliHarness):
    """End to end against a throwaway repository in a temporary directory."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = self.folder.name
        self.environment = dict(
            os.environ,
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME="Alpha Dev",
            GIT_AUTHOR_EMAIL="alpha@example.com",
            GIT_COMMITTER_NAME="Alpha Dev",
            GIT_COMMITTER_EMAIL="alpha@example.com",
        )
        self.git("init", "-q")

    def git(self, *argv, **extra_env):
        environment = dict(self.environment, **extra_env)
        subprocess.run(
            ["git", *argv], cwd=self.repo, env=environment, check=True, capture_output=True
        )

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self, message, day, **extra_env):
        stamp = f"2024-03-{day:02d}T12:00:00+00:00"
        self.git("add", "-A")
        self.git(
            "commit", "-q", "-m", message,
            GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp, **extra_env,
        )

    def repo_report(self, *argv):
        with _env_without_git_settings():
            code, out, err = self.run_cli(*argv, "--repo", self.repo, "--format", "json")
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_empty_repository_is_not_an_error(self):
        rows = self.repo_report("summary")["sections"]["summary"]
        self.assertEqual({r["metric"]: r["value"] for r in rows}["commits"], 0)

    def test_history_with_rename_unicode_and_two_authors(self):
        self.write("src/first.py", "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\n")
        self.write("docs/café.md", "words\n")
        self.commit("initial import", 1)
        self.git("mv", "src/first.py", "src/second.py")
        self.commit("rename the module", 2)
        self.write("src/second.py", "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\n")
        self.write("docs/café.md", "more words\n")
        self.commit(
            "fix: extend the module", 3,
            GIT_AUTHOR_NAME="Beta Dev", GIT_AUTHOR_EMAIL="beta@example.com",
        )

        files = {r["path"]: r for r in self.repo_report("churn")["sections"]["files"]}
        self.assertEqual(set(files), {"src/second.py", "docs/café.md"})
        self.assertEqual(files["src/second.py"]["commits"], 3)
        self.assertEqual(files["src/second.py"]["added"], 9)
        self.assertEqual(files["src/second.py"]["authors"], 2)

        authors = self.repo_report("authors")["sections"]["authors"]
        self.assertEqual([a["commits"] for a in authors], [2, 1])

        pairs = self.repo_report("cochange")["sections"]["pairs"]
        self.assertEqual(pairs[0]["support"], 2)

    def test_merge_commit_is_recognised(self):
        self.write("a.txt", "a\n")
        self.commit("first", 1)
        self.git("checkout", "-q", "-b", "topic")
        self.write("b.txt", "b\n")
        self.commit("on topic", 2)
        self.git("checkout", "-q", "-")
        self.write("c.txt", "c\n")
        self.commit("on main", 3)
        self.git("merge", "-q", "--no-ff", "-m", "Merge topic", "topic")
        rows = self.repo_report("summary")["sections"]["summary"]
        facts = {r["metric"]: r["value"] for r in rows}
        self.assertEqual((facts["commits"], facts["merges"]), (4, 1))

    def test_repository_settings_file_is_discovered(self):
        self.write("keep.py", "x\n")
        self.write("drop.lock", "x\n")
        self.write(".gitlog-insights.toml", '[filters]\nexclude = ["*.lock", "*.toml"]\n')
        self.commit("first", 1)
        files = {r["path"] for r in self.repo_report("churn")["sections"]["files"]}
        self.assertEqual(files, {"keep.py"})

    def test_rev_selects_a_range(self):
        self.write("a.txt", "a\n")
        self.commit("first", 1)
        self.write("b.txt", "b\n")
        self.commit("second", 2)
        files = self.repo_report("churn", "--rev", "HEAD~1..HEAD")["sections"]["files"]
        self.assertEqual([r["path"] for r in files], ["b.txt"])

    def test_bad_revision_reports_the_git_error(self):
        self.write("a.txt", "a\n")
        self.commit("first", 1)
        with _env_without_git_settings():
            code, _, err = self.run_cli("summary", "--repo", self.repo, "--rev", "no-such-branch")
        self.assertEqual(code, 2)
        self.assertTrue(err.strip())

    def test_option_like_revision_is_refused(self):
        with _env_without_git_settings():
            code, _, err = self.run_cli("summary", "--repo", self.repo, "--rev=--output=x")
        self.assertEqual(code, 2)
        self.assertIn("refusing", err)


class _env_without_git_settings:
    """Keep a developer's global git settings from influencing ``git log`` here."""

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")}
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        os.environ["GIT_CONFIG_SYSTEM"] = os.devnull

    def __exit__(self, *exc_info):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
