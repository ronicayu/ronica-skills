"""Tests for docs/reference.md and the docs around it: the file matches the generator, every definition has its prose,
and every link in the docs resolves. Run: "$PY" plugins/agentic-team/tests/run_parallel.py (all tests, in parallel)"""

import argparse
import contextlib
import io
import os
import re
import sys
import tempfile
import types
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import config  # noqa: E402
import events  # noqa: E402
import gen_reference  # noqa: E402
import reference_data  # noqa: E402
import run  # noqa: E402

README_LINES_MAX = 150


def read(*parts):
    with open(os.path.join(PLUGIN, *parts), encoding="utf-8") as fh:
        return fh.read()


def markdown_files():
    names = ["README.md", "CHANGELOG.md"] + [os.path.join("docs", n) for n in sorted(os.listdir(os.path.join(PLUGIN, "docs")))
                                             if n.endswith(".md")]
    return names


def prose_lines(text):
    """The lines of a Markdown text outside fenced code blocks."""
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            yield line


def slugs(text):
    """The anchors of the headings of a Markdown text, as GitHub makes them."""
    seen, found = {}, set()
    for line in prose_lines(text):
        m = re.match(r"^#{1,6} +(.*?) *#*$", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(1).lower().replace("`", "")).replace(" ", "-")
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            found.add(slug if n == 0 else f"{slug}-{n}")
    return found


class ReferenceTest(unittest.TestCase):
    def test_the_reference_file_is_what_the_generator_prints(self):
        self.assertEqual(read("docs", "reference.md"), gen_reference.render(),
                         "docs/reference.md is out of date: run scripts/gen_reference.py")

    def test_check_mode_fails_on_a_stale_file_and_passes_on_a_current_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "reference.md")
            with unittest.mock.patch.object(gen_reference, "OUTPUT", path), contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gen_reference.main(["--check"]), 1)  # no file
                with open(path, "w") as fh:
                    fh.write(gen_reference.render() + "an edit by hand\n")
                self.assertEqual(gen_reference.main(["--check"]), 1)
                self.assertEqual(gen_reference.main([]), 0)  # writes the file
                self.assertEqual(gen_reference.main(["--check"]), 0)

    def test_every_config_key_has_a_description_and_none_is_left_over(self):
        for section, keys in config.SCHEMA.items():
            self.assertEqual(sorted(config.DESCRIPTIONS[section]), sorted(keys), section)
            for key, text in config.DESCRIPTIONS[section].items():
                self.assertTrue(text.strip(), f"{section}.{key}")
        self.assertEqual(sorted(config.DESCRIPTIONS), sorted(config.SCHEMA))
        self.assertLessEqual(set(config.SECTION_NOTES), set(config.SCHEMA))

    def test_every_command_has_prose_and_none_is_left_over(self):
        names = [name for name, _, _ in gen_reference.subcommands(run.build_parser())]
        self.assertEqual(sorted(reference_data.COMMAND_DOCS), sorted(names))

    def test_every_event_has_a_meaning_and_emit_refuses_an_unknown_name(self):
        for name, meaning in events.EVENTS.items():
            self.assertRegex(name, r"^[a-z][a-z0-9-]*$")
            self.assertTrue(meaning.endswith("."), name)
        fake = types.SimpleNamespace(events=[])
        with self.assertRaises(AssertionError):
            run.Run.emit(fake, "no-such-event")
        self.assertEqual(fake.events, [])
        run.Run.emit(fake, "ready", detail="none")
        self.assertEqual(fake.events[0]["event"], "ready")

    def test_every_option_of_every_command_has_help(self):
        parser = run.build_parser()
        for name, sub, _ in gen_reference.subcommands(parser):
            for action in sub._actions:
                if not isinstance(action, argparse._HelpAction):
                    self.assertTrue(action.help, f"{name} {action.dest}")

    def test_meta_keys_and_result_kinds_are_complete_rows(self):
        for keys, by, text in reference_data.META_KEYS:
            self.assertTrue(keys and by and text, keys)
        for row in reference_data.RESULT_KINDS:
            self.assertTrue(all(row), row)
        listed = [k for keys, _ in reference_data.META_WHY for k in keys]
        self.assertLessEqual(set(sum(config.RUNTIME_META.values(), ())), set(listed))
        for keys, _ in reference_data.META_WHY:
            gen_reference.meta_class(keys)  # one class per row

    def test_the_readme_is_a_quickstart(self):
        self.assertLessEqual(len(read("README.md").splitlines()), README_LINES_MAX)

    def test_every_link_in_the_docs_resolves(self):
        for name in markdown_files():
            here = os.path.dirname(os.path.join(PLUGIN, name))
            text = read(name)
            own = slugs(text)
            for line in prose_lines(text):
                for target in re.findall(r"\]\(([^)\s]+)\)", re.sub(r"`[^`]*`", "", line)):
                    if re.match(r"[a-z]+:", target):
                        continue
                    path, _, anchor = target.partition("#")
                    if path:
                        full = os.path.normpath(os.path.join(here, path))
                        self.assertTrue(os.path.exists(full), f"{name}: {target}")
                    else:
                        full = os.path.join(PLUGIN, name)
                    if anchor and full.endswith(".md"):
                        wanted = own if not path else slugs(read(os.path.relpath(full, PLUGIN)))
                        self.assertIn(anchor, wanted, f"{name}: {target}")


if __name__ == "__main__":
    unittest.main()
