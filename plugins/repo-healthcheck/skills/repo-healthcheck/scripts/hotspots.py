#!/usr/bin/env python3
"""Hotspots, file sizes and co-change for the repo-healthcheck skill.

    hotspots.py [REPO] [--months 12] [--top 15] [--pretty]

Prints one JSON document on stdout. It runs `git log` once (renames followed,
signatures never checked, the repository's own git commands never run) and reads
each source file once; it never changes the repository. Standard library only;
Python 3.9+. REPO may be a folder inside a git repository: the log is limited to
that folder, paths are relative to it, and history.git_root and history.subpath
say where git was found.

Source files are the six languages of detect.py, tests excluded, and files that
detect.py calls generated, vendored or migrations (one shared rule) are left out
and counted in `excluded`. Output:

  files        top N by hotspot score: path, language, loc, commits (in the
               window; a renamed file keeps the commits of its old names),
               indent_complexity, max_indent, score, authors (distinct
               people among those commits), top_author (the name most used by
               the one with most commits) and top_author_share (0 to 1, their
               commits over all commits of the file by people). The three author
               fields are null when a file has no commits or history is unusable
               (authors is 0 when every commit was a bot's)
  active_authors_12m
               distinct people who made non-merge commits in the window (the
               window is --months, 12 by default); null without usable history.
               People: git applies .mailmap (%aN, %aE); then identities that share
               an e-mail address (any case) or a name (any case, whitespace folded)
               are one person. Bots are not people: names ending in [bot],
               noreply@anthropic.com, noreply@github.com, and the names dependabot,
               renovate, renovate-bot, github-actions.
  largest      top N source files by LOC
  deepest_indent  top N by deepest indentation level
  cochange     top 10 pairs of source files changed in the same commits (a
               commit that touches more than 30 files is ignored; a pair needs
               at least 2 such commits)
  size_buckets source files by LOC: "<200", "200-499", "500-999", ">=1000"
  excluded     {"generated": n, "vendored": n, "migrations": n} source files left out
  history      whether git history was usable, and why not

Indent complexity is the Tornhill whitespace measure: the sum, over non-blank
lines, of the leading indent in levels. A tab counts as 4 spaces. The level
unit (2, 3, 4 or 8 spaces) is inferred per file: the largest candidate that
divides at least 90 % of the indented lines.

score = (commits / most commits of any file) * (indent complexity / highest
indent complexity of any file). It is 1.0 for a file that is the busiest and the
most complex, and 0 for a file with no commits in the window. When history is
not usable, commits and score are null and `files` is ordered by indent
complexity.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect  # noqa: E402  (shares the file listing, skip list and language table)

READ_LIMIT = 1024 * 1024
MAX_COCHANGE_FILES = 30
MIN_COMMITS_SHALLOW = 10
BUCKETS = ("<200", "200-499", "500-999", ">=1000")


def bucket(loc):
    if loc < 200:
        return BUCKETS[0]
    if loc < 500:
        return BUCKETS[1]
    if loc < 1000:
        return BUCKETS[2]
    return BUCKETS[3]


def leading_width(line):
    width = 0
    for ch in line:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += 4
        else:
            break
    return width


def infer_unit(widths):
    positive = [w for w in widths if w > 0]
    if not positive:
        return 1
    for candidate in (8, 4, 3, 2):
        if sum(1 for w in positive if w % candidate == 0) >= 0.9 * len(positive):
            return candidate
    return 1


def measure(text):
    """(loc, indent complexity, deepest level) of a source text."""
    widths = [leading_width(line) for line in text.split("\n") if line.strip()]
    unit = infer_unit(widths)
    levels = [w / float(unit) for w in widths]
    return len(widths), int(round(sum(levels))), (max(levels) if levels else 0)


def source_files(repo):
    """[(path, language)] of non-test source files."""
    out = []
    for rel in repo.files:
        language = detect.language_of(rel)
        if language is None or detect.is_test_path(language, rel):
            continue
        out.append((rel, language))
    return out


def read_metrics(repo, path):
    """(excluded kind, None) for a generated, vendored or migration file, else (None, (loc, complexity, deepest))."""
    full = os.path.join(repo.root, path)
    try:
        size = os.path.getsize(full)
        with open(full, "rb") as handle:
            data = handle.read(READ_LIMIT)
    except OSError:
        return None, None
    kind = repo.exclusion_kind(path, data[:2048])
    if kind:
        return kind, None
    loc, complexity, deepest = measure(data.decode("utf-8", "replace"))
    if size > len(data) and data:
        factor = size / float(len(data))
        loc = int(loc * factor)
        complexity = int(complexity * factor)
    return None, (loc, complexity, deepest)


def follow_renames(entries):
    """Paths touched by each commit, with old names mapped to the file's current path.

    entries is newest first: [[(status, [paths])]] per commit. A rename `old -> new`
    makes every older mention of `old` stand for the final name of `new`.
    """
    current = {}
    result = []
    for changes in entries:
        touched = []
        for status, paths in changes:
            if status[0] in "RC" and len(paths) == 2:
                old, new = paths
                final = current.get(new, new)
                if status[0] == "R":
                    current[old] = final
                touched.append(final)
            elif paths:
                touched.append(current.get(paths[0], paths[0]))
        result.append(touched)
    return result


def history(repo, months):
    """(commits, info): commits is [(sha, [paths], author key, author name)] or None when unusable."""
    info = {"available": False, "reason": None, "window_months": months,
            "commits_in_window": None, "total_commits": None, "shallow": False,
            "git_root": repo.git_root, "subpath": repo.subpath if repo.is_git else None}
    if not repo.is_git:
        info["reason"] = "not a git repository"
        return None, info
    total = detect.run_git(repo.git_root, ["rev-list", "--count", "HEAD"])
    if total is None:
        info["reason"] = "git repository with no commits"
        return None, info
    info["total_commits"] = int(total.decode().strip() or 0)
    shallow = detect.run_git(repo.git_root, ["rev-parse", "--is-shallow-repository"])
    info["shallow"] = bool(shallow) and shallow.decode().strip() == "true"
    if info["shallow"] and info["total_commits"] < MIN_COMMITS_SHALLOW:
        info["reason"] = "shallow clone with %d commits (fewer than %d)" % (
            info["total_commits"], MIN_COMMITS_SHALLOW)
        return None, info
    args = ["-c", "core.quotepath=off", "log", "--since=%d months ago" % months, "--no-show-signature",
            "-M", "--no-merges", "--name-status", "--format=@@@%H\x1f%aN\x1f%aE"]
    if repo.subpath != ".":
        args += ["--", repo.subpath]
    out = detect.run_git(repo.git_root, args)
    if out is None:
        info["reason"] = "git log failed"
        return None, info
    headers = []
    entries = []
    for line in out.decode("utf-8", "replace").splitlines():
        if line.startswith("@@@"):
            sha, _sep, rest = line[3:].partition("\x1f")
            name, _sep, email = rest.partition("\x1f")
            headers.append((sha, email.strip().lower(), name.strip()))
            entries.append([])
        elif line.strip() and entries:
            fields = line.split("\t")
            if len(fields) >= 2:
                entries[-1].append((fields[0], fields[1:]))
    prefix = "" if repo.subpath == "." else repo.subpath + "/"
    commits = []
    for (sha, key, name), touched in zip(headers, follow_renames(entries)):
        commits.append((sha, [p[len(prefix):] for p in touched if p.startswith(prefix)], key, name))
    info["available"] = True
    info["commits_in_window"] = len(commits)
    return commits, info


BOT_NAMES = {"dependabot", "renovate", "renovate-bot", "github-actions", "dependabot-preview"}
BOT_EMAILS = {"noreply@anthropic.com", "noreply@github.com"}


def is_bot(name, email):
    """Bots do not count as people: *[bot] names, tool noreply addresses, well-known bot names."""
    low = re.sub(r"\s+", " ", name.strip().lower())
    mail = email.strip().lower()
    if low.endswith("[bot]") or mail in BOT_EMAILS or low in BOT_NAMES:
        return True
    return mail.endswith("@users.noreply.github.com") and low.endswith("[bot]")


def people(identities):
    """{(email, name): person id or None for a bot} from the (email, name) pairs of the commits.

    Union-find: two pairs with the same e-mail (case-insensitive) or the same name
    (case-insensitive, whitespace folded) are one person. .mailmap is applied by git
    itself (%aN and %aE). The id is the smallest e-mail or name of the group.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    result = {}
    for email, name in sorted(set(identities)):
        if is_bot(name, email):
            result[(email, name)] = None
            continue
        folded = re.sub(r"\s+", " ", name.strip().lower())
        keys = []
        if email:
            keys.append("e:" + email.lower())
        if folded:
            keys.append("n:" + folded)
        if not keys:
            keys.append("x:unknown")
        for key in keys[1:]:
            union(keys[0], key)
        result[(email, name)] = keys[0]
    return {pair: (None if value is None else find(value)) for pair, value in result.items()}


def analyse(root, months=12, top=15):
    repo = detect.Repo(root)
    commits, info = history(repo, months)
    rows = {}
    excluded = {"generated": 0, "vendored": 0, "migrations": 0}
    for path, language in source_files(repo):
        kind, metrics = read_metrics(repo, path)
        if kind:
            excluded[kind] += 1
        if metrics is None:
            continue
        loc, complexity, deepest = metrics
        rows[path] = {"path": path, "language": language, "loc": loc, "commits": None,
                      "indent_complexity": complexity, "max_indent": round(deepest, 1), "score": None,
                      "authors": None, "top_author": None, "top_author_share": None}

    pairs = defaultdict(int)
    active_authors = None
    if commits is not None:
        counts = defaultdict(int)
        by_author = defaultdict(lambda: defaultdict(int))
        who = people([(key, name) for _sha, _paths, key, name in commits])
        name_votes = defaultdict(lambda: defaultdict(int))
        for _sha, _paths, key, name in commits:
            if who[(key, name)] is not None:
                name_votes[who[(key, name)]][name] += 1
        names = {pid: max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0] for pid, votes in name_votes.items()}
        for _sha, paths, key, name in commits:
            person = who[(key, name)]
            for path in set(paths):
                if path in rows:
                    counts[path] += 1
                    if person is not None:
                        by_author[path][person] += 1
            if len(set(paths)) <= MAX_COCHANGE_FILES:
                touched = sorted(p for p in set(paths) if p in rows)
                for a, b in combinations(touched, 2):
                    pairs[(a, b)] += 1
        most = max(counts.values()) if counts else 0
        highest = max((r["indent_complexity"] for r in rows.values()), default=0)
        active_authors = len(names)
        for path, row in rows.items():
            row["commits"] = counts.get(path, 0)
            if row["commits"] and by_author[path]:
                top_key, top_count = max(by_author[path].items(), key=lambda kv: (kv[1], kv[0]))
                row["authors"] = len(by_author[path])
                row["top_author"] = names[top_key]
                row["top_author_share"] = round(top_count / float(sum(by_author[path].values())), 3)
            elif row["commits"]:
                row["authors"] = 0
            if most and highest:
                row["score"] = round((row["commits"] / float(most)) * (row["indent_complexity"] / float(highest)), 4)
            else:
                row["score"] = 0.0

    everything = list(rows.values())
    if commits is not None:
        ranked = [r for r in everything if r["commits"]]
        ranked.sort(key=lambda r: (-r["score"], -r["indent_complexity"], r["path"]))
    else:
        ranked = sorted(everything, key=lambda r: (-r["indent_complexity"], r["path"]))
    largest = sorted(everything, key=lambda r: (-r["loc"], r["path"]))[:top]
    deepest = sorted(everything, key=lambda r: (-r["max_indent"], r["path"]))[:top]
    cochange = []
    for (a, b), n in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < 2 or len(cochange) >= 10:
            continue
        cochange.append({"a": a, "b": b, "commits": n,
                         "ratio": round(n / float(min(rows[a]["commits"], rows[b]["commits"])), 2)})
    buckets = {name: 0 for name in BUCKETS}
    for row in everything:
        buckets[bucket(row["loc"])] += 1
    return {
        "repo": repo.root,
        "history": info,
        "active_authors_12m": active_authors,
        "source_files": len(everything),
        "files": ranked[:top],
        "largest": [{k: r[k] for k in ("path", "language", "loc")} for r in largest],
        "deepest_indent": [{k: r[k] for k in ("path", "language", "max_indent")} for r in deepest],
        "cochange": cochange,
        "size_buckets": buckets,
        "excluded": excluded,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Churn x size x indent hotspots from git history.")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--pretty", action="store_true", help="indent the JSON")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.repo):
        sys.stderr.write("hotspots.py: not a directory: %s\n" % args.repo)
        return 2
    result = analyse(args.repo, args.months, args.top)
    if args.pretty:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
