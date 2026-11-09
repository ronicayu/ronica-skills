import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tgstore.base import StoreError  # noqa: E402
from tgstore.github.body import LIMIT, check_size, conflicts, parse, render  # noqa: E402


def test_round_trip():
    meta = {"estimate": 2, "lane": "core", "verify": "make check", "tags": ["a", "b"], "nested": {"x": None}}
    body = render("Why this exists.\n\nTwo paragraphs.", meta)
    assert body.endswith("taskgraph:end -->\n")
    assert parse(body) == ("Why this exists.\n\nTwo paragraphs.", meta, [])


def test_block_is_one_sorted_compact_line():
    body = render("n", {"b": 1, "a": "é"})
    assert body == 'n\n\n<!-- taskgraph:meta v1\n{"a":"é","b":1}\ntaskgraph:end -->\n'


def test_escapes_keep_the_html_comment_closed():
    meta = {"a": "x --> y", "b": "<!-- z", "c": "taskgraph:end -->"}
    body = render("", meta)
    assert body.count("-->") == 1 and body.count("<!--") == 1
    assert parse(body) == ("", meta, [])


def test_empty_notes_put_the_block_first():
    body = render("", {"a": 1})
    assert body.startswith("<!-- taskgraph:meta v1\n")
    assert parse(body) == ("", {"a": 1}, [])


def test_notes_that_end_in_newlines_survive():
    for notes in ("a\n", "a\n\n", "\nb"):
        assert parse(render(notes, {"k": 1}))[0] == notes


def test_no_block_without_meta_unless_the_issue_had_one():
    assert render("only notes", {}) == "only notes"
    assert parse(render("n", {}, keep=True)) == ("n", {}, [])


def test_body_without_a_block_is_all_notes():
    assert parse("typed by a person\nin the browser") == ("typed by a person\nin the browser", {}, [])
    assert parse("") == ("", {}, [])
    assert parse(None) == ("", {}, [])


def test_human_text_before_the_block_is_kept_as_notes():
    body = "Edited by a person.\n\n" + render("", {"a": 1})
    assert parse(body) == ("Edited by a person.", {"a": 1}, [])


@pytest.mark.parametrize("body", [
    "n\n\n<!-- taskgraph:meta v1\n{not json}\ntaskgraph:end -->\n",
    "n\n\n<!-- taskgraph:meta v1\n[1,2]\ntaskgraph:end -->\n",
    "n\n\n<!-- taskgraph:meta v1\n{\"a\":1}\n",
    "n\n\n<!-- taskgraph:meta v1\n{\"a\":1}\ntaskgraph:end -->\ntext typed after the block\n",
])
def test_broken_block_reads_as_empty_meta_with_a_problem(body):
    notes, meta, problems = parse(body)
    assert (notes, meta, problems) == ("n", {}, ["broken"])
    assert conflicts(7, problems) == ["meta block on #7 is broken; fix or delete it on GitHub"]


def test_two_blocks_the_last_one_counts_and_the_first_stays_in_the_notes():
    first = render("", {"old": 1})
    body = first + "\n" + render("middle", {"new": 2})
    notes, meta, problems = parse(body)
    assert meta == {"new": 2} and problems == ["two_blocks"]
    assert "taskgraph:meta v1" in notes and notes.endswith("middle")
    assert conflicts(3, problems) == ["#3 has 2 meta blocks; the last one counts"]


def test_crlf_from_the_browser_still_parses():
    body = render("a", {"k": 1}).replace("\n", "\r\n")
    assert parse(body)[1:] == ({"k": 1}, [])


def test_size_limit_refuses_at_260001_bytes():
    check_size("#1", "x" * LIMIT)
    with pytest.raises(StoreError) as caught:
        check_size("#1", "x" * (LIMIT + 1))
    assert str(caught.value) == "#1 body would be 260,001 bytes; GitHub truncates above 262,144"
    with pytest.raises(StoreError):
        check_size("#1", "é" * (LIMIT // 2 + 1))  # bytes, not characters


def test_meta_is_json_for_anything_tg_stores():
    meta = {"sessions": [{"id": "x", "n": 1.5}], "ok": True, "none": None, "text": "line\nbreak \"quoted\""}
    assert json.loads(render("", meta).split("\n")[1].replace("\\u003c", "<").replace("--\\u003e", "-->")) == meta
    assert parse(render("", meta))[1] == meta
