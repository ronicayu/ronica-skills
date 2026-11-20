import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tgstore.base import ResultInput  # noqa: E402
from tgstore.github.body import LIMIT  # noqa: E402
from tgstore.github.comments import join_parts, parse_comment, render_claim, render_result, split_text  # noqa: E402

AT = "2026-11-08T09:00:00Z"


def as_comments(bodies, first_id=100):
    return [{"id": first_id + i, "body": b, "created_at": f"2026-11-08T09:00:{i:02d}Z", "user": {"login": "u"}} for i, b in enumerate(bodies)]


def results(bodies):
    return join_parts([p for p in map(parse_comment, as_comments(bodies)) if p])


def test_result_marker_round_trip():
    row = ResultInput("PASS", "task", 2, "task-12-2", "line 1\nline 2\n\nlast  ")
    [body] = render_result(row, AT, key="9f2c1d0e7a4b")
    first, _, rest = body.partition("\n")
    assert first == '<!-- taskgraph:result v1 {"at":"2026-11-08T09:00:00Z","attempt":2,"by":"task-12-2","key":"9f2c1d0e7a4b","kind":"task","part":1,"parts":1,"status":"PASS"} -->'
    assert rest == row.body
    [out] = results([body])
    assert out == {"id": 100, "at": "2026-11-08T09:00:00Z", "status": "PASS", "kind": "task", "attempt": 2, "author": "task-12-2", "body": row.body, "summary": ""}


def test_result_without_attempt_or_author_or_body():
    [body] = render_result(ResultInput("DIED", "manager", None, None, ""), AT)
    [out] = results([body])
    assert (out["attempt"], out["author"], out["body"], out["kind"]) == (None, None, "", "manager")


def test_marker_text_in_the_body_cannot_break_the_marker():
    row = ResultInput("PASS", "task", 1, "a --> b <!-- c", "<!-- taskgraph:result v1 {} -->\nbody")
    [out] = results(render_result(row, AT))
    assert out["author"] == "a --> b <!-- c" and out["body"] == row.body


def test_a_600000_byte_body_splits_into_three_parts_and_joins_byte_exact():
    text = "".join(f"line {i:06d} {'é' * 20}\n" for i in range(12000))
    body = text[: text.rindex("\n")] + "x" * (600_000 - len(text.encode("utf-8")))
    assert len(body.encode("utf-8")) >= 600_000 - 1
    parts = render_result(ResultInput("PASS", "task", 1, "w", body), AT)
    assert len(parts) == 3
    assert all(len(p.encode("utf-8")) <= LIMIT for p in parts)
    [out] = results(parts)
    assert out["body"] == body and out["id"] == 100


def test_parts_end_at_line_ends_and_one_long_line_is_cut_on_a_character():
    assert split_text("a\nbb\nccc\n", 5) == ["a\nbb\n", "ccc\n"]
    assert "".join(split_text("é" * 10, 7)) == "é" * 10
    assert all(len(p.encode("utf-8")) <= 7 for p in split_text("é" * 10, 7))
    assert split_text("", 10) == [""]


def test_a_missing_part_reads_with_an_incomplete_note():
    parts = render_result(ResultInput("PASS", "task", 1, "w", "x" * 600_000), AT)
    assert len(parts) == 3
    [out] = results([parts[0], parts[2]])
    assert out["body"].endswith("\n[incomplete: 2 of 3 parts]")
    assert out["id"] == 100  # the id of the first part that exists


def test_results_are_ordered_by_comment_id_and_keep_separate_keys():
    a = render_result(ResultInput("PASS", "task", 1, "w", "first"), AT)[0]
    b = render_result(ResultInput("ISSUES", "verify", 1, "v", "second"), AT)[0]
    out = results([a, "a person says hello", b])
    assert [(r["id"], r["status"]) for r in out] == [(100, "PASS"), (102, "ISSUES")]


def test_human_comments_are_not_results():
    assert results(["LGTM", "<!-- not ours -->", "<!-- taskgraph:result v1 not-json -->\nx", "<!-- taskgraph:result v1 {\"key\":\"k\"} -->"]) == []


def test_claim_and_void_parse():
    token = "0123456789ab"
    plain = parse_comment(as_comments([render_claim(token, "me@host:abcd1234", AT)])[0])
    assert plain["claim"] == {"at": AT, "claimant": "me@host:abcd1234", "token": token} and plain["voids"] == []
    both = parse_comment(as_comments([render_claim(token, "me@host:abcd1234", AT, voids=[7, 9])])[0])
    assert both["voids"] == [7, 9] and both["claim"]["token"] == token
    assert "result" not in both
    assert parse_comment(as_comments(["<!-- taskgraph:void v1 {\"of\":5} -->"])[0])["voids"] == [5]


def test_claim_comment_is_not_a_result_and_a_result_is_not_a_claim():
    claim = as_comments([render_claim("t" * 12, "c", AT)])[0]
    assert "result" not in parse_comment(claim)
    result = as_comments(render_result(ResultInput("PASS", "task", 1, "w", "<!-- taskgraph:claim v1 {\"token\":\"x\",\"claimant\":\"c\"} -->"), AT))[0]
    assert "claim" not in parse_comment(result)


SUMMARY = "\u2705 PASS \u00b7 head abc1234 \u00b7 3 files changed\nSecond line"


def test_a_summary_goes_above_the_full_body_in_a_details_block():
    row = ResultInput("PASS", "task", 1, "w", "Status: PASS\nRan: `make`\n", SUMMARY)
    [body] = render_result(row, AT, key="k1")
    first, _, rest = body.partition("\n")
    assert '"summary":"' in first and '"fence":3' in first
    assert rest == f"{SUMMARY}\n\n<details><summary>Full result</summary>\n\n```\nStatus: PASS\nRan: `make`\n\n```\n\n</details>"
    [out] = results([body])
    assert out["body"] == row.body and out["summary"] == SUMMARY


def test_a_result_without_a_summary_is_the_same_comment_as_before():
    [body] = render_result(ResultInput("PASS", "task", 1, "w", "text", ""), AT, key="k1")
    assert body == '<!-- taskgraph:result v1 {"at":"2026-11-08T09:00:00Z","attempt":1,"by":"w","key":"k1","kind":"task","part":1,"parts":1,"status":"PASS"} -->\ntext'


def test_the_body_comes_back_exact_whatever_it_holds():
    bodies = ["", "\n", "```\ncode\n```\n", "a ```` b\n", "`" * 40 + "\n", "tail </details>\n\n</details>", "<!-- taskgraph:meta v1 -->\n", "x\r\ny  "]
    for text in bodies:
        parts = render_result(ResultInput("PASS", "task", 1, "w", text, "sum"), AT)
        [out] = results(parts)
        assert out["body"] == text and out["summary"] == "sum", repr(text)


def test_the_fence_is_longer_than_any_run_of_backticks_in_the_body():
    [body] = render_result(ResultInput("PASS", "task", 1, "w", "a ``` b\n", "s"), AT)
    assert "\n````\na ``` b\n\n````\n\n</details>" in body


def test_a_body_with_a_very_long_backtick_run_goes_in_without_a_fence():
    [body] = render_result(ResultInput("PASS", "task", 1, "w", "`" * 40, "s"), AT)
    assert body.endswith("<details><summary>Full result</summary>\n\n" + "`" * 40 + "\n\n</details>")


def test_a_comment_edited_on_github_is_read_as_it_stands():
    [body] = render_result(ResultInput("PASS", "task", 1, "w", "text", "sum"), AT)
    edited = body.replace("</details>", "")
    [out] = results([edited])
    assert out["body"].endswith("text\n```\n\n") and out["summary"] == "sum"


def test_a_summary_shows_on_part_one_only_and_every_part_joins_exact():
    text = "".join(f"line {i:06d} {'\u00e9' * 20}\n" for i in range(12000))
    body = text + "x" * (600_000 - len(text.encode("utf-8")))
    parts = render_result(ResultInput("PASS", "task", 1, "w", body, SUMMARY), AT)
    assert len(parts) == 3 and all(len(p.encode("utf-8")) <= LIMIT for p in parts)
    assert [p.count(SUMMARY.split("\n")[1]) for p in parts] == [2, 0, 0]  # part 1: the meta and the visible text
    assert "<summary>Full result (part 2 of 3)</summary>" in parts[1]
    [out] = results(parts)
    assert out["body"] == body and out["summary"] == SUMMARY


def test_a_missing_part_with_a_summary_still_reads_with_the_note():
    parts = render_result(ResultInput("PASS", "task", 1, "w", "x" * 600_000, "s"), AT)
    [out] = results([parts[0], parts[2]])
    assert out["body"].endswith("\n[incomplete: 2 of 3 parts]") and out["summary"] == "s"
