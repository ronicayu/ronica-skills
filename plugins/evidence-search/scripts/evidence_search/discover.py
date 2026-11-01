"""Find the files to index and classify them.

In a git repository the file list comes from `git ls-files`, so .gitignore is
honoured. Default exclusions apply on top, plus any the project adds. The same
exclusions are printed as ripgrep flags so grep and the index see the same
files.
"""

import fnmatch
import os
import subprocess

DEFAULT_EXCLUDES = [
    "target/**", "build/**", "dist/**", "out/**", "node_modules/**",
    "bower_components/**", "vendor/**", ".git/**", ".evidence-search/**",
    "**/*.min.js", "**/*.min.css", "**/*.map", "**/*.lock", "**/package-lock.json",
]

MAX_BYTES = 1_000_000

LANG_BY_EXT = {
    ".java": "java",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".jsp": "jsp", ".jspf": "jsp", ".tag": "jsp", ".jspx": "jsp",
    ".html": "html", ".htm": "html",
    ".md": "markdown", ".markdown": "markdown",
    ".adoc": "asciidoc", ".rst": "rst", ".txt": "text",
    ".xml": "xml", ".xsd": "xml", ".wsdl": "xml",
    ".properties": "properties", ".yml": "yaml", ".yaml": "yaml", ".json": "json",
    ".sql": "sql", ".sh": "shell", ".bat": "shell", ".cmd": "shell",
    ".py": "python", ".groovy": "groovy", ".kt": "kotlin", ".scala": "scala",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".go": "go", ".rb": "ruby",
    ".css": "css", ".scss": "css", ".less": "css",
}

DOC_LANGS = {"markdown", "asciidoc", "rst", "text"}
CONFIG_LANGS = {"xml", "properties", "yaml", "json"}


def kind_of(lang):
    if lang in DOC_LANGS:
        return "docs"
    if lang in CONFIG_LANGS:
        return "config"
    return "code"


def lang_of(path):
    base = os.path.basename(path).lower()
    if base in ("dockerfile", "makefile", "jenkinsfile"):
        return "text"
    return LANG_BY_EXT.get(os.path.splitext(base)[1])


def find_root(start):
    """The git top level containing START, or START itself."""
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.path.abspath(start)


def is_git(root):
    return os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git"))


def excluded(path, patterns):
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # "**/x" also matches x at the top level.
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
        # "dir/**" also matches the directory at any depth: a/b/target/x.
        if pattern.endswith("/**") and not pattern.startswith("**/"):
            if fnmatch.fnmatch(path, "*/" + pattern) or path == pattern[:-3]:
                return True
    return False


def _git_files(root):
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            yield os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")


def is_binary(path):
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(8192)
    except OSError:
        return True


def list_files(root, extra_excludes=()):
    """Relative paths of indexable text files under ROOT, sorted."""
    patterns = DEFAULT_EXCLUDES + list(extra_excludes)
    candidates = _git_files(root) if is_git(root) else _walk_files(root)
    result = []
    for rel in candidates:
        if excluded(rel, patterns) or lang_of(rel) is None:
            continue
        full = os.path.join(root, rel)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if not os.path.isfile(full) or st.st_size > MAX_BYTES or st.st_size == 0:
            continue
        result.append(rel)
    return sorted(set(result))


def rg_flags(extra_excludes=()):
    """The exclusions as ripgrep -g flags, shell-quoted.

    ripgrep anchors a glob that contains a slash to the search root, while
    the index excludes a directory at any depth, so directory patterns get a
    leading **/.
    """
    flags = []
    for pattern in DEFAULT_EXCLUDES + list(extra_excludes):
        if pattern.startswith("**/"):
            glob = pattern[3:] if "/" not in pattern[3:] else pattern
        elif pattern.endswith("/**"):
            glob = "**/" + pattern
        else:
            glob = pattern
        flags.append("-g '!%s'" % glob)
    return " ".join(flags)
