"""The tool names in the skill's reference files and in detect.py must not drift.

Rule, per language file `references/<language>.md` (python, typescript, rust,
java, go, kotlin):

* The file has a `## Tools` section. In its tables, the first column holds the
  tool name in backticks.
* Every tool that detect.py's TOOLS table has for that language is listed, and
  every listed tool is in detect.py: for that language, or a `shared` tool, or
  (for kotlin) one of the java rows in KOTLIN_FROM_JAVA.
* A tool is listed once per file.
* `references/shared.md`, if it exists, must list the `shared` tools exactly.
* Any other reference file with a `## Tools` section may list only tools that
  detect.py knows.

A missing reference file fails the test; it is not skipped.

Run: python -m unittest discover -s plugins/repo-health/tests
"""

import importlib.util
import os
import re
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SKILL = os.path.join(PLUGIN, "skills", "repo-health")
REFERENCES = os.path.join(SKILL, "references")
DETECT = os.path.join(SKILL, "scripts", "detect.py")
LANGUAGES = ("python", "typescript", "rust", "java", "go", "kotlin")

_spec = importlib.util.spec_from_file_location("repo_health_detect_for_consistency", DETECT)
detect = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(detect)


def parse_tools_table(text):
    """Tool names from the first column of the tables under `## Tools`.

    Returns None when the text has no `## Tools` heading. The section ends at
    the next heading of level 1 or 2. Rows whose first cell has no backticked
    name (the header and the separator) are skipped.
    """
    names = []
    in_section = False
    found = False
    for line in text.splitlines():
        if re.match(r"^##\s+Tools\s*$", line):
            in_section = found = True
            continue
        if in_section and re.match(r"^#{1,2}\s", line):
            in_section = False
        if not in_section or not line.lstrip().startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        m = re.match(r"^\s*`([^`]+)`\s*$", cells[0])
        if m:
            names.append(m.group(1))
    return names if found else None


def parse_tools_file(path):
    with open(path, encoding="utf-8") as handle:
        return parse_tools_table(handle.read())


def tools_by_language():
    result = {}
    for language, name, _category, _specs, _words in detect.TOOLS:
        result.setdefault(language, set()).add(name)
    return result


def compare(language, listed, table=None):
    """Problems between a reference file's tool names and detect.py's table."""
    table = table if table is not None else tools_by_language()
    expected = table.get(language, set())
    allowed = set(table.get("shared", set()))
    if language == "kotlin":
        allowed |= set(detect.KOTLIN_FROM_JAVA)
    known = set().union(*table.values()) if table else set()
    problems = []
    seen = set()
    for name in listed:
        if name in seen:
            problems.append("`%s` is listed twice" % name)
        seen.add(name)
        if name not in expected and name not in allowed:
            if name in known:
                problems.append("`%s` is not a %s tool in detect.py" % (name, language))
            else:
                problems.append("`%s` is not in detect.py" % name)
    for name in sorted(expected - seen):
        problems.append("detect.py has the %s tool `%s`; the reference file does not list it" % (language, name))
    return problems


def check_references(directory):
    """Every problem between a references/ directory and detect.py (empty when they agree)."""
    if not os.path.isdir(directory):
        return ["references/ is missing (expected at %s)" % directory]
    table = tools_by_language()
    known = set().union(*table.values())
    problems = []

    def listed_in(name):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            problems.append("references/%s is missing" % name)
            return None
        listed = parse_tools_file(path)
        if listed is None:
            problems.append("references/%s has no `## Tools` section" % name)
        return listed

    for language in LANGUAGES:
        listed = listed_in(language + ".md")
        if listed is not None:
            problems.extend("references/%s.md: %s" % (language, p) for p in compare(language, listed, table))
    if os.path.exists(os.path.join(directory, "shared.md")):
        listed = listed_in("shared.md")
        if listed is not None and sorted(listed) != sorted(table["shared"]):
            problems.append("references/shared.md must list exactly the shared tools: %s" % sorted(table["shared"]))
    for name in sorted(os.listdir(directory)):
        stem, ext = os.path.splitext(name)
        if ext != ".md" or stem in LANGUAGES or stem == "shared":
            continue
        for tool in parse_tools_file(os.path.join(directory, name)) or []:
            if tool not in known:
                problems.append("references/%s: `%s` is not in detect.py" % (name, tool))
    return problems


class ReferenceFiles(unittest.TestCase):
    def test_reference_files_match_detect(self):
        problems = check_references(REFERENCES)
        self.assertEqual(problems, [], "references/ and detect.py disagree:\n  " + "\n  ".join(problems))


class TableParser(unittest.TestCase):
    """The parser and the comparison, on reference files built here."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="repo-health-refs-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def parse(self, text):
        path = os.path.join(self.dir, "ref.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return parse_tools_file(path)

    def test_first_column_names(self):
        text = (
            "# Python\n\n## Detect\n\n| `not` | a tool |\n\n## Tools\n\n"
            "| Tool | Category | Config |\n| --- | --- | --- |\n"
            "| `ruff` | lint | `ruff.toml` |\n| `coverage.py` | coverage | `.coveragerc` |\n"
            "| plain | lint | none |\n\n## Commands\n\n| `pytest` | tests |\n"
        )
        self.assertEqual(self.parse(text), ["ruff", "coverage.py"])

    def test_subsections_belong_to_the_tools_section(self):
        text = "## Tools\n\n### Lint\n\n| `ruff` | x |\n\n### Types\n\n| `mypy` | x |\n\n## Other\n\n| `black` | x |\n"
        self.assertEqual(self.parse(text), ["ruff", "mypy"])

    def test_no_tools_section(self):
        self.assertIsNone(self.parse("# Title\n\n| `ruff` | x |\n"))

    def test_empty_tools_section(self):
        self.assertEqual(self.parse("## Tools\n\nnothing here\n"), [])

    def test_heading_must_be_exactly_tools(self):
        self.assertIsNone(self.parse("## Tools and notes\n\n| `ruff` | x |\n"))

    def test_indented_rows_and_trailing_spaces(self):
        self.assertEqual(self.parse("## Tools  \n\n  | `ruff` | x |\n"), ["ruff"])

    def test_compare_reports_missing_extra_and_duplicate_tools(self):
        table = {"python": {"ruff", "mypy"}, "typescript": {"eslint"}, "shared": {"semgrep"},
                 "kotlin": {"detekt"}, "java": {"junit", "checkstyle"}}
        self.assertEqual(compare("python", ["ruff", "mypy"], table), [])
        self.assertEqual(compare("python", ["ruff", "mypy", "semgrep"], table), [])   # shared is allowed
        problems = compare("python", ["ruff", "ruff", "eslint", "nope"], table)
        self.assertIn("`ruff` is listed twice", problems)
        self.assertIn("`eslint` is not a python tool in detect.py", problems)
        self.assertIn("`nope` is not in detect.py", problems)
        self.assertTrue(any("`mypy`" in p and "does not list" in p for p in problems))

    def test_compare_allows_the_java_rows_kotlin_inherits(self):
        table = {"kotlin": {"detekt"}, "java": {"junit", "checkstyle"}, "shared": set()}
        self.assertEqual(compare("kotlin", ["detekt", "junit"], table), [])
        self.assertEqual(compare("kotlin", ["detekt", "checkstyle"], table),
                         ["`checkstyle` is not a kotlin tool in detect.py"])

    def test_compare_against_the_real_table_catches_a_dropped_tool(self):
        listed = sorted(tools_by_language()["go"])
        self.assertEqual(compare("go", listed), [])
        problems = compare("go", listed[1:])
        self.assertEqual(len(problems), 1)
        self.assertIn(listed[0], problems[0])

    def make_references(self, **changes):
        """A complete references/ directory generated from detect.py's table."""
        folder = os.path.join(self.dir, "references")
        os.makedirs(folder)
        table = tools_by_language()
        for language in LANGUAGES:
            names = sorted(table[language])
            if language == "kotlin":
                names += sorted(detect.KOTLIN_FROM_JAVA)
            rows = "".join("| `%s` | lint | none |\n" % name for name in names)
            with open(os.path.join(folder, language + ".md"), "w") as handle:
                handle.write("# %s\n\n## Tools\n\n| Tool | Category | Config |\n| --- | --- | --- |\n%s" % (language, rows))
        for name, text in changes.items():
            path = os.path.join(folder, name)
            if text is None:
                os.remove(path)
            else:
                with open(path, "w") as handle:
                    handle.write(text)
        return folder

    def test_a_complete_directory_passes(self):
        self.assertEqual(check_references(self.make_references()), [])

    def test_a_missing_language_file_is_a_problem_not_a_skip(self):
        problems = check_references(self.make_references(**{"go.md": None}))
        self.assertEqual(problems, ["references/go.md is missing"])

    def test_a_missing_directory_is_a_problem(self):
        self.assertEqual(len(check_references(os.path.join(self.dir, "nope"))), 1)

    def test_a_file_without_a_tools_section_is_a_problem(self):
        problems = check_references(self.make_references(**{"rust.md": "# Rust\n"}))
        self.assertTrue(any("rust.md has no `## Tools` section" in p for p in problems))

    def test_a_renamed_tool_is_a_problem(self):
        folder = self.make_references()
        path = os.path.join(folder, "python.md")
        with open(path) as handle:
            text = handle.read().replace("`ruff`", "`ruf`")
        with open(path, "w") as handle:
            handle.write(text)
        problems = check_references(folder)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("`ruf` is not in detect.py" in p for p in problems))
        self.assertTrue(any("does not list" in p and "`ruff`" in p for p in problems))

    def test_other_files_may_list_only_known_tools(self):
        folder = self.make_references(**{"dimensions.md": "## Tools\n\n| `ruff` | x |\n| `bogus` | x |\n"})
        self.assertEqual(check_references(folder), ["references/dimensions.md: `bogus` is not in detect.py"])

    def test_shared_file_must_list_the_shared_tools(self):
        folder = self.make_references(**{"shared.md": "## Tools\n\n| `semgrep` | x |\n"})
        self.assertEqual(len(check_references(folder)), 1)
        names = "".join("| `%s` | x |\n" % n for n in sorted(tools_by_language()["shared"]))
        folder = os.path.join(self.dir, "references")
        with open(os.path.join(folder, "shared.md"), "w") as handle:
            handle.write("## Tools\n\n" + names)
        self.assertEqual(check_references(folder), [])

    def test_every_language_has_tools_in_detect(self):
        table = tools_by_language()
        for language in LANGUAGES + ("shared",):
            self.assertTrue(table.get(language), language)


if __name__ == "__main__":
    unittest.main()
