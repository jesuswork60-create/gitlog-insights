import unittest
from datetime import datetime, timedelta, timezone

from helpers import ALPHA, BETA, GAMMA, at, change, commit

from gitlog_insights.analysis.authors import author_stats, rank_authors
from gitlog_insights.analysis.churn import directory_of, directory_stats, file_stats, rank_files
from gitlog_insights.analysis.cochange import cochange_pairs, partners_of
from gitlog_insights.analysis.compare import compare_periods
from gitlog_insights.analysis.hotspots import hotspots
from gitlog_insights.analysis.messages import classify_subject, message_stats
from gitlog_insights.analysis.ownership import bus_factor, file_ownership, owner_footprint
from gitlog_insights.analysis.summary import summarize
from gitlog_insights.analysis.timeline import rhythm, timeline
from gitlog_insights.models import Author


class Churn(unittest.TestCase):
    def setUp(self):
        self.history = [
            commit("3", at(3), change("a.py", 5, 5), author=BETA),
            commit("2", at(2), change("a.py", 1, 0), change("b.py", 100, 0)),
            commit("1", at(1), change("logo.png", None, None), change("a.py", 2, 2)),
        ]
        self.stats = file_stats(self.history)

    def test_totals(self):
        entry = self.stats["a.py"]
        self.assertEqual((entry.commits, entry.added, entry.deleted, entry.churn), (3, 8, 7, 15))
        self.assertEqual(len(entry.authors), 2)
        self.assertEqual((entry.first_changed, entry.last_changed), (at(1), at(3)))

    def test_binary_changes_are_counted_separately(self):
        entry = self.stats["logo.png"]
        self.assertEqual((entry.commits, entry.churn, entry.binary_changes), (1, 0, 1))

    def test_date_range_does_not_depend_on_order(self):
        reversed_stats = file_stats(reversed(self.history))["a.py"]
        self.assertEqual((reversed_stats.first_changed, reversed_stats.last_changed), (at(1), at(3)))

    def test_ranking(self):
        values = list(self.stats.values())
        self.assertEqual([s.path for s in rank_files(values)], ["b.py", "a.py", "logo.png"])
        self.assertEqual(rank_files(values, by="commits")[0].path, "a.py")
        self.assertEqual(rank_files(values, by="authors")[0].path, "a.py")
        self.assertEqual(rank_files(values, by="path")[0].path, "a.py")
        self.assertEqual(len(rank_files(values, limit=2)), 2)

    def test_ties_break_by_path(self):
        history = [commit("1", at(1), change("z.py", 1), change("a.py", 1))]
        self.assertEqual([s.path for s in rank_files(file_stats(history).values())], ["a.py", "z.py"])

    def test_unknown_sort_key(self):
        with self.assertRaises(ValueError):
            rank_files([], by="beauty")

    def test_empty(self):
        self.assertEqual(file_stats([]), {})


class Directories(unittest.TestCase):
    def test_directory_of(self):
        self.assertEqual(directory_of("a/b/c.py", 1), "a")
        self.assertEqual(directory_of("a/b/c.py", 2), "a/b")
        self.assertEqual(directory_of("a/b/c.py", 5), "a/b")
        self.assertEqual(directory_of("c.py", 1), ".")

    def test_commit_counts_once_per_directory(self):
        history = [commit("1", at(1), change("src/a.py", 1), change("src/b.py", 2), change("top.txt", 3))]
        stats = directory_stats(history)
        self.assertEqual(stats["src"].commits, 1)
        self.assertEqual(stats["src"].added, 3)
        self.assertEqual(stats["."].added, 3)

    def test_depth_must_be_positive(self):
        with self.assertRaises(ValueError):
            directory_stats([], depth=0)


class Authors(unittest.TestCase):
    def test_totals_and_days(self):
        history = [
            commit("3", at(5), change("b.py", 1, 1)),
            commit("2", at(2, 8), change("a.py", 2, 0)),
            commit("1", at(2, 7), change("a.py", 3, 0)),
            commit("m", at(1), parents=("x", "y"), author=BETA),
        ]
        stats = author_stats(history)
        alpha = stats["alpha@example.com"]
        self.assertEqual((alpha.commits, alpha.added, alpha.deleted), (3, 6, 1))
        self.assertEqual(alpha.files, {"a.py", "b.py"})
        self.assertEqual(len(alpha.active_days), 2)
        self.assertEqual(stats["beta@example.com"].merges, 1)

    def test_newest_name_wins_in_either_order(self):
        old = commit("1", at(1), author=Author("Oldname", "a@example.com"))
        new = commit("2", at(2), author=Author("Newname", "A@EXAMPLE.COM"))
        for history in ([old, new], [new, old]):
            stats = author_stats(history)
            self.assertEqual(len(stats), 1)
            self.assertEqual(stats["a@example.com"].name, "Newname")

    def test_days_use_the_author_local_clock(self):
        offset = timezone(timedelta(hours=-8))
        history = [commit("1", datetime(2024, 3, 1, 23, 30, tzinfo=offset))]
        days = author_stats(history)["alpha@example.com"].active_days
        self.assertEqual({d.day for d in days}, {1})

    def test_longest_streak(self):
        history = [commit(str(d), at(d)) for d in (1, 2, 3, 7, 8, 20)]
        self.assertEqual(author_stats(history)["alpha@example.com"].longest_streak, 3)

    def test_streak_crosses_month_end(self):
        history = [commit("1", at(29, month=2)), commit("2", at(1, month=3))]
        self.assertEqual(author_stats(history)["alpha@example.com"].longest_streak, 2)

    def test_ranking(self):
        history = [
            commit("1", at(1), change("a", 100)),
            commit("2", at(1), change("a", 1), author=BETA),
            commit("3", at(2), change("b", 1), author=BETA),
        ]
        stats = author_stats(history).values()
        self.assertEqual(rank_authors(stats)[0].key, "beta@example.com")
        self.assertEqual(rank_authors(stats, by="churn")[0].key, "alpha@example.com")
        self.assertEqual(rank_authors(stats, by="files")[0].key, "beta@example.com")
        self.assertEqual(rank_authors(stats, by="days")[0].key, "beta@example.com")
        self.assertEqual(len(rank_authors(stats, limit=1)), 1)
        with self.assertRaises(ValueError):
            rank_authors(stats, by="charm")


class CoChange(unittest.TestCase):
    def setUp(self):
        self.history = [
            commit("1", at(1), change("a"), change("b"), change("c")),
            commit("2", at(2), change("a"), change("b")),
            commit("3", at(3), change("a")),
            commit("4", at(4), change("c")),
        ]

    def test_support_and_metrics(self):
        [pair] = cochange_pairs(self.history, min_support=2)
        self.assertEqual((pair.a, pair.b, pair.support), ("a", "b", 2))
        self.assertAlmostEqual(pair.coupling, 2 / 3)
        self.assertAlmostEqual(pair.confidence_a_to_b, 2 / 3)
        self.assertAlmostEqual(pair.confidence_b_to_a, 1.0)

    def test_min_support_one_lists_all_pairs(self):
        pairs = cochange_pairs(self.history, min_support=1)
        self.assertEqual({(p.a, p.b) for p in pairs}, {("a", "b"), ("a", "c"), ("b", "c")})

    def test_order_is_by_support_then_coupling_then_name(self):
        pairs = cochange_pairs(self.history, min_support=1)
        self.assertEqual((pairs[0].a, pairs[0].b), ("a", "b"))
        # a-c and b-c share one commit; b has fewer commits, so b-c couples tighter.
        self.assertEqual((pairs[1].a, pairs[1].b), ("b", "c"))

    def test_large_commits_are_ignored_entirely(self):
        big = commit("big", at(5), *[change(f"f{i}") for i in range(5)], change("a"), change("b"))
        pairs = cochange_pairs(self.history + [big], max_files=4)
        self.assertEqual(pairs[0].support, 2)
        self.assertEqual(pairs[0].a_commits, 3)

    def test_duplicate_path_in_a_commit_counts_once(self):
        history = [commit("1", at(1), change("a"), change("a"), change("b"))] * 2
        [pair] = cochange_pairs(history)
        self.assertEqual((pair.a, pair.b, pair.support), ("a", "b", 2))

    def test_min_coupling_and_limit(self):
        self.assertEqual(cochange_pairs(self.history, min_support=1, min_coupling=0.6)[0].b, "b")
        self.assertEqual(len(cochange_pairs(self.history, min_support=1, min_coupling=0.6)), 1)
        self.assertEqual(len(cochange_pairs(self.history, min_support=1, limit=2)), 2)

    def test_partners(self):
        pairs = cochange_pairs(self.history, min_support=1)
        partners = partners_of("b", pairs)
        self.assertEqual([name for name, _ in partners], ["a", "c"])
        self.assertEqual(partners_of("missing", pairs), [])


class Ownership(unittest.TestCase):
    def setUp(self):
        self.history = [
            commit("3", at(3), change("a.py", 90, 0)),
            commit("2", at(2), change("a.py", 5, 5), author=BETA),
            commit("1", at(1), change("b.py", 1, 0), author=BETA),
        ]

    def test_share_by_lines(self):
        entry = file_ownership(self.history)["a.py"]
        self.assertEqual(entry.owner, "alpha@example.com")
        self.assertAlmostEqual(entry.owner_share, 0.9)
        self.assertEqual((entry.contributors, entry.total_weight), (2, 100))
        self.assertFalse(entry.is_siloed)

    def test_share_by_commits(self):
        entry = file_ownership(self.history, metric="commits")["a.py"]
        self.assertAlmostEqual(entry.owner_share, 0.5)
        # Equal weights: alphabetically first author, so results are stable.
        self.assertEqual(entry.owner, "alpha@example.com")

    def test_silo(self):
        self.assertTrue(file_ownership(self.history)["b.py"].is_siloed)

    def test_binary_and_rename_only_changes_still_count(self):
        history = [commit("1", at(1), change("logo.png", None, None), change("c.py", 0, 0, old="d.py"))]
        data = file_ownership(history)
        self.assertEqual(data["logo.png"].total_weight, 1)
        self.assertEqual(data["c.py"].total_weight, 1)

    def test_bad_metric(self):
        with self.assertRaises(ValueError):
            file_ownership([], metric="vibes")

    def test_footprint_and_bus_factor(self):
        history = []
        for index in range(5):
            history.append(commit(str(index), at(1), change(f"a{index}")))
        for index in range(3):
            history.append(commit(f"b{index}", at(1), change(f"b{index}"), author=BETA))
        for index in range(2):
            history.append(commit(f"c{index}", at(1), change(f"c{index}"), author=GAMMA))
        data = file_ownership(history).values()
        self.assertEqual(
            owner_footprint(data),
            [("alpha@example.com", 5), ("beta@example.com", 3), ("gamma@example.com", 2)],
        )
        # Five of ten is not *more than* half, so a second person is needed.
        self.assertEqual(bus_factor(data), 2)
        self.assertEqual(bus_factor(data, threshold=0.25), 1)
        self.assertEqual(bus_factor(data, threshold=0.9), 3)

    def test_bus_factor_edges(self):
        self.assertEqual(bus_factor([]), 0)
        with self.assertRaises(ValueError):
            bus_factor([], threshold=1.0)


class Hotspots(unittest.TestCase):
    def test_recent_work_outranks_old_work_of_equal_size(self):
        history = [
            commit("new", at(30, month=6), change("recent.py", 10)),
            commit("old", at(1, month=1), change("ancient.py", 10)),
        ]
        ranked = hotspots(history)
        self.assertEqual([h.path for h in ranked], ["recent.py", "ancient.py"])
        self.assertGreater(ranked[0].score, ranked[1].score * 2)

    def test_half_life_halves_the_weight(self):
        reference = at(1) + timedelta(days=10)
        history = [commit("1", at(1), change("a", 3))]
        now_score = hotspots(history, half_life_days=10, reference=at(1))[0].score
        later_score = hotspots(history, half_life_days=10, reference=reference)[0].score
        self.assertAlmostEqual(later_score, now_score / 2)

    def test_steady_editing_beats_one_giant_commit(self):
        history = [commit(str(d), at(d), change("steady.py", 10)) for d in range(1, 10)]
        history.append(commit("big", at(5), change("giant.py", 100000)))
        self.assertEqual(hotspots(history)[0].path, "steady.py")

    def test_default_reference_is_the_newest_commit_not_today(self):
        history = [commit("1", at(1), change("a", 1))]
        self.assertAlmostEqual(hotspots(history)[0].score, 2.0)

    def test_details_and_limit(self):
        history = [
            commit("2", at(2), change("a", 1, 1), author=BETA),
            commit("1", at(1), change("a", 2, 0), change("b", 1)),
        ]
        ranked = hotspots(history, limit=1)
        self.assertEqual(len(ranked), 1)
        first = ranked[0]
        self.assertEqual((first.path, first.commits, first.churn, first.authors), ("a", 2, 4, 2))
        self.assertEqual(first.last_changed, at(2))

    def test_empty_and_invalid(self):
        self.assertEqual(hotspots([]), [])
        with self.assertRaises(ValueError):
            hotspots([], half_life_days=0)


class Timeline(unittest.TestCase):
    def test_monthly_with_gap(self):
        history = [
            commit("2", at(15, month=3), change("a", 2, 1), author=BETA),
            commit("1", at(10, month=1), change("a", 1, 0)),
            commit("0", at(11, month=1), change("a", 1, 0), author=BETA),
        ]
        buckets = timeline(history)
        self.assertEqual([b.key for b in buckets], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual([b.commits for b in buckets], [2, 0, 1])
        self.assertEqual(len(buckets[0].authors), 2)
        self.assertEqual((buckets[2].added, buckets[2].deleted), (2, 1))

    def test_without_gaps(self):
        history = [commit("2", at(15, month=3)), commit("1", at(10, month=1))]
        self.assertEqual([b.key for b in timeline(history, fill_gaps=False)], ["2024-01", "2024-03"])

    def test_week_and_day_periods(self):
        history = [commit("2", at(4)), commit("1", at(1))]
        self.assertEqual([b.key for b in timeline(history, period="week")], ["2024-W09", "2024-W10"])
        self.assertEqual(len(timeline(history, period="day")), 4)

    def test_empty(self):
        self.assertEqual(timeline([]), [])

    def test_rhythm_uses_local_time(self):
        tokyo = timezone(timedelta(hours=9))
        # Friday 23:00 UTC is Saturday 08:00 at +09:00.
        moment = datetime(2024, 3, 1, 23, tzinfo=timezone.utc).astimezone(tokyo)
        grid = rhythm([commit("1", moment)])
        self.assertEqual(grid[5][8], 1)
        self.assertEqual(sum(map(sum, grid)), 1)
        self.assertEqual((len(grid), len(grid[0])), (7, 24))


class Messages(unittest.TestCase):
    def test_conventional_prefixes(self):
        parsed = classify_subject("feat(api)!: drop the old route")
        self.assertEqual((parsed.kind, parsed.scope, parsed.breaking), ("feat", "api", True))
        self.assertEqual(classify_subject("Fix: tidy").kind, "fix")
        self.assertIsNone(classify_subject("docs: words").scope)

    def test_fallback_guesses(self):
        self.assertEqual(classify_subject('Revert "add thing"').kind, "revert")
        self.assertEqual(classify_subject("Merge branch 'topic'").kind, "merge")
        self.assertEqual(classify_subject("Fixes the crash on start").kind, "fix")
        self.assertEqual(classify_subject("regression in loader").kind, "fix")
        self.assertEqual(classify_subject("add new loader").kind, "other")

    def test_word_boundaries_avoid_false_fixes(self):
        self.assertEqual(classify_subject("add prefix handling").kind, "other")
        self.assertEqual(classify_subject("debug helper").kind, "other")

    def test_colon_without_a_space_is_not_a_prefix(self):
        self.assertEqual(classify_subject("note:nothing here").kind, "other")

    def test_stats(self):
        history = [
            commit("1", at(1), change("a"), change("b"), subject="fix(core): one"),
            commit("2", at(2), change("a"), subject="repair: not counted"),
            commit("3", at(3), change("a"), subject="fix: two"),
            commit("4", at(4), subject=""),
            commit("5", at(5), subject="x" * 80),
            commit("6", at(6), subject="feat!: boom"),
        ]
        stats = message_stats(history)
        self.assertEqual(stats.total, 6)
        self.assertEqual(stats.kinds["fix"], 2)
        self.assertEqual(stats.scopes["core"], 1)
        self.assertEqual(stats.breaking, 1)
        self.assertEqual((stats.empty_subjects, stats.long_subjects), (1, 1))
        self.assertEqual(stats.fix_touches["a"], 2)
        self.assertEqual(stats.fix_touches["b"], 1)
        self.assertAlmostEqual(stats.fix_ratio, 2 / 6)

    def test_empty_ratio(self):
        self.assertEqual(message_stats([]).fix_ratio, 0.0)


class Compare(unittest.TestCase):
    def setUp(self):
        self.history = [
            commit("3", at(20), change("a", 50), author=GAMMA),
            commit("2", at(10), change("b", 5)),
            commit("1", at(1), change("a", 10), change("b", 20)),
            commit("0", at(2), change("c", 1), author=BETA),
        ]
        self.result = compare_periods(self.history, at(10))

    def test_split_moment_counts_as_after(self):
        self.assertEqual((self.result.commits_before, self.result.commits_after), (2, 2))
        self.assertEqual((self.result.churn_before, self.result.churn_after), (31, 55))

    def test_file_deltas_are_largest_first(self):
        self.assertEqual(self.result.files[0].key, "a")
        self.assertEqual(self.result.files[0].change, 40)
        changes = {d.key: d.change for d in self.result.files}
        self.assertEqual(changes["b"], -15)
        self.assertEqual(changes["c"], -1)

    def test_new_and_gone_authors(self):
        self.assertEqual(self.result.new_authors, ["gamma@example.com"])
        self.assertEqual(self.result.gone_authors, ["beta@example.com"])

    def test_empty_side(self):
        result = compare_periods(self.history, at(1, year=2030))
        self.assertEqual(result.commits_after, 0)
        self.assertEqual(result.new_authors, [])


class Summary(unittest.TestCase):
    def test_values(self):
        history = [
            commit("3", at(10), change("a", 10, 10)),
            commit("m", at(5), parents=("x", "y"), author=BETA),
            commit("2", at(3), change("a", 1, 0), change("b", 2, 0)),
            commit("1", at(1), change("c", 1, 0)),
        ]
        data = summarize(history)
        self.assertEqual((data.commits, data.merges, data.authors, data.files), (4, 1, 2, 3))
        self.assertEqual((data.added, data.deleted), (14, 10))
        self.assertEqual((data.first_commit, data.last_commit, data.span_days), (at(1), at(10), 9))
        # The merge is left out, so the median is taken over 20, 3 and 1.
        self.assertEqual(data.median_commit_size, 3)
        self.assertEqual((data.largest_commit, data.largest_commit_size), ("3", 20))

    def test_empty(self):
        data = summarize([])
        self.assertEqual((data.commits, data.span_days, data.largest_commit), (0, 0, None))

    def test_only_merges(self):
        data = summarize([commit("m", at(1), parents=("x", "y"))])
        self.assertEqual(data.median_commit_size, 0.0)


if __name__ == "__main__":
    unittest.main()
