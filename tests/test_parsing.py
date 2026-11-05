import unittest
from datetime import datetime, timedelta, timezone

from helpers import DEFAULT_LOG, MACHINE_LOG, log_lines

from gitlog_insights.models import Author
from gitlog_insights.numstat import parse_numstat, split_rename, unquote_path
from gitlog_insights.parser import LogParseError, LogParser, parse_author, parse_log


class NumstatRows(unittest.TestCase):
    def test_plain_row(self):
        row = parse_numstat("12\t4\tsrc/app.py")
        self.assertEqual((row.path, row.added, row.deleted), ("src/app.py", 12, 4))
        self.assertFalse(row.is_binary)
        self.assertFalse(row.is_rename)
        self.assertEqual(row.churn, 16)

    def test_binary_row_has_no_line_counts(self):
        row = parse_numstat("-\t-\tlogo.png")
        self.assertTrue(row.is_binary)
        self.assertEqual(row.churn, 0)

    def test_non_rows_are_rejected(self):
        for text in ("", "hello", "1\t2", "x\t2\tfile", "1 2 file"):
            self.assertIsNone(parse_numstat(text), text)

    def test_path_with_spaces(self):
        self.assertEqual(parse_numstat("1\t1\tmy docs/read me.txt").path, "my docs/read me.txt")


class Renames(unittest.TestCase):
    def test_whole_path(self):
        self.assertEqual(split_rename("old.txt => new.txt"), ("old.txt", "new.txt"))

    def test_brace_in_middle(self):
        self.assertEqual(split_rename("src/{a => b}/f.py"), ("src/a/f.py", "src/b/f.py"))

    def test_brace_with_empty_old_side(self):
        self.assertEqual(split_rename("{ => lib}/a.py"), ("a.py", "lib/a.py"))

    def test_brace_with_empty_new_side(self):
        self.assertEqual(split_rename("lib/{old => }/a.py"), ("lib/old/a.py", "lib/a.py"))

    def test_brace_at_end(self):
        self.assertEqual(split_rename("src/{a.py => b.py}"), ("src/a.py", "src/b.py"))

    def test_not_a_rename(self):
        self.assertEqual(split_rename("plain/file.py"), (None, "plain/file.py"))

    def test_quoted_sides_of_a_rename(self):
        self.assertEqual(split_rename('"a\\tb.txt" => c.txt'), ("a\tb.txt", "c.txt"))

    def test_row_records_old_path(self):
        row = parse_numstat("0\t0\tsrc/{a => b}/f.py")
        self.assertEqual(row.old_path, "src/a/f.py")
        self.assertEqual(row.path, "src/b/f.py")
        self.assertTrue(row.is_rename)


class Unquoting(unittest.TestCase):
    def test_unquoted_text_is_untouched(self):
        self.assertEqual(unquote_path("plain.txt"), "plain.txt")
        self.assertEqual(unquote_path('"'), '"')

    def test_octal_bytes_decode_as_utf8(self):
        self.assertEqual(unquote_path('"caf\\303\\251.txt"'), "café.txt")

    def test_named_escapes(self):
        self.assertEqual(unquote_path('"a\\tb\\n\\"c\\\\"'), 'a\tb\n"c\\')

    def test_invalid_utf8_is_replaced_not_fatal(self):
        self.assertIn("�", unquote_path('"\\377x"'))

    def test_unknown_escape_is_kept_literally(self):
        self.assertEqual(unquote_path('"a\\qb"'), "a\\qb")


class Authors(unittest.TestCase):
    def test_name_and_email(self):
        self.assertEqual(parse_author("Alpha Dev <a@example.com>"), Author("Alpha Dev", "a@example.com"))

    def test_empty_email(self):
        self.assertEqual(parse_author("Alpha Dev <>"), Author("Alpha Dev", ""))

    def test_no_brackets(self):
        self.assertEqual(parse_author("Alpha Dev"), Author("Alpha Dev", ""))

    def test_key_ignores_email_case_and_falls_back_to_name(self):
        self.assertEqual(Author("A", "X@Example.com").key, "x@example.com")
        self.assertEqual(Author("Some One", "").key, "some one")


class MachineLayout(unittest.TestCase):
    def setUp(self):
        self.commits = list(parse_log(log_lines(MACHINE_LOG)))

    def test_counts_and_order(self):
        self.assertEqual([c.sha for c in self.commits], ["c3", "c2", "c1"])

    def test_header_fields(self):
        newest = self.commits[0]
        self.assertEqual(newest.author, Author("Beta Dev", "beta@example.com"))
        self.assertEqual(newest.subject, "feat(core): add parser")
        self.assertEqual(newest.parents, ("c2",))
        self.assertEqual(newest.authored_at.utcoffset(), timedelta(hours=1))

    def test_root_commit_has_no_parents(self):
        self.assertEqual(self.commits[-1].parents, ())
        self.assertFalse(self.commits[-1].is_merge)

    def test_totals_skip_binary_rows(self):
        self.assertEqual(self.commits[0].added, 11)
        self.assertEqual(self.commits[0].deleted, 2)
        self.assertEqual(len(self.commits[0].changes), 3)

    def test_subject_may_hold_anything_but_the_separators(self):
        line = "\x1eabc\x1f\x1fA\x1fa@example.com\x1f2024-01-01T00:00:00Z\x1fcommit deadbeef => 1\t2\tx\n"
        [only] = parse_log([line])
        self.assertEqual(only.subject, "commit deadbeef => 1\t2\tx")


class DefaultLayout(unittest.TestCase):
    def setUp(self):
        self.commits = list(parse_log(DEFAULT_LOG.splitlines(keepends=True)))

    def test_decorated_commit_line_and_merge_header(self):
        merge = self.commits[0]
        self.assertTrue(merge.sha.startswith("aaaaaaa"))
        self.assertEqual(merge.parents, ("bbbbbbb", "ccccccc"))
        self.assertTrue(merge.is_merge)
        self.assertEqual(merge.changes, [])

    def test_subject_is_the_first_message_line(self):
        self.assertEqual(self.commits[1].subject, "Rewrite the loader")

    def test_indented_body_is_not_read_as_numstat(self):
        self.assertEqual(self.commits[1].paths, ["loader.py", "renamed.py"])

    def test_default_date_format(self):
        expected = datetime(2024, 3, 3, 10, tzinfo=timezone.utc)
        self.assertEqual(self.commits[1].authored_at, expected)

    def test_parents_on_the_commit_line(self):
        text = (
            "commit aaaaaaaa bbbbbbbb cccccccc\nAuthor: A <a@example.com>\n"
            "Date: 2024-01-01T00:00:00Z\n\n    subject\n"
        )
        [only] = parse_log(text.splitlines())
        self.assertEqual(only.parents, ("bbbbbbbb", "cccccccc"))

    def test_fuller_format_uses_author_date(self):
        text = (
            "commit aaaaaaaa\nAuthor:     A <a@example.com>\n"
            "AuthorDate: Mon Jan 1 00:00:00 2024 +0000\n"
            "Commit:     B <b@example.com>\n"
            "CommitDate: Tue Jan 2 00:00:00 2024 +0000\n\n    subject\n"
        )
        [only] = parse_log(text.splitlines())
        self.assertEqual(only.authored_at.day, 1)

    def test_crlf_line_endings(self):
        lines = DEFAULT_LOG.replace("\n", "\r\n").splitlines(keepends=True)
        self.assertEqual(list(parse_log(lines))[1].paths, ["loader.py", "renamed.py"])

    def test_layouts_can_be_mixed(self):
        mixed = MACHINE_LOG + DEFAULT_LOG
        self.assertEqual(len(list(parse_log(log_lines(mixed)))), 5)


class BadInput(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(list(parse_log([])), [])

    def test_lenient_mode_counts_garbage(self):
        parser = LogParser()
        lines = ["garbage first\n"] + log_lines(MACHINE_LOG) + ["more garbage\n"]
        self.assertEqual(len(list(parser.parse(lines))), 3)
        self.assertEqual(parser.skipped_lines, 2)
        self.assertEqual(parser.commits_parsed, 3)

    def test_strict_mode_names_the_line(self):
        lines = ["\x1ea\x1f\x1fA\x1fa@example.com\x1f2024-01-01T00:00:00Z\x1fs\n", "nonsense\n"]
        with self.assertRaises(LogParseError) as caught:
            list(parse_log(lines, strict=True))
        self.assertEqual(caught.exception.line_number, 2)

    def test_incomplete_commit_is_dropped_or_raised(self):
        text = ["commit aaaaaaaa\n", "Author: A <a@example.com>\n"]
        parser = LogParser()
        self.assertEqual(list(parser.parse(text)), [])
        self.assertEqual(parser.skipped_commits, 1)
        with self.assertRaises(LogParseError):
            list(parse_log(text, strict=True))

    def test_wrong_field_count(self):
        parser = LogParser()
        self.assertEqual(list(parser.parse(["\x1eonly\x1ftwo\n"])), [])
        self.assertEqual(parser.skipped_lines, 1)

    def test_bad_date_drops_the_commit(self):
        parser = LogParser()
        line = "\x1ea\x1f\x1fA\x1fa@example.com\x1fnot-a-date\x1fs\n"
        self.assertEqual(list(parser.parse([line])), [])
        self.assertEqual(parser.skipped_commits, 1)

    def test_parsing_is_lazy(self):
        def lines():
            yield from log_lines(MACHINE_LOG)[:6]
            raise AssertionError("read past the second commit header")

        # Pulling the first commit only reads up to the next commit's header.
        self.assertEqual(next(iter(parse_log(lines()))).sha, "c3")


if __name__ == "__main__":
    unittest.main()
