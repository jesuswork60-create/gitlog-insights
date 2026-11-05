# gitlog-insights

Reads the history of a git repository and answers questions a plain `git log`
makes tedious: which files change most, who wrote what, which files always
change together, and where recent work is piling up.

It runs `git log` itself, or reads a log you saved earlier. There are no
dependencies outside the Python standard library.

## Install

Python 3.11 or newer.

```
pip install .
```

Or run it from a checkout without installing:

```
PYTHONPATH=src python3 -m gitlog_insights summary --repo /path/to/repo
```

## Usage

```
gitlog-insights churn --repo path/to/repo --limit 5
gitlog-insights authors --since 6m --format markdown
gitlog-insights cochange --min-support 3 --file src/parser.py
gitlog-insights compare --split 2024-06-01
```

The reports:

| Command | Answers |
| --- | --- |
| `summary` | How big is this history? |
| `churn` | Which files change most? |
| `dirs` | The same, rolled up to directories (`--depth`) |
| `authors` | Who is active, and how much? |
| `cochange` | Which files change in the same commit? |
| `ownership` | Who is the main contributor to each file? Includes a rough bus factor |
| `hotspots` | Where is recent change concentrated? (`--half-life` in days) |
| `timeline` | Activity per day, week, month or year |
| `rhythm` | Commits by weekday and hour, in each author's local time |
| `messages` | Conventional-commit types, and the files fixes touch most |
| `compare` | What changed before and after a date? (`--split`) |
| `snapshot` | Save the parsed history to a JSON Lines file for later |

All of them share filters (`--since`, `--until`, `--author`, `--exclude-author`,
`--include`, `--exclude`, `--no-merges`) and an output choice (`--format text`,
`markdown`, `json` or `csv`).

Working from a saved log needs `--numstat` in the original command. Either of
these layouts is understood:

```
git log --numstat > history.log
git log --numstat --format='%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s' > history.log
gitlog-insights churn --input history.log
```

### Settings file

A `.gitlog-insights.toml` at the top of the repository is picked up
automatically; `--config` names a different one. Command line flags win over the
file for single values, and path and author filters from both are combined.
Misspelled keys are errors.

```toml
[filters]
exclude = ["vendor/", "*.lock"]
exclude_authors = ["release-bot"]

[identity]
mailmap = ".mailmap"
aliases = { "old@example.com" = "new@example.com" }

[cochange]
min_support = 3
max_files = 20

[hotspots]
half_life_days = 60
```

## Tests

```
PYTHONPATH=src python3 -m unittest discover -s tests
```

Some tests create throwaway repositories in a temporary directory. They are
skipped if `git` is not installed.

## How some numbers are defined

- **Hotspot score**: each change adds `(1 + log2(1 + lines)) * 0.5 ** (age /
  half_life)`. Age is measured from the newest commit in the data, not from
  today, so results on a saved log do not drift.
- **Coupling**: the Jaccard index of the commits touching two files. Commits
  above `max_files` files are ignored for this report.
- **Bus factor**: the fewest main contributors who together are the main
  contributor of more than half the files. It is a rough signal.

## Known limitations

- All commits are held in memory while a report is built. Parsing is streaming
  but the analyses are not, so very large histories use a lot of it.
- Rename following assumes newest-first order, so logs saved with `--reverse`
  give wrong results unless you pass `--no-renames`.
- A file created at a name that an older file moved away from is handled, but
  one created at the name of a file deleted long before shares that file's
  history, because deletions are not distinguishable from edits in numstat.
- A filename containing the literal text ` => ` is read as a rename.
- Merge commits normally have no numstat rows, so their changes do not count
  towards any file.
- Only the author is read. Committers and `Co-authored-by` trailers are ignored.
- A commit subject containing the byte `0x1f` is rejected by the machine layout.
- Time-period buckets are always UTC. There is no option to use another zone.
