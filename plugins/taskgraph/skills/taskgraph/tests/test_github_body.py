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


GATE = {"label": "Review by legal", "ref": "https://example.com/review/7", "since": "2026-11-14T10:00:00Z"}
LINE = "Waiting for: [Review by legal](https://example.com/review/7) <!-- taskgraph:waiting -->"


def test_a_gate_with_a_ref_shows_a_visible_waiting_line_outside_the_block():
    meta = {"lane": "a", "gates": {"legal": GATE}}
    body = render("Why.", meta)
    assert body.startswith(f"Why.\n\n{LINE}\n\n<!-- taskgraph:meta v1\n")
    assert parse(body) == ("Why.", meta, [])
    assert render("", meta).startswith(f"{LINE}\n\n<!-- taskgraph:meta v1\n")
    assert parse(render("", meta)) == ("", meta, [])


def test_the_waiting_line_is_not_read_back_as_notes_and_is_never_doubled():
    meta = {"gates": {"legal": GATE}}
    for notes in ("", "a", "a\n", "a\n\n", "\nb", "Waiting for: typed by a person"):
        body = render(notes, meta)
        assert parse(body) == (notes, meta, [])
        assert render(*parse(body)[:2]) == body
        assert body.count(LINE) == 1
    assert parse(render("a", meta).replace("\n", "\r\n"))[:2] == ("a", meta)  # CRLF from the browser


def test_a_gate_without_a_ref_adds_no_line_and_a_cleared_gate_removes_it():
    no_ref = {"lane": "a", "gates": {"legal": {"label": "Review by legal", "ref": None, "since": "x"}}}
    assert "Waiting for" not in render("n", no_ref)
    assert render("n", no_ref).startswith("n\n\n<!-- taskgraph:meta v1\n")
    notes, meta, _ = parse(render("n", {"lane": "a", "gates": {"legal": GATE}}))
    meta.pop("gates")
    assert render(notes, meta) == render("n", {"lane": "a"}) and "Waiting for" not in render(notes, meta)


def test_two_gates_with_refs_share_one_line_and_labels_are_escaped():
    meta = {"gates": {"review": {"label": "legal [draft] <b>", "ref": "https://x.example/a b(1)"}, "legal": GATE}}
    assert render("", meta).split("\n")[0] == ("Waiting for: [Review by legal](https://example.com/review/7), "
                                               "[legal \\[draft\\] \\<b\\>](https://x.example/a%20b%281%29) <!-- taskgraph:waiting -->")
    assert parse(render("n", meta)) == ("n", meta, [])


def block_of(meta):
    return render("", meta).split("\n", 2)[2]


def test_text_typed_after_the_waiting_line_stays_notes_and_the_line_is_not_doubled():
    meta = {"gates": {"legal": GATE}}
    for typed, notes in ((f"Why.\n\n{LINE}\n\nmore\n\n", "Why.\n\nmore"), (f"Why.\n\n{LINE}\nmore\n\n", "Why.\n\nmore"),
                         (f"{LINE}\n\nmore\n\n", "more"), (f"Why.\r\n\r\n{LINE} \r\n\r\nmore\r\n\r\n", "Why.\r\n\r\nmore")):
        assert parse(typed + block_of(meta)) == (notes, meta, [])
        assert render(notes, meta).count(LINE) == 1


def test_an_extra_blank_line_before_the_block_does_not_move_the_waiting_line_into_the_notes():
    meta = {"gates": {"legal": GATE}}
    for extra in ("\n", "\n\n", "\r\n"):
        body = render("Why.", meta).replace(f"{LINE}\n\n", f"{LINE}\n\n{extra}")
        assert parse(body) == ("Why.", meta, [])
        assert render(*parse(body)[:2]) == render("Why.", meta)
    assert parse(render("Why.", meta).replace(f"\n\n{LINE}", f"\n{LINE}"))[0] == "Why."  # the blank line removed


def test_two_gates_with_refs_and_copies_left_in_the_notes_are_dropped():
    meta = {"gates": {"legal": GATE, "review": {"label": "Review", "ref": "https://x.example/r"}}}
    line = render("", meta).split("\n")[0]
    assert line.count("](") == 2 and line.endswith(" <!-- taskgraph:waiting -->")
    assert parse(render("Why.", meta)) == ("Why.", meta, [])
    moved = f"{line}\n\nWhy.\n\n{line}\n\n{LINE}\n\n" + block_of(meta)  # copies an older tg left in the notes
    assert parse(moved) == ("Why.", meta, [])
    assert render(*parse(moved)[:2]).count("Waiting for:") == 1


def test_a_line_whose_marker_was_deleted_is_notes():
    meta = {"gates": {"legal": GATE}}
    body = render("Why.", meta).replace(" <!-- taskgraph:waiting -->", "")
    assert parse(body)[0] == "Why.\n\n" + LINE.removesuffix(" <!-- taskgraph:waiting -->")


def test_ordinary_notes_round_trip_exactly_next_to_the_waiting_line():
    meta = {"gates": {"legal": GATE}}
    for notes in ("", "a", "a\n", "a\n\n", "a\n\n\n", " a ", "\nb", "a\r\n\r\nb", "x <!-- other -->", "Waiting for: you"):
        body = render(notes, meta)
        assert parse(body) == (notes, meta, [])
        assert render(*parse(body)[:2]) == body


def test_only_a_web_ref_becomes_a_link_and_a_label_mentions_nobody():
    meta = {"gates": {"legal": {"label": "Review #5 for @octocat", "ref": "notaurl"},
                      "z": {"label": "@team/x", "ref": "HTTPS://x.example/a"}}}
    line = render("", meta).split("\n")[0]
    assert line == "Waiting for: Review #5 for @‍octocat, [@‍team/x](HTTPS://x.example/a) <!-- taskgraph:waiting -->"
    assert "@o" not in line and "@t" not in line and "#5" in line  # a # stays as it is
    assert parse(render("n", meta)) == ("n", meta, [])
    assert "Waiting for" not in render("n", {"gates": {"legal": {"label": "x", "ref": "  "}}})
