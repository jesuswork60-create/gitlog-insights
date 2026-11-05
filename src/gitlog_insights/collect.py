"""Run ``git log`` and stream its output."""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime
from typing import Iterator

from .parser import LOG_FORMAT


class GitError(RuntimeError):
    """``git`` could not be started or reported a failure."""


# Printed by git when HEAD points at an unborn branch; that is simply "no commits".
_EMPTY_REPO_MESSAGES = ("does not have any commits yet",)


def build_command(
    repo: str,
    *,
    since: datetime | None = None,
    revision: str | None = None,
    all_refs: bool = False,
    max_count: int | None = None,
) -> list[str]:
    """Assemble the git command line.

    Only the lower date bound is pushed down to git. Upper bounds and path
    filters are applied after parsing, because the rename tracker needs to see
    newer commits and co-change analysis needs whole commits.
    """
    command = [
        "git",
        "-C",
        repo,
        "-c",
        "core.quotePath=false",
        "-c",
        "log.showRoot=true",
        "log",
        f"--format={LOG_FORMAT}",
        "--numstat",
        "-M",
        "--no-color",
        "--no-show-signature",
        "--no-ext-diff",
        "--no-textconv",
    ]
    if since is not None:
        command.append(f"--since={since.isoformat()}")
    if max_count is not None:
        command.append(f"--max-count={max_count}")
    if all_refs:
        command.append("--all")
    if revision:
        if revision.startswith("-"):
            raise GitError(f"refusing revision that looks like an option: {revision}")
        command.append(revision)
    command.append("--")
    return command


def stream_git_log(repo: str, **options) -> Iterator[str]:
    """Yield raw output lines from ``git log``; raises :class:`GitError` on failure.

    Stderr goes to a temporary file rather than a pipe so a chatty git cannot
    block while we are still draining stdout.
    """
    command = build_command(repo, **options)
    environment = dict(os.environ, LC_ALL="C")
    with tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr,
                env=environment,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise GitError(f"could not run git: {exc}") from exc
        finished = False
        try:
            assert process.stdout is not None
            yield from process.stdout
            finished = True
        finally:
            # An abandoned generator must not leave git blocked on a full pipe.
            if not finished:
                process.kill()
            process.stdout.close()
            code = process.wait()
        if code != 0:
            stderr.seek(0)
            message = stderr.read().decode("utf-8", errors="replace").strip()
            if any(text in message for text in _EMPTY_REPO_MESSAGES):
                return
            raise GitError(message or f"git log exited with status {code}")
