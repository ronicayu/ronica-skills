import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"
VIEWS = ("graph", "lanes", "timeline")


def runner(db):
    env = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13"}

    def tg(*args):
        subprocess.run([sys.executable, str(SCRIPT), "--db", str(db), "--project", "demo", *args], check=True, capture_output=True, env=env)

    return tg


@pytest.fixture(scope="module")
def page_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("page")
    tg = runner(tmp / "t.db")

    tg("add", "Launch", "--type", "objective", "--meta", "owner=ann")
    tg("add", "Ship v1", "--type", "milestone", "--parent", "1", "--due", "2026-12-01", "--meta", "lane=dev")
    tg("add", "Build feature", "--parent", "1", "--start", "2026-10-20", "--due", "2026-11-20", "--meta", "owner=ann", "lane=dev")
    tg("add", "Write docs", "--parent", "1", "--start", "2026-10-14", "--due", "2026-10-30", "--meta", "owner=bo", "lane=docs")
    tg("add", "Vendor key", "--type", "external", "--due", "2026-11-05", "--meta", "party=Acme", "lane=dev")
    tg("add", "Undated chore", "--meta", "lane=docs")
    tg("dep", "add", "2", "3")
    tg("dep", "add", "3", "5")
    tg("baseline", "set", "--label", "plan")
    tg("date", "3", "--due", "2026-11-25")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"chromium unavailable: {e}")
        yield b
        b.close()


@pytest.mark.parametrize("view", VIEWS)
def test_page_renders_and_opens_panel(browser, page_file, view):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.goto(f"{page_file.as_uri()}?view={view}")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("view") == view
    assert page.evaluate("tasks().length") > 0
    page.wait_for_timeout(300)
    x, y = page.evaluate(
        """() => {
            const n = cy.getElementById('5');
            const p = n.renderedPosition(), b = document.getElementById('cy').getBoundingClientRect();
            return [b.left + p.x, b.top + p.y];
        }"""
    )
    page.mouse.click(x, y)
    page.wait_for_function("document.getElementById('panel').style.display === 'block'")
    assert "Vendor key" in page.inner_text("#panel")
    assert problems == []
    page.close()


def test_timeline_marks_baseline_and_today(browser, page_file):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"{page_file.as_uri()}?view=timeline")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("cy.nodes('.tl-base').map(n => n.id())") == ["tl:base:3"]
    assert page.evaluate("cy.getElementById('tl:today').data('name')") == "Today 13 Oct"
    assert page.evaluate("cy.getElementById('2').hasClass('atrisk')")
    page.close()


@pytest.fixture(scope="module")
def raid_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("raid")
    tg = runner(tmp / "t.db")
    tg("add", "Build", "--due", "2026-11-20", "--meta", "lane=dev")
    tg("add", "Vendor may slip", "--type", "risk", "--blocks", "1", "--due", "2026-10-30", "--meta", "lane=dev", "likelihood=high", "impact=high")
    tg("add", "Build server down", "--type", "issue", "--due", "2026-10-16", "--meta", "lane=dev", "severity=high")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


@pytest.mark.parametrize("view", VIEWS)
def test_risk_and_issue_render(browser, raid_file, view):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{raid_file.as_uri()}?view={view}")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("cy.getElementById('2').data('type')") == "risk"
    assert page.evaluate("cy.getElementById('3').data('type')") == "issue"
    assert page.evaluate("cy.edges('.threat').map(e => e.id())") == ["2-1"]
    assert problems == []
    page.close()


def open_page(browser, path, query="", height=900):
    page = browser.new_page(viewport={"width": 1400, "height": height})
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{path.as_uri()}{query}")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    return page, problems


COVERED = "() => covered()"


def more(page, item):
    page.click("#moreBtn")
    page.click(f"#{item}")


def pick_goal(page, gid):
    page.click("#goal")
    page.click(f'#goalList .choice[data-id="{gid}"]')


def view_option(page, name, value):
    page.click("#optsBtn")
    page.check(f'input[name="{name}"][value="{value}"]')
    page.keyboard.press("Escape")


def tick(page, selector):
    if not page.evaluate("menuOpen('filterWrap')"):
        page.click("#filterBtn")
    page.click(selector)


@pytest.mark.parametrize("view", VIEWS)
def test_fit_keeps_nodes_clear_of_legend(browser, raid_file, page_file, view):
    for path in (page_file, raid_file):
        page, problems = open_page(browser, path, f"?view={view}", height=520)
        assert page.evaluate(COVERED) is False
        page.click("#fit")
        assert page.evaluate(COVERED) is False
        assert problems == []
        page.close()


def test_legend_collapses_and_remembers(browser, page_file):
    page, problems = open_page(browser, page_file)
    short = page.evaluate("document.getElementById('legend').getBoundingClientRect().height")
    assert page.inner_text("#legendToggle") == "Legend ▸"
    page.click("#legendToggle")
    tall = page.evaluate("document.getElementById('legend').getBoundingClientRect().height")
    assert tall - short >= 20 and tall <= 64 and page.inner_text("#legendToggle") == "Legend ▾"
    page.reload()
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert not page.evaluate("document.getElementById('legend').classList.contains('closed')")
    page.click("#optsBtn")
    assert page.is_checked("#legendOn")
    page.uncheck("#legendOn")
    assert page.evaluate("document.getElementById('legend').classList.contains('closed')")
    assert problems == []
    page.close()


BY_Y = "((sel, key) => cy.nodes(sel).sort((a, b) => a.position('y') - b.position('y')).map(n => n.data(key)))"


def heads(page, view):
    sel = ".lane-bg" if view == "lanes" else ".tl-head"
    return page.evaluate(f"{BY_Y}('{sel}', 'name').map(s => s.replace(/( · |\\n)(RED|AMBER|GREEN)$/, ''))")


def test_timeline_dependency_modes_and_pinned_milestones(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    drawn = "() => cy.edges('.tl-dep').map(e => e.id()).sort()"
    assert page.evaluate(drawn) == ["5-3"]
    view_option(page, "depsMode", "critical")
    assert page.evaluate(drawn) == ["3-2", "5-3"]
    assert page.evaluate("cy.edges('.tl-critical').map(e => e.id()).sort()") == ["3-2", "5-3"]
    assert "deps=critical" in page.url
    view_option(page, "depsMode", "all")
    assert "deps=1" in page.url and len(page.evaluate(drawn)) >= 2
    names = page.evaluate(f"{BY_Y}('.tl-name[of]', 'name')")
    assert names[:2] == ["▾ ⊘ #1 Launch", "⊘ #2 Ship v1"] and names[-1] == "#6 Undated chore"
    assert [re.sub("[◔⊘✓] ", "", n) for n in names] == ["▾ #1 Launch", "#2 Ship v1", "#3 Build feature", "#5 Vendor key", "#4 Write docs", "#6 Undated chore"]
    assert heads(page, "timeline") == ["Objectives", "dev", "docs", "Undated"]
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", ("lanes", "timeline"))
def test_lane_rag_stripes(browser, page_file, view):
    page, problems = open_page(browser, page_file, f"?view={view}")
    rag = page.evaluate("cy.nodes('.lane-rag').map(n => n.data('rag'))")
    bands = page.evaluate("cy.nodes('.lane-bg').length")
    assert "red" in rag and len(rag) == (bands - 1 if view == "timeline" else bands)
    if view == "timeline":
        assert page.evaluate(f"{BY_Y}('.tl-head', 'name')")[-1] == "Undated"
    assert problems == []
    page.close()


SHOWN = "() => tasks().map(n => n.id()).sort()"


@pytest.mark.parametrize("view", VIEWS)
def test_goal_focus_from_url_shows_only_what_it_needs(browser, page_file, view):
    page, problems = open_page(browser, page_file, f"?view={view}&goal=2")
    assert page.evaluate(SHOWN) == ["1", "2", "3", "5"]
    assert page.evaluate("goal") == 2 and page.input_value("#goal") == "#2 Ship v1 · 1 Dec"
    assert page.inner_text("#goalInfo") == "0/2 done · at risk"
    assert page.evaluate("document.title") == "taskgraph · #2 Ship v1"
    assert problems == []
    page.close()


def test_goal_focus_from_picker_and_panel(browser, page_file):
    page, problems = open_page(browser, page_file)
    everything = page.evaluate(SHOWN)
    assert "4" in everything and "6" in everything and page.is_hidden("#goalInfo")
    page.click("#goal")
    options = page.evaluate("Array.from(document.querySelectorAll('#goalList .choice'), o => o.dataset.id)")
    assert options == ["", "2", "1"]
    page.click('#goalList .choice[data-id="2"]')
    assert page.evaluate(SHOWN) == ["1", "2", "3", "5"] and "goal=2" in page.url
    assert page.is_hidden("#goalList")
    pick_goal(page, "")
    assert page.evaluate(SHOWN) == everything and "goal=" not in page.url
    page.click("#goal")
    page.keyboard.type("laun")
    assert page.evaluate("Array.from(document.querySelectorAll('#goalList .choice'), o => o.dataset.id)") == ["1"]
    page.keyboard.press("Enter")
    assert page.evaluate("goal") == 1 and "goal=1" in page.url
    pick_goal(page, "")
    page.evaluate("select(3, false)")
    page.click("#focusGoal")
    assert page.evaluate(SHOWN) == ["1", "3", "5"] and "goal=3" in page.url
    assert page.input_value("#goal") == "#3 Build feature" and page.inner_text("#focusGoal") == "Show everything"
    page.click("#focusGoal")
    assert page.evaluate(SHOWN) == everything
    assert problems == []
    page.close()


@pytest.fixture(scope="module")
def programme_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("programme")
    tg = runner(tmp / "t.db")
    tg("add", "Migrate", "--type", "objective", "--meta", "owner=pd")
    tg("add", "Go live", "--type", "milestone", "--due", "2026-12-15", "--meta", "lane=Programme")
    tg("add", "Build landing zone", "--parent", "1", "--meta", "lane=Infra", "owner=priya")
    tg("add", "Write modules", "--parent", "3", "--start", "2026-09-20", "--due", "2026-10-10", "--meta", "owner=priya")
    tg("add", "Migrate data", "--parent", "1", "--meta", "lane=Data", "owner=mei")
    tg("add", "Replicate", "--parent", "5", "--start", "2026-10-15", "--due", "2026-11-15", "--meta", "owner=mei")
    tg("add", "Capacity", "--type", "risk", "--blocks", "6", "--due", "2026-10-20", "--meta", "lane=Data", "owner=priya", "likelihood=medium", "impact=high")
    tg("add", "Residency", "--type", "decision", "--due", "2026-10-25", "--meta", "lane=Security", "decider=ciso")
    tg("dep", "add", "2", "3")
    tg("dep", "add", "2", "5")
    tg("dep", "add", "6", "8")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


RAGS = f"{BY_Y}('.lane-rag', 'rag')"


def test_bands_and_rag_match_across_views(browser, programme_file):
    for view in ("lanes", "timeline"):
        page, problems = open_page(browser, programme_file, f"?view={view}")
        assert heads(page, view) == ["Objectives", "Data", "Infra", "Programme", "Security"]
        assert page.evaluate(RAGS) == ["red", "amber", "red", "red", "amber"]
        more(page, "expandAll")
        assert heads(page, view) == ["Objectives", "Data", "Infra", "Programme", "Security"]
        assert page.evaluate(RAGS) == ["red", "amber", "red", "red", "amber"]
        assert problems == []
        page.close()


def test_timeline_nests_only_within_lane(browser, programme_file):
    page, problems = open_page(browser, programme_file, "?view=timeline")
    more(page, "expandAll")
    rows = page.evaluate(f"{BY_Y}('.tl-name', 'name').map(s => s.replace(/ · (RED|AMBER|GREEN)$/, '').replace(/[◔⊘✓] /g, ''))")
    infra = rows.index("Infra")
    assert rows[infra + 1] == "▾ #3 Build landing zone" and rows[infra + 2] == "#4 Write modules"
    assert not any("#3 Build landing zone" in r for r in rows[rows.index("Objectives"):rows.index("Data")])
    assert page.evaluate("cy.nodes('.tl-name[of=\"4\"]').data('tx') === 14 + 14 - TL.names")
    assert problems == []
    page.close()


@pytest.fixture(scope="module")
def tall_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tall")
    tg = runner(tmp / "t.db")
    tg("add", "Programme", "--type", "objective")
    for i in range(1, 41):
        start = date(2026, 10, 20) + timedelta(weeks=i - 1)
        dep = ["--depends", str(i)] if i > 1 else []
        tg("add", f"Step {i}", "--parent", "1", "--start", start.isoformat(), "--due", (start + timedelta(days=6)).isoformat(), "--meta", "lane=dev", *dep)
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


ANCHOR = """() => {
    const box = document.getElementById('cy').getBoundingClientRect();
    if (view === 'graph') {
        const b = cy.getElementById('1').renderedBoundingBox();
        return b.y1 >= 0 && b.x2 <= box.width && Math.abs((b.x1 + b.x2) / 2 - box.width / 2) < 1 && Math.abs(b.y1 - 40) < 1;
    }
    const b = cy.elements().renderedBoundingBox();
    return Math.abs(b.x1 - 40) < 1 && Math.abs(b.y1 - 40) < 1;
}"""


INSIDE = """() => {
    const box = document.getElementById('cy').getBoundingClientRect();
    return tasks().every(n => { const b = n.renderedBoundingBox(); return b.x1 >= 0 && b.y1 >= 0 && b.x2 <= box.width && b.y2 <= box.height; });
}"""


@pytest.fixture(scope="module")
def solo_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("solo")
    tg = runner(tmp / "t.db")
    tg("add", "Only task", "--due", "2026-11-01")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


@pytest.mark.parametrize("view", VIEWS)
def test_readability_floor(browser, tall_file, view):
    page, problems = open_page(browser, tall_file, f"?view={view}")
    for action in (None, "expandAll", "relayout"):
        if action:
            more(page, action)
        assert abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6, action
        assert page.evaluate(ANCHOR), action
        assert page.evaluate(COVERED) is False
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_fit_button_shows_the_whole_plan(browser, tall_file, view):
    page, problems = open_page(browser, tall_file, f"?view={view}")
    assert not page.evaluate(INSIDE)
    page.click("#fit")
    assert page.evaluate("cy.zoom()") < 0.9
    assert abs(page.evaluate("cy.zoom() - fitTarget().zoom")) < 1e-6
    assert page.evaluate(INSIDE)
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_tiny_plan_is_not_blown_up(browser, solo_file, view):
    page, problems = open_page(browser, solo_file, f"?view={view}")
    assert 0.9 <= page.evaluate("cy.zoom()") <= 1.25 + 1e-9
    page.click("#fit")
    assert page.evaluate("cy.zoom()") <= 1.25 + 1e-9
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_small_plan_fits_above_floor(browser, page_file, view):
    page, problems = open_page(browser, page_file, f"?view={view}")
    assert page.evaluate("cy.zoom()") > 0.9
    assert page.evaluate(INSIDE)
    assert problems == []
    page.close()


def test_cjk_label_clamps(browser, page_file):
    page, problems = open_page(browser, page_file)
    lines = page.evaluate("clampLabel('完成所有租户的数据迁移并验证数据一致性以及回滚方案的演练', LABEL_W, 2)").split("\n")
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert problems == []
    page.close()


TOOLBAR = """() => {
    const bar = document.getElementById('toolbar'), r = bar.getBoundingClientRect();
    const kids = Array.from(document.querySelectorAll('#toolbar > *:not([hidden])'), k => k.getBoundingClientRect());
    return {
        overflow: bar.scrollWidth - bar.clientWidth, height: bar.offsetHeight, scrollLeft: bar.scrollLeft,
        left: Math.min(...kids.map(k => k.left)), right: Math.max(...kids.map(k => k.right)),
        gap: document.getElementById('cy').getBoundingClientRect().top - r.bottom,
        project: document.getElementById('project').getBoundingClientRect().left
    };
}"""


@pytest.mark.parametrize("view", VIEWS)
def test_toolbar_never_overflows(browser, page_file, view):
    for width in (1024, 1280, 1440, 1920):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(f"{page_file.as_uri()}?view={view}")
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        bar = page.evaluate(TOOLBAR)
        assert bar["overflow"] <= 0 and bar["left"] >= 0 and bar["right"] <= width, (width, bar)
        assert bar["height"] <= (140 if width == 1024 else 96), (width, bar)
        assert bar["gap"] == 0, (width, bar)
        page.click("#fit")
        more(page, "expandAll")
        bar = page.evaluate(TOOLBAR)
        assert bar["scrollLeft"] == 0 and bar["project"] >= 0
        page.close()


def test_search_reveals_collapsed_and_counts(browser, page_file):
    page, problems = open_page(browser, page_file)
    more(page, "collapseAll")
    page.fill("#search", "write")
    page.wait_for_timeout(300)
    assert page.evaluate("tasks().filter(n => !n.hasClass('dim')).map(n => n.id())") == ["4"]
    assert page.inner_text("#searchCount") == "1 match"
    assert page.evaluate("expandedIds().has(1)")
    page.fill("#search", "zzz")
    page.wait_for_timeout(300)
    assert page.inner_text("#searchCount") == "No matches"
    assert page.evaluate("cy.nodes('.dim').length") == 0
    page.fill("#search", "e")
    page.wait_for_timeout(300)
    hits = page.evaluate("searchHits('e').map(n => n.id)")
    assert hits == [3, 4, 5, 6, 2] and page.inner_text("#searchCount") == "5 matches"
    page.press("#search", "Enter")
    assert page.evaluate("document.getElementById('panel').style.display") == "block"
    assert page.evaluate("pinned") == hits[0] and page.inner_text("#searchCount") == "1 of 5 matches"
    page.press("#search", "Enter")
    assert page.evaluate("pinned") == hits[1] and page.inner_text("#searchCount") == "2 of 5 matches"
    page.press("#search", "Shift+Enter")
    assert page.evaluate("pinned") == hits[0] and page.inner_text("#searchCount") == "1 of 5 matches"
    page.fill("#search", "ee")
    page.wait_for_timeout(300)
    assert "of" not in page.inner_text("#searchCount")
    page.fill("#search", "")
    page.wait_for_timeout(300)
    assert page.inner_text("#searchCount") == "" and page.evaluate("cy.nodes('.dim').length") == 0
    assert problems == []
    page.close()


def node_xy(page, nid):
    return page.evaluate(
        f"""() => {{
            const p = cy.getElementById('{nid}').renderedPosition(), b = document.getElementById('cy').getBoundingClientRect();
            return [b.left + p.x, b.top + p.y];
        }}"""
    )


def test_hover_does_not_fade(browser, page_file):
    page, problems = open_page(browser, page_file)
    page.mouse.move(*node_xy(page, "5"))
    page.wait_for_timeout(200)
    assert page.evaluate("cy.nodes('.faded').length") == 0
    assert page.evaluate("cy.getElementById('5').hasClass('hl') && cy.getElementById('3').hasClass('hl')")
    left, top = page.evaluate("(b => [b.left, b.top])(document.getElementById('cy').getBoundingClientRect())")
    page.mouse.move(left + 5, top + 5)
    page.wait_for_timeout(100)
    assert page.evaluate("cy.elements('.hl').length") == 0
    page.mouse.click(*node_xy(page, "5"))
    page.wait_for_timeout(200)
    assert page.evaluate("cy.nodes('.faded').length") > 0
    assert float(page.evaluate("cy.nodes('.faded')[0].style('opacity')")) == 0.35
    assert problems == []
    page.close()


@pytest.fixture(scope="module")
def done_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("done")
    tg = runner(tmp / "t.db")
    tg("add", "Ship", "--type", "milestone", "--due", "2026-10-01")
    tg("add", "Build", "--due", "2026-09-20")
    tg("dep", "add", "1", "2")
    tg("done", "2")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out


@pytest.mark.parametrize("view", VIEWS)
def test_all_done_offers_show_done(browser, done_file, view):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{done_file.as_uri()}?view={view}")
    page.wait_for_function("typeof cy !== 'undefined'")
    assert page.evaluate("tasks().length") == 0
    assert page.is_visible("#empty")
    assert page.inner_text("#emptyText") == "All 2 items are done."
    assert page.inner_text("#emptyAction") == "Show done"
    if view == "timeline":
        assert page.evaluate("cy.nodes('.bg').length") == 0
    page.click("#emptyAction")
    assert page.evaluate("tasks().length") == 2
    assert page.is_hidden("#empty")
    assert problems == []
    page.close()


def test_nothing_matches_offers_reset(browser, page_file):
    page, problems = open_page(browser, page_file)
    pick_goal(page, "2")
    tick(page, "#filters [data-facet=type] .link:text('None')")
    assert page.evaluate("tasks().length") == 0
    assert page.inner_text("#emptyText") == "Nothing matches the current filters."
    assert "types=none" in page.url
    page.keyboard.press("Escape")
    page.click("#emptyAction")
    assert page.evaluate("types.size") == 7 and page.evaluate("chipList().length") == 0
    assert page.input_value("#goal") == "" and "goal=" not in page.url
    assert page.evaluate("tasks().length") > 0 and page.is_hidden("#empty")
    assert problems == []
    page.close()


def test_date_format(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    assert page.evaluate("day('2026-10-30')") == "30 Oct"
    assert page.evaluate("day('2027-03-15')") == "15 Mar 2027"
    assert page.evaluate("cy.getElementById('3').data('label')") == "20 Oct–25 Nov · conflict"
    page.click("#goal")
    assert page.text_content('#goalList .choice[data-id="2"]') == "#2 Ship v11 Dec"
    page.keyboard.press("Escape")
    page.evaluate("select(3, false)")
    text = page.inner_text("#panel")
    assert "Due\t25 Nov · +5d vs 20 Nov · plan" in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", page.text_content("#panel"))
    assert re.search(r"Created\d{1,2} Oct \d{2}:\d{2}", page.text_content("#details"))
    assert re.fullmatch(r"Generated \d{1,2} \w{3}( \d{4})? \d{2}:\d{2}", page.inner_text("#stamp"))
    assert problems == []
    page.close()


def test_status_words_and_rag_headers(browser, programme_file):
    page, problems = open_page(browser, programme_file, "?view=timeline")
    assert page.evaluate("cy.getElementById('2').data('label')") == "15 Dec · at risk"
    more(page, "expandAll")
    assert page.evaluate("cy.getElementById('6').data('label')").endswith(" · conflict")
    assert page.evaluate("cy.getElementById('4').data('label')") == "20 Sep–10 Oct · 3d late"
    assert page.evaluate(f"{BY_Y}('.tl-head', 'name')") == ["Objectives · RED", "Data · AMBER", "Infra · RED", "Programme · RED", "Security · AMBER"]
    page.close()
    page, problems = open_page(browser, programme_file, "?view=lanes")
    assert page.evaluate("cy.getElementById('lane:1').data('name')").endswith("\nAMBER")
    assert page.evaluate("cy.nodes('.lane-rag')[0].width()") == 8
    assert problems == []
    page.close()


def luminance(hex_):
    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(hex_[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


CONTRAST = [  # foreground token, background token, is text
    ("text", "surface", True), ("muted", "surface", True), ("muted", "control", True), ("muted", "bg", True),
    ("muted", "band-1", True), ("link", "surface", True), ("amber-text", "surface", True), ("red-text", "surface", True),
    ("on-text", "on", True), ("goal", "bg", True), ("amber", "bg", True), ("red", "bg", True),
    ("edge", "surface", False), ("edge", "control", False), ("axis", "bg", False), ("axis", "band-1", False),
    *[(f"st-{s}-fg", f"st-{s}-bg", True) for s in ("ready", "in_progress", "blocked", "done")],
    ("st-blocked-bd", "bg", False), ("st-done-bg", "bg", False), ("st-ready-bd", "bg", False),
    *[(f"mark-{s}", "surface", True) for s in ("ready", "in_progress", "blocked", "done")],
    *[(f"load-{i}-ink", f"load-{i}", True) for i in (1, 2, 3, 4)], ("over-ink", "over", True),
]
TOKENS = "Object.fromEntries([...new Set(%s.flat())].map(k => [k, getComputedStyle(document.documentElement).getPropertyValue('--' + k).trim()]))"


def hex6(value):
    value = value.lstrip("#")
    return "#" + ("".join(c * 2 for c in value) if len(value) == 3 else value[:6])


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_contrast_tokens(browser, page_file, theme):
    page, problems = open_page(browser, page_file, f"?theme={theme}")
    names = [[fg, bg] for fg, bg, _ in CONTRAST]
    tokens = page.evaluate(TOKENS % json.dumps(names))
    for fg, bg, text in CONTRAST:
        ratio = contrast(hex6(tokens[fg]), hex6(tokens[bg]))
        assert ratio >= (4.5 if text else 3.0), (theme, fg, bg, round(ratio, 2))
    # The canvas draws from the same tokens.
    assert page.evaluate("cy.getElementById('2').data('derived_status')") == "blocked"
    rgb = page.evaluate("cy.getElementById('2').style('background-color')")
    assert rgb == "rgb(%d,%d,%d)" % tuple(int(hex6(tokens["st-blocked-bg"])[i:i + 2], 16) for i in (1, 3, 5))
    assert problems == []
    page.close()


def theme_of(page):
    return page.evaluate("[document.documentElement.dataset.theme, getComputedStyle(document.body).backgroundColor, cy.getElementById('3').style('background-color')]")


def test_theme_follows_system_and_remembers_a_pick(browser, page_file):
    seen = {}
    for scheme in ("dark", "light"):
        context = browser.new_context(viewport={"width": 1400, "height": 900}, color_scheme=scheme)
        page = context.new_page()
        page.goto(page_file.as_uri())
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        seen[scheme] = theme_of(page)
        assert seen[scheme][0] == scheme
        context.close()
    assert seen["dark"][1] != seen["light"][1] and seen["dark"][2] != seen["light"][2]

    context = browser.new_context(viewport={"width": 1400, "height": 900}, color_scheme="dark")
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    # A ?theme= link wins over the system and stays in the URL.
    page.goto(page_file.as_uri() + "?view=timeline&theme=light")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert theme_of(page) == seen["light"]
    page.click("#viewLanes")
    assert "theme=light" in page.url
    page.click("#optsBtn")
    assert page.is_checked('input[name="theme"][value="light"]')
    # Picking one switches at once, is remembered, and drops the link's choice.
    page.check('input[name="theme"][value="dark"]')
    assert theme_of(page)[0] == "dark" and theme_of(page)[2] == seen["dark"][2]
    assert "theme=" not in page.url
    page.check('input[name="theme"][value="light"]')
    page.reload()
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert theme_of(page)[0] == "light"
    page.click("#optsBtn")
    page.check('input[name="theme"][value="auto"]')
    assert theme_of(page)[0] == "dark"
    assert problems == []
    context.close()


def test_print_is_light_from_dark(browser, page_file):
    page, problems = open_page(browser, page_file, "?theme=dark&task=3")
    dark = page.evaluate("cy.getElementById('3').style('background-color')")
    page.evaluate("printSheet()")
    # The sheet carries the light tokens and a light plan image; the screen stays dark.
    assert page.evaluate("getComputedStyle(document.getElementById('print')).getPropertyValue('--bg').trim()") == "#f5f6f8"
    corner = page.evaluate("""new Promise(done => {
        const img = new Image();
        img.onload = () => {
            const c = Object.assign(document.createElement('canvas'), { width: img.width, height: img.height }).getContext('2d');
            c.drawImage(img, 0, 0);
            done([...c.getImageData(1, 1, 1, 1).data].slice(0, 3));
        };
        img.src = document.querySelector('#print .plan').src;
    })""")
    assert corner == [245, 246, 248]
    assert page.evaluate("[...document.querySelectorAll('#print .badge')].some(b => getComputedStyle(b).backgroundColor === 'rgb(227, 230, 234)')")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("cy.getElementById('3').style('background-color')") == dark
    assert problems == []
    page.close()


PANEL_OPEN = "document.getElementById('panel').style.display === 'block'"


def test_panel_close_and_esc(browser, page_file, raid_file):
    page, problems = open_page(browser, page_file)
    page.evaluate("select(5, false)")
    assert page.is_visible("#panelClose")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--panel-w').trim()") == "340px"
    page.click("#panelClose")
    assert page.evaluate("document.getElementById('panel').style.display") == "none"
    assert page.evaluate("pinned") is None
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--panel-w').trim()") == "0px"
    page.evaluate("select(5, false)")
    page.keyboard.press("Escape")
    assert not page.evaluate(PANEL_OPEN)
    page.evaluate("select(5, false)")
    page.fill("#search", "vendor")
    page.press("#search", "Escape")
    assert page.input_value("#search") == "" and page.evaluate(PANEL_OPEN)
    page.click("#goal")
    page.keyboard.press("Escape")
    assert page.is_hidden("#goalList") and page.evaluate(PANEL_OPEN)
    page.evaluate("select(2, false)")
    assert page.inner_text("#focusGoal") == "Focus on this goal"
    page.evaluate("select(3, false)")
    assert page.inner_text("#focusGoal") == "Show only what this needs"
    assert problems == []
    page.close()
    page, problems = open_page(browser, raid_file)
    page.evaluate("select(2, false)")
    assert page.evaluate(PANEL_OPEN) and page.query_selector("#focusGoal") is None
    assert problems == []
    page.close()


LEGEND_SHOWN = "Array.from(document.querySelectorAll('#legendBody .col > div'), d => [d.textContent.trim().replace(/^[◔⊘✓] /, ''), !d.hidden])"


def legend_shown(page):
    return dict(page.evaluate(LEGEND_SHOWN))


def test_legend_defaults_and_rows(browser, page_file, raid_file):
    for width, closed in ((1280, True), (1440, True)):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(page_file.as_uri())
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        assert page.evaluate("document.getElementById('legend').classList.contains('closed')") is closed
        assert page.evaluate("localStorage.getItem('taskgraph.legend')") is None
        page.close()
    page, problems = open_page(browser, raid_file, "?view=graph")
    assert legend_shown(page)["Baseline due"] is False
    page.close()
    page, problems = open_page(browser, page_file, "?view=graph")
    shown = legend_shown(page)
    assert shown["Baseline due"] is True and shown["Lane RAG"] is False and shown["Done"] is False
    tick(page, "#status-done")
    assert legend_shown(page)["Done"] is True and "status=ready,in_progress,blocked,done" in page.url
    page.close()
    page, problems = open_page(browser, page_file, "?view=lanes")
    assert legend_shown(page)["Lane RAG"] is True
    assert problems == []
    page.close()
    for view in VIEWS:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{page_file.as_uri()}?view={view}")
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        assert page.evaluate("document.getElementById('legend').getBoundingClientRect().height") <= 36
        page.click("#legendToggle")
        assert page.evaluate("document.getElementById('legend').getBoundingClientRect().height") <= 72
        page.close()


BAND_OF = """id => {
    const y = cy.getElementById(String(id)).position('y');
    return cy.nodes('.lane-bg').filter(b => Math.abs(b.position('y') - y) < b.data('h') / 2).data('name').split('\\n')[0];
}"""


def test_lanes_by_owner_fallback(browser, programme_file, page_file):
    page, problems = open_page(browser, programme_file, "?view=lanes&lanes=owner")
    assert heads(page, "lanes") == ["ciso", "mei", "pd", "priya", "Unassigned"]
    assert page.evaluate(f"({BAND_OF})(8)") == "ciso"
    assert page.evaluate(f"({BAND_OF})(2)") == "Unassigned"
    page.close()
    page, problems = open_page(browser, page_file, "?view=lanes")
    names = heads(page, "lanes")
    assert names[0] == "Objectives" and "Unassigned" not in names
    assert page.evaluate(f"({BAND_OF})(1)") == "Objectives"
    assert problems == []
    page.close()


def test_expand_collapse_refit(browser, page_file, tall_file):
    page, problems = open_page(browser, page_file)
    more(page, "collapseAll")
    assert page.evaluate(INSIDE)
    assert abs(page.evaluate("cy.zoom() - fitTarget().zoom")) < 1e-6
    page.close()
    page, problems = open_page(browser, tall_file)
    more(page, "expandAll")
    assert abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6
    more(page, "collapseAll")
    assert abs(page.evaluate("cy.zoom() - Math.max(READABLE, fitTarget().zoom)")) < 1e-6
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_export_png(browser, page_file, tmp_path, view):
    import struct
    page, problems = open_page(browser, page_file, f"?view={view}&goal=2")
    page.evaluate("select(3, false)")
    faded = page.evaluate("cy.nodes('.faded').map(n => n.id()).sort()")
    with page.expect_download() as info:
        more(page, "exportPng")
    download = info.value
    assert download.suggested_filename == f"taskgraph-demo-goal-2-{view}-2026-10-13.png"
    out = tmp_path / download.suggested_filename
    download.save_as(out)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width > 400 and height > 200
    assert page.evaluate("cy.nodes('.faded').map(n => n.id()).sort()") == faded
    assert page.evaluate("exportTitle()") == f"taskgraph · demo · #2 Ship v1 · {dict(graph='Graph', lanes='Swimlane', timeline='Timeline')[view]}"
    assert problems == []
    page.close()


def test_back_and_forward_step_through_navigation(browser, page_file):
    page, problems = open_page(browser, page_file)
    state = "() => [view, goal, depsMode, location.search]"
    page.click("#viewTimeline")
    pick_goal(page, "2")
    view_option(page, "depsMode", "critical")
    tick(page, "#type-task")
    page.keyboard.press("Escape")
    assert page.evaluate(state)[:3] == ["timeline", 2, "critical"]
    assert "types=" in page.evaluate("location.search")
    page.go_back()
    page.wait_for_function("depsMode === 'off'")
    assert page.evaluate(state)[:3] == ["timeline", 2, "off"]
    assert page.evaluate("document.querySelector('input[name=depsMode]:checked').value") == "off"
    page.go_back()
    page.wait_for_function("goal === null")
    assert page.evaluate(state)[:3] == ["timeline", None, "off"] and page.input_value("#goal") == ""
    page.go_back()
    page.wait_for_function("view === 'graph'")
    assert page.evaluate("tasks().length") > 0 and page.url.startswith("file:")
    page.go_forward()
    page.wait_for_function("view === 'timeline'")
    assert page.evaluate("cy.nodes('.tl-head').length") > 0
    assert problems == []
    page.close()


GROW = """() => {
    const base = DATA.nodes.find(n => n.id === 5);
    const extra = [101, 102, 103, 104, 105, 106, 107, 108].map((id, i) => ({ ...base, id, title: 'Added ' + id, depends_on: [], blocks: [], due: '2026-11-0' + (i + 1), start: null, children: [], parent: null, conflicts: [], outlook: null }));
    applyData({ ...DATA, nodes: [...DATA.nodes, ...extra] });
}"""


@pytest.mark.parametrize("view", VIEWS)
def test_refresh_and_resize_keep_the_plan_fitted(browser, page_file, view):
    page, problems = open_page(browser, page_file, f"?view={view}", height=700)
    assert page.evaluate(INSIDE)
    page.evaluate(GROW)
    assert page.evaluate(INSIDE) or abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6
    assert page.evaluate("hiddenTasks()") is False or page.evaluate("cy.zoom() <= 0.9 + 1e-9")
    page.set_viewport_size({"width": 900, "height": 600})
    page.wait_for_timeout(400)
    assert page.evaluate("userMoved") is False
    assert page.evaluate(INSIDE) or abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6
    assert problems == []
    page.close()


def test_view_left_alone_after_viewer_zooms(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=graph")
    box = page.evaluate("document.getElementById('cy').getBoundingClientRect().toJSON()")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)
    assert page.evaluate("userMoved") is True
    zoom = page.evaluate("cy.zoom()")
    page.set_viewport_size({"width": 1200, "height": 800})
    page.wait_for_timeout(400)
    assert abs(page.evaluate("cy.zoom()") - zoom) < 1e-6
    page.click("#fit")
    assert page.evaluate("userMoved") is False and page.evaluate(INSIDE)
    assert problems == []
    page.close()


def test_fit_whole_survives_refresh(browser, tall_file):
    page, problems = open_page(browser, tall_file, "?view=graph")
    page.click("#fit")
    assert page.evaluate(INSIDE)
    page.evaluate("applyData({ ...DATA })")
    assert page.evaluate(INSIDE) and page.evaluate("cy.zoom()") < 0.9
    page.click("#viewLanes")
    assert abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6
    assert problems == []
    page.close()


def test_timeline_search_enter_keeps_names_in_view(browser, tall_file):
    page, problems = open_page(browser, tall_file, "?view=timeline")
    page.fill("#search", "Step 35")
    page.wait_for_timeout(300)
    page.focus("#search")
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    names = page.evaluate("cy.nodes('.tl-name[of]').map(n => n.renderedBoundingBox().x1)")
    assert min(names) >= 0
    row = page.evaluate("""() => {
        const b = cy.getElementById(String(pinned)).renderedBoundingBox(), box = document.getElementById('cy').getBoundingClientRect();
        return b.y1 >= 0 && b.y2 <= box.height;
    }""")
    assert row and page.evaluate("byId.get(pinned).title") == "Step 35"
    assert page.evaluate("document.getElementById('panel').style.display") == "block"
    assert problems == []
    page.close()


def test_deleted_goal_leaves_the_url(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline&goal=2")
    assert "goal=2" in page.url
    page.evaluate("""() => {
        const nodes = DATA.nodes.filter(n => n.id !== 2).map(n => ({ ...n, depends_on: n.depends_on.filter(i => i !== 2), blocks: n.blocks.filter(i => i !== 2), children: n.children.filter(i => i !== 2) }));
        applyData({ ...DATA, nodes, edges: DATA.edges.filter(e => e.source !== 2 && e.target !== 2) });
    }""")
    assert "goal=" not in page.url and "view=timeline" in page.url
    assert page.input_value("#goal") == "" and "#2" not in page.evaluate("document.title")
    assert page.evaluate("tasks().length") > 0
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_collapsed_summary_shows_late_work_inside(browser, programme_file, view):
    page, problems = open_page(browser, programme_file, f"?view={view}")
    more(page, "collapseAll")
    marked = "id => [cy.getElementById(String(id)).data('label'), cy.getElementById(String(id)).hasClass('late')]"
    assert page.evaluate("expandedIds().has(1) && !expandedIds().has(3)")
    page.evaluate("toggleExpand(1)")
    label, late = page.evaluate(f"({marked})(1)")
    assert "1 late inside" in label and late
    page.evaluate("toggleExpand(1)")
    label, late = page.evaluate(f"({marked})(3)")
    assert "1 late inside" in label and late
    more(page, "expandAll")
    label, late = page.evaluate(f"({marked})(3)")
    assert "late inside" not in label and not late
    assert page.evaluate("cy.getElementById('4').hasClass('late')")
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_external_label_names_who_to_chase(browser, page_file, view):
    page, problems = open_page(browser, page_file, f"?view={view}")
    calm = page.evaluate("cy.getElementById('5').data('label')")
    if view != "timeline":
        assert "Acme" in calm and ("needed by" not in calm or calm.index("Acme") < calm.index("needed by"))
    page.evaluate("applyData({ ...DATA, nodes: DATA.nodes.map(n => n.id === 5 ? { ...n, chase_due: true, meta: { ...n.meta, chase: '2026-10-10' } } : n) })")
    label = page.evaluate("cy.getElementById('5').data('label')")
    assert "chase Acme" in label and "chase due" not in label and label.count("Acme") == 1
    assert problems == []
    page.close()


def test_panel_shows_driving_chain(browser, page_file):
    page, problems = open_page(browser, page_file)
    page.evaluate("select(2, false)")
    assert page.text_content("#chainHead") == "Driving chain"
    items = page.evaluate("Array.from(document.querySelectorAll('#chainHead + ul li span'), s => s.textContent)")
    assert items == ["#5 Vendor key", "#3 Build feature"]
    page.click("#chainHead + ul li:first-child")
    page.wait_for_function("pinned === 5")
    assert page.query_selector("#chainHead") is None
    assert problems == []
    page.close()


def test_conflict_line_explains_itself(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    edge = page.evaluate("cy.edges('.tl-conflict').map(e => e.id())")
    assert edge == ["5-3"]
    box = page.evaluate("""() => {
        const e = cy.getElementById('5-3'), c = document.getElementById('cy').getBoundingClientRect();
        const p = e.renderedMidpoint();
        return [c.left + p.x, c.top + p.y];
    }""")
    page.mouse.move(*box)
    page.wait_for_timeout(250)
    story = page.text_content("#tip")
    assert page.is_visible("#tip")
    assert story == "#3 waits for #5 · #5 is due 5 Nov but #3 needs it 20 Oct (16d short)"
    page.mouse.click(*box)
    page.wait_for_function("pinned === 5")
    assert "#5 due 5 Nov after #3 needs it 20 Oct" in page.inner_text("#panel")
    page.mouse.move(5, 300)
    assert page.text_content("#tip") == "" and page.is_hidden("#tip")
    assert problems == []
    page.close()


def test_export_png_includes_the_legend(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    items = page.evaluate("legendItems().then(l => l.map(i => i.text))")
    shown = page.evaluate("[...document.querySelectorAll('#legendBody .col > div')].filter(d => !d.hidden).map(d => d.textContent.trim())")
    assert items == shown and "Milestone" in items and "Lane RAG" in items and "Done" not in items
    page.click("#legendToggle")
    assert page.evaluate("legendItems().then(l => l.length)") == len(items)
    import struct
    with page.expect_download() as info:
        more(page, "exportPng")
    data = open(info.value.path(), "rb").read()
    w, h = struct.unpack(">II", data[16:24])
    plan = page.evaluate("(async () => (await createImageBitmap(await cy.png({ output: 'blob-promise', full: true, scale: 2, maxWidth: 8000, maxHeight: 8000 }))).height)()")
    k = max(1, w / 2400)
    assert h >= plan + round(64 * k) + round(30 * k)
    assert problems == []
    page.close()


def test_filter_popover_and_chips(browser, page_file):
    page, problems = open_page(browser, page_file)
    assert page.is_hidden("#filters") and page.is_hidden("#clearAll") and page.evaluate("chipList().length") == 0
    page.click("#filterBtn")
    assert page.is_visible("#type-task") and page.get_attribute("#filterBtn", "aria-expanded") == "true"
    page.click("#type-task")
    page.click("#type-external")
    assert page.is_visible("#type-task")
    assert page.text_content("#chips") == "Types: −task, −external×" and page.is_visible("#clearAll")
    assert "5" not in page.evaluate("tasks().map(n => n.id())")
    page.mouse.click(700, 500)
    assert page.is_hidden("#filters")
    page.click('#chips .chip[data-key=types] button')
    assert page.evaluate("types.size") == 7 and page.is_hidden("#clearAll")
    owner = '#filters [data-facet=owner][data-value="bo"]'
    page.click("#filterBtn")
    page.click("#filters [data-facet=owner] .link:text('None')")
    page.click(owner)
    assert page.evaluate("tasks().map(n => n.id()).sort()") == ["1", "4"] and "owner=bo" in page.url
    assert page.evaluate("autoOpened.size") == 0
    assert page.text_content("#chips") == "Owner: bo×"
    page.click(owner)
    assert "owner=none" in page.url and page.text_content("#chips") == "Owner: none×"
    page.click("#filters [data-facet=owner] .link:text('All')")
    assert page.evaluate("owners") is None and "owner=" not in page.url
    page.click("#flag-late")
    assert page.evaluate("tasks().length") == 0
    page.click("#flag-atrisk")
    assert page.evaluate("tasks().map(n => n.id()).sort()") == ["1", "2"] and "flag=late,atrisk" in page.url
    assert page.text_content("#chips") == "Late or At risk×"
    page.keyboard.press("Escape")
    assert page.is_hidden("#filters")
    page.click("#clearAll")
    assert page.evaluate("flags.size") == 0 and page.evaluate("location.search") == "?project=demo"
    page.click("#filterBtn")
    page.click("#status-done")
    assert page.text_content("#chips") == "Done shown×"
    assert problems == []
    page.close()


def test_toolbar_rows_hold_still(browser, page_file):
    page, problems = open_page(browser, page_file)
    spots = "() => ['project', 'goal', 'viewGraph', 'search', 'filterBtn', 'fit', 'moreBtn'].map(id => { const r = document.getElementById(id).getBoundingClientRect(); return [id, Math.round(r.top)]; })"
    before = page.evaluate(spots)
    page.click("#viewTimeline")
    pick_goal(page, "2")
    tick(page, "#type-task")
    page.keyboard.press("Escape")
    assert page.evaluate(spots) == before
    page.keyboard.press("e")
    assert page.evaluate("expandedIds().size") == 1
    page.keyboard.press("c")
    page.keyboard.press("f")
    assert page.evaluate("keepWhole") is True
    more(page, "relayout")
    assert page.is_hidden("#more")
    assert problems == []
    page.close()


def test_search_fields_exact_id_and_results(browser, programme_file, page_file):
    page, problems = open_page(browser, programme_file)
    more(page, "expandAll")
    hits = lambda q: page.evaluate(f"searchHits({q!r}).map(n => n.id)")
    assert hits("priya") == [3, 4, 7] and hits("infra") == [3, 4] and hits("ciso") == [8]
    assert page.evaluate("searchMatches('priya').map(h => h.m.field)") == ["owner", "owner", "owner"]
    page.close()
    page, problems = open_page(browser, page_file)
    hits = lambda q: page.evaluate(f"searchHits({q!r}).map(n => n.id)")
    assert hits("#1") == [1] and hits("#5") == [5] and hits("acme") == [5] and hits("bo") == [4]
    page.evaluate("applyData({ ...DATA, nodes: DATA.nodes.map(n => n.id === 6 ? { ...n, notes: 'Ask legal about the runbook', meta: { ...n.meta, tags: ['ops', 'q4'] } } : n) })")
    assert hits("runbook") == [6] and hits("q4") == [6]
    page.press("body", "/")
    assert page.evaluate("document.activeElement.id") == "search"
    page.keyboard.type("e")
    page.wait_for_timeout(300)
    assert page.is_visible("#results")
    rows = page.evaluate("Array.from(document.querySelectorAll('#results .hit'), r => [r.dataset.id, r.querySelector('.when').textContent])")
    assert [r[0] for r in rows] == ["3", "4", "5", "6", "2"] and rows[-1][1] == "dev · lane"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("document.querySelector('#results .active').dataset.id") == "4" and page.evaluate("pinned") is None
    page.keyboard.press("Enter")
    assert page.evaluate("pinned") == 4 and page.is_hidden("#results") and page.inner_text("#searchCount") == "2 of 5 matches"
    page.keyboard.press("Enter")
    assert page.evaluate("pinned") == 5
    page.keyboard.press("ArrowDown")
    page.click('#results .hit[data-id="2"]')
    assert page.evaluate("pinned") == 2
    assert page.is_visible("#searchClear")
    page.click("#searchClear")
    assert page.input_value("#search") == "" and page.is_hidden("#searchClear") and page.evaluate("document.activeElement.id") == "search"
    assert problems == []
    page.close()


def test_search_says_what_a_filter_hides(browser, page_file):
    page, problems = open_page(browser, page_file)
    tick(page, "#type-external")
    page.keyboard.press("Escape")
    page.fill("#search", "vendor")
    page.wait_for_timeout(300)
    assert page.inner_text("#searchCount") == "No matches · 1 hidden by Types Show"
    page.click("#searchShow")
    assert page.evaluate("types.has('external')") and page.inner_text("#searchCount") == "1 match"
    page.fill("#search", "added")
    page.wait_for_timeout(300)
    page.evaluate(GROW)
    assert page.inner_text("#searchCount") == "8 matches (8 new)"
    assert page.evaluate("cy.nodes('.new').length") == 8
    assert problems == []
    page.close()


def test_search_folds_what_it_opened(browser, programme_file):
    page, problems = open_page(browser, programme_file)
    more(page, "collapseAll")
    assert not page.evaluate("expandedIds().has(3)")
    page.fill("#search", "write modules")
    page.wait_for_timeout(300)
    assert page.evaluate("expandedIds().has(3)") and page.evaluate("tasks().map(n => n.id())").count("4") == 1
    page.fill("#search", "")
    page.wait_for_timeout(300)
    assert not page.evaluate("expandedIds().has(3)")
    page.fill("#search", "write modules")
    page.wait_for_timeout(300)
    assert page.evaluate("autoOpened.has(3)")
    page.evaluate("toggleExpand(3), toggleExpand(3)")
    page.fill("#search", "")
    page.wait_for_timeout(300)
    assert page.evaluate("expandedIds().has(3)")
    assert problems == []
    page.close()


@pytest.mark.parametrize("view", VIEWS)
def test_clicked_node_stays_in_view(browser, programme_file, view):
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto(f"{programme_file.as_uri()}?view={view}")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    more(page, "expandAll")
    right = page.evaluate("""() => tasks().max(n => n.renderedBoundingBox({ includeLabels: view !== 'timeline' }).x2).ele.id()""")
    page.mouse.click(*node_xy(page, right))
    page.wait_for_timeout(700)
    assert page.evaluate("pinned") == int(right)
    inside = page.evaluate("""id => {
        const b = cy.getElementById(id).renderedBoundingBox({ includeLabels: view !== 'timeline' }), box = document.getElementById('cy').getBoundingClientRect();
        return [b.x1 >= 0 && b.x2 <= box.width + 1 && b.y1 >= 0 && b.y2 <= box.height + 1, cy.nodes('.tl-name').length ? cy.nodes('.tl-name').renderedBoundingBox().x1 >= -1 : true];
    }""", right)
    assert inside == [True, True], (view, right)
    page.close()


HEADS = "Array.from(document.querySelectorAll('#panel h3'), h => h.textContent)"


def test_panel_leads_with_why_it_is_red(browser, programme_file):
    page, problems = open_page(browser, programme_file)
    more(page, "expandAll")
    page.evaluate("select(2, false)")
    heads = page.evaluate(HEADS)
    assert heads[:3] == ["Why it is at risk", "Blocks", "Blocked by"] and heads[-1] == "Notes"
    outlook = page.evaluate("Array.from(document.querySelectorAll('#facts tr'), r => r.textContent).find(t => t.startsWith('Outlook'))")
    assert outlook.startswith("OutlookAt risk — #4 Write modules is 3d late")
    late = page.evaluate("Array.from(document.querySelectorAll('#whyHead ~ ul li'), li => li.textContent)")
    assert "○#4 Write modules3d late" in late
    assert page.text_content("#facts").startswith("Date15 Dec")
    assert page.is_hidden("#details tr") and page.text_content("#details").startswith("DetailsTypemilestone")
    page.evaluate("select(4, false)")
    assert page.evaluate(HEADS)[0] == "Why it is red" and "Due 10 Oct · 3d late" in page.inner_text("#panel")
    assert page.text_content("#facts").startswith("Ownerpriya")
    assert problems == []
    page.close()


def test_panel_back_steps_and_deep_link(browser, page_file):
    context = browser.new_context(viewport={"width": 1400, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{page_file.as_uri()}?view=lanes&task=3")
    page.wait_for_function("typeof cy !== 'undefined' && pinned === 3")
    assert page.evaluate(PANEL_OPEN) and "task=3" in page.url and page.query_selector("#panelBack") is None
    page.click("#copyLink")
    page.wait_for_function("document.getElementById('copyLink').textContent === 'Copied'")
    assert page.evaluate("navigator.clipboard.readText()") == page.url and page.url.endswith("view=lanes&task=3")
    page.click("h3:text('Blocks') + ul li")
    page.wait_for_function("pinned === 2")
    assert page.text_content("#panelBack") == "‹ #3 Build feature" and "task=2" in page.url
    page.click("h3:text('Blocked by') + ul li")
    page.wait_for_function("pinned === 3")
    assert page.evaluate("trail") == [3, 2]
    page.keyboard.press("Alt+ArrowLeft")
    page.wait_for_function("pinned === 2")
    page.click("#panelBack")
    page.wait_for_function("pinned === 3")
    assert page.query_selector("#panelBack") is None
    page.keyboard.press("Escape")
    assert not page.evaluate(PANEL_OPEN) and "task=" not in page.url
    page.goto(f"{page_file.as_uri()}?types=task,milestone&task=5")
    page.wait_for_function("typeof cy !== 'undefined' && pinned === 5")
    assert page.evaluate("types.has('external')") and "Vendor key" in page.inner_text("#panel")
    assert problems == []
    context.close()


def test_panel_meta_links_notes_and_width(browser, page_file):
    page, problems = open_page(browser, page_file)
    notes = "\n".join(f"line {i}" for i in range(20)) + "\nsee https://wiki.example/runbook for steps"
    page.evaluate(f"""applyData({{ ...DATA, nodes: DATA.nodes.map(n => n.id !== 5 ? n : {{ ...n, notes: {notes!r}, chase_due: true,
        meta: {{ ...n.meta, contact: 'Jo <jo@acme.example>', chase: '2026-10-10', promised: '2026-11-10', tags: ['legal', 'q4'], link: 'https://jira.example/browse/PLAT-1', priority: 'high' }},
        conflicts: [...n.conflicts, {{ kind: 'promised', from: 5, to: null, with: null, due: '2026-11-10', need: '2026-11-05', gap: 5, message: '#5 promised 2026-11-10 after needed 2026-11-05' }}] }}) }})""")
    page.evaluate("select(5, false)")
    assert page.evaluate("document.querySelectorAll('#facts .tag').length") == 2
    assert page.get_attribute("#facts a[href^='https://jira']", "target") == "_blank"
    assert page.get_attribute("#facts a[href^='mailto:']", "href") == "mailto:jo@acme.example"
    assert page.text_content("#facts .overdue") == " · overdue"
    self_row = "#panel li.self"
    assert page.text_content(self_row) == "Promised 10 Nov is after needed 5 Nov (5d)"
    assert page.evaluate(f"getComputedStyle(document.querySelector('{self_row}')).opacity") == "1"
    assert page.evaluate("document.querySelector('#panel .notes').classList.contains('clamp')") and page.is_visible("#notesMore")
    assert page.get_attribute("#panel .notes a", "href") == "https://wiki.example/runbook"
    page.click("#notesMore")
    assert page.text_content("#notesMore") == "Show less"
    page.evaluate("applyData({ ...DATA })")
    assert not page.evaluate("document.querySelector('#panel .notes').classList.contains('clamp')")
    assert "Priority" in page.text_content("#details") and "priority" not in page.text_content("#facts")
    box = page.evaluate("document.getElementById('panelGrip').getBoundingClientRect().toJSON()")
    x, y = box["x"] + 4, box["y"] + 200
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 100, y, steps=5)
    page.mouse.up()
    assert page.evaluate("panelW") == 440 and page.evaluate("localStorage.getItem('taskgraph.panelW')") == "440"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--panel-w').trim()") == "440px"
    page.mouse.move(x - 100, y)
    page.mouse.down()
    page.mouse.move(x - 600, y, steps=5)
    page.mouse.up()
    assert page.evaluate("panelW") == 520
    assert problems == []
    page.close()


def test_filter_opens_summaries_that_hide_matches(browser, programme_file):
    page, problems = open_page(browser, programme_file)
    more(page, "collapseAll")
    assert not page.evaluate("expandedIds().has(3)")
    page.click("#filterBtn")
    page.click("#filters [data-facet=owner] .link:text('None')")
    page.click('#filters [data-facet=owner][data-value="priya"]')
    assert page.evaluate("expandedIds().has(3)") and page.evaluate("tasks().map(n => n.id()).sort()") == ["1", "3", "4", "7"]
    page.click("#clearAll")
    assert not page.evaluate("expandedIds().has(3)")
    page.goto(f"{programme_file.as_uri()}?flag=late")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("tasks().map(n => n.id()).sort()") == ["1", "3", "4"]
    assert problems == []
    page.close()


def test_graph_layout_is_remembered(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=graph")
    pos = "() => Object.fromEntries(tasks().map(n => [n.id(), [Math.round(n.position('x')), Math.round(n.position('y'))]]))"
    first = page.evaluate(pos)
    page.evaluate("flags.add('atrisk'); filtersChanged()")
    assert page.evaluate("tasks().map(n => n.id()).sort()") == ["1", "2"]
    page.evaluate("flags.clear(); filtersChanged()")
    assert page.evaluate(pos) == first and page.evaluate("layoutMemo.size") == 2
    page.evaluate("void cy.getElementById('3').position({ x: 9999, y: 9999 })")
    more(page, "relayout")
    assert page.evaluate(pos) == first
    assert problems == []
    page.close()


def test_hidden_tasks_matches_node_by_node(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=lanes")
    slow = """() => {
        const box = document.getElementById('cy').getBoundingClientRect(), l = document.getElementById('legend').getBoundingClientRect();
        const lg = { x1: l.left - box.left, x2: l.right - box.left, y1: l.top - box.top, y2: l.bottom - box.top };
        return tasks().some(n => { const b = n.renderedBoundingBox();
            return b.x1 < 0 || b.y1 < 0 || b.x2 > box.width || b.y2 > box.height || (b.x1 < lg.x2 && b.x2 > lg.x1 && b.y1 < lg.y2 && b.y2 > lg.y1); });
    }"""
    for pan in ({"x": 0, "y": 0}, {"x": -300, "y": 0}, {"x": 0, "y": 600}, {"x": 40, "y": 520}):
        page.evaluate(f"void cy.panBy({pan})")
        assert page.evaluate("hiddenTasks()") == page.evaluate(slow), pan
    page.click("#legendToggle")
    page.evaluate("fitView(true); void cy.panBy({ x: 0, y: 120 })")
    assert page.evaluate("hiddenTasks()") == page.evaluate(slow)
    assert problems == []
    page.close()


def test_print_sheet(browser, page_file, tmp_path):
    page, problems = open_page(browser, page_file, "?view=timeline&task=3&owner=ann")
    page.wait_for_function("pinned === 3")
    page.evaluate("printSheet()")
    parts = page.evaluate("Array.from(document.getElementById('print').children, c => c.tagName + '.' + c.className)")
    assert parts == ["H1.", "P.sub", "IMG.plan", "DIV.key", "DIV.item"]
    assert page.text_content("#print h1") == "taskgraph · demo · Timeline"
    assert page.text_content("#print .sub") == "As of 13 Oct 2026 · done items hidden · Owner: ann"
    assert page.evaluate("document.querySelector('#print .plan').src").startswith("data:image/png;base64,")
    item = page.text_content("#print .item")
    assert "Build feature" in item and "Copy link" not in item and page.evaluate("document.querySelectorAll('#print [id]').length") == 0
    page.emulate_media(media="print")
    assert page.is_hidden("#toolbar") and page.is_hidden("#cy") and page.is_visible("#print .plan") and page.is_visible("#print .item tr")
    page.emulate_media(media="screen")
    page.evaluate("dispatchEvent(new Event('afterprint'))")
    assert page.evaluate("document.getElementById('print').children.length") == 0
    page.pdf(path=str(tmp_path / "plan.pdf"), landscape=True)
    assert (tmp_path / "plan.pdf").read_bytes()[:5] == b"%PDF-"
    assert problems == []
    page.close()


ROUTES = """() => cy.edges('.tl-dep').map(e => {
    const s = e.source(), t = e.target(), left = t.position('x') - t.width() / 2, te = e.targetEndpoint();
    const pts = [e.sourceEndpoint(), ...(e.segmentPoints() || []), te];
    const lo = Math.min(s.position('y'), t.position('y')) - TL.row, hi = Math.max(s.position('y'), t.position('y')) + TL.row;
    return { id: e.id(), entersLeft: Math.abs(te.x - left) < 1 && Math.abs(te.y - t.position('y')) < 1,
             staysRight: pts.every(p => p.x >= TL.names + 8), staysNear: pts.every(p => p.y >= lo && p.y <= hi),
             lastLeg: Math.abs(pts[pts.length - 2].y - te.y) < 1 };
})"""


@pytest.mark.parametrize("fixture", ["page_file", "programme_file"])
def test_timeline_lines_enter_the_left_end(browser, request, fixture):
    page, problems = open_page(browser, request.getfixturevalue(fixture), "?view=timeline&deps=1")
    more(page, "expandAll")
    routes = page.evaluate(ROUTES)
    assert routes and all(r["entersLeft"] and r["staysRight"] and r["staysNear"] and r["lastLeg"] for r in routes), routes
    view_option(page, "depsMode", "off")
    conflict = page.evaluate(ROUTES)
    assert conflict and all(r["entersLeft"] for r in conflict)
    assert problems == []
    page.close()


@pytest.fixture(scope="module")
def load_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("load")
    db = tmp / "t.db"
    tg = runner(db)
    tg("add", "Workstream", "--meta", "owner=ann", "estimate=999", "lane=dev", "team=core")
    tg("add", "Build", "--parent", "1", "--start", "2026-10-19", "--due", "2026-10-30", "--meta", "owner=ann", "estimate=40")
    tg("add", "Fix", "--due", "2026-10-16", "--meta", "owner=ann", "estimate=12h", "lane=ops")
    tg("add", "Overdue", "--due", "2026-10-09", "--meta", "owner=bo", "estimate=10", "lane=ops")
    tg("add", "Someday", "--meta", "owner=bo", "estimate=5")
    tg("add", "Unsized", "--due", "2026-10-20", "--meta", "owner=ann")
    tg("add", "Next year", "--start", "2027-01-04", "--due", "2027-01-08", "--meta", "owner=ann", "estimate=15")
    tg("add", "Weekend", "--start", "2026-10-24", "--meta", "owner=cy", "estimate=6", "lane=ops")
    tg("add", "Decide", "--type", "decision", "--due", "2026-10-22", "--meta", "decider=ann", "estimate=3")
    tg("add", "Ship", "--type", "milestone", "--due", "2026-10-30", "--depends", "2")
    out = tmp / "graph.html"
    tg("graph", "--no-open", "--out", str(out))
    return out, db


def cli_load(db, *args):
    env = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13"}
    import json
    p = subprocess.run([sys.executable, str(SCRIPT), "--db", str(db), "--project", "demo", "--json", "load", "--weeks", "12", *args], check=True, capture_output=True, text=True, env=env)
    return json.loads(p.stdout)


PAGE_LOAD = """() => { const d = computeLoad(); return {
    weeks: d.weeks.map((w, i) => ({ start: isoOf(w), capacity: d.capacity[i] })),
    groups: d.rows.map(g => ({ name: g.name, hours: g.hours.map(round1), later: round1(g.later), unscheduled: round1(g.unscheduled), over: g.over.flatMap((o, i) => o ? [i] : []) })),
    unestimated: d.unestimated.map(n => n.id).sort((a, b) => a - b) }; }"""


@pytest.mark.parametrize("by,hours", [("owner", 30), ("lane", 15), ("team", 8)])
def test_load_view_matches_the_cli(browser, load_file, by, hours):
    path, db = load_file
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{path.as_uri()}?view=load&loadby={by}&hours={hours}")
    page.wait_for_function("typeof cy !== 'undefined' && document.querySelector('#loadView table.load')")
    cli = cli_load(db, "--by", by, "--week-hours", str(hours))
    mine = page.evaluate(PAGE_LOAD)
    assert mine["weeks"] == cli["weeks"]
    assert mine["unestimated"] == cli["unestimated"]
    assert mine["groups"] == [{k: g[k] for k in ("name", "hours", "later", "unscheduled", "over")} for g in cli["groups"]]
    assert problems == []
    page.close()


def test_load_view_cells_filters_and_print(browser, load_file):
    path, db = load_file
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    problems = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.goto(f"{path.as_uri()}?view=lanes")
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    page.click("#viewLoad")
    assert "view=load" in page.url and page.is_hidden("#cy") and page.is_visible("#loadView") and page.is_hidden("#legend")
    rows = page.evaluate("Array.from(document.querySelectorAll('#loadView tbody th.name'), t => t.textContent)")
    assert rows == ["ann", "bo", "cy"]
    assert "null" not in page.text_content("#loadView")  # a block with nothing to say is left out
    first = page.evaluate("Array.from(document.querySelectorAll('#loadView tbody tr:first-child td.c'), t => t.textContent).slice(0, 3)")
    assert first == ["12", "23", "20"]
    page.click('#loadView td.c[data-group="ann"][data-week="2026-10-19"]')
    assert page.text_content("#loadView .loadPick h3") == "ann · week of 19 Oct · 23h of 30h"
    assert page.evaluate("Array.from(document.querySelectorAll('#loadView .loadPick li span'), s => s.textContent)") == ["#2 Build", "#9 Decide"]
    page.click("#loadView .loadPick li >> nth=0")
    assert page.evaluate("pinned") == 2 and page.evaluate(PANEL_OPEN) and "task=2" in page.url
    page.keyboard.press("Escape")
    page.click("#optsBtn")
    page.fill("#weekHours", "10")
    page.press("#weekHours", "Enter")
    assert "hours=10" in page.url and page.evaluate("weekHours") == 10
    assert page.text_content('#loadView td.c[data-group="ann"][data-week="2026-10-19"]') == "23!"
    page.check('input[name="loadKey"][value="lane"]')
    page.keyboard.press("Escape")
    assert "loadby=lane" in page.url
    assert page.evaluate("Array.from(document.querySelectorAll('#loadView tbody th.name'), t => t.textContent)") == ["dev", "ops", "Unassigned"]
    tick(page, "#filters [data-facet=owner] .link:text('None')")
    page.click('#filters [data-facet=owner][data-value="bo"]')
    page.keyboard.press("Escape")
    assert page.evaluate("Array.from(document.querySelectorAll('#loadView tbody th.name'), t => t.textContent)") == ["ops", "Unassigned"]
    assert page.is_disabled("#exportPng")
    page.evaluate("printSheet()")
    assert page.evaluate("Array.from(document.getElementById('print').children, c => c.className)")[:3] == ["", "sub", "loadPrint"]
    assert page.evaluate("document.querySelectorAll('#print table.load tbody tr').length") == 2
    page.go_back()
    page.wait_for_function("loadKey === 'owner'")
    assert page.evaluate("view") == "load"
    page.go_back()
    page.wait_for_function("view === 'lanes'")
    assert page.is_visible("#cy") and page.is_hidden("#loadView") and page.evaluate("tasks().length") > 0
    assert problems == []
    page.close()


def test_keyboard_reaches_and_opens_items(browser, programme_file):
    page, problems = open_page(browser, programme_file)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.id") == "skip" and page.is_visible("#skip")
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "cy"
    page.wait_for_timeout(100)
    assert "items. Arrow keys move between items." in page.text_content("#announce")
    page.keyboard.press("Home")
    first = page.evaluate("kbdId")
    assert page.evaluate("cy.nodes('.kbd').map(n => Number(n.id()))") == [first]
    page.wait_for_timeout(100)
    assert page.text_content("#announce").startswith(f"#{first} ") and page.text_content("#announce").endswith("Enter for details.")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("kbdId") != first
    page.keyboard.press("Enter")
    assert page.evaluate(PANEL_OPEN) and page.evaluate("pinned") == page.evaluate("kbdId")
    assert page.evaluate("document.activeElement.id") == "panelTitle"
    page.keyboard.press("Escape")
    assert not page.evaluate(PANEL_OPEN) and page.evaluate("document.activeElement.id") == "cy"
    page.evaluate("setKbd(cy.getElementById('3'))")
    expanded = page.evaluate("expandedIds().has(3)")
    page.keyboard.press(" ")
    assert page.evaluate("expandedIds().has(3)") != expanded and page.evaluate("kbdId") == 3
    page.click("#cy", position={"x": 5, "y": 5})
    page.keyboard.press("Tab")
    assert page.evaluate("cy.nodes('.kbd').length") == 0
    assert problems == []
    page.close()


def test_timeline_arrows_step_by_row(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    page.focus("#cy")
    order = page.evaluate("tasks().toArray().sort((a, b) => a.position('y') - b.position('y')).map(n => Number(n.id()))")
    page.keyboard.press("Home")
    seen = [page.evaluate("kbdId")]
    for _ in order[1:]:
        page.keyboard.press("ArrowDown")
        seen.append(page.evaluate("kbdId"))
    assert seen == order
    page.keyboard.press("ArrowUp")
    assert page.evaluate("kbdId") == order[-2]
    assert problems == []
    page.close()


def test_panel_rows_are_buttons_and_focus_follows(browser, page_file):
    page, problems = open_page(browser, page_file)
    page.evaluate("select(3, false)")
    row = "h3:text('Blocks') + ul li > .row"
    assert page.get_attribute(row, "role") == "button" and page.get_attribute(row, "tabindex") == "0"
    assert page.get_attribute(row, "aria-label") == "#2 Ship v1, Blocked"
    assert page.evaluate("document.querySelector(\"h3 + ul > li\").getAttribute('role')") is None
    page.focus(row)
    page.keyboard.press("Enter")
    assert page.evaluate("pinned") == 2 and page.evaluate("document.activeElement.id") == "panelTitle"
    page.focus("#panelGrip")
    page.keyboard.press("ArrowLeft")
    assert page.evaluate("panelW") == 360 and page.get_attribute("#panelGrip", "aria-valuenow") == "360"
    page.focus("h3:text('Blocked by') + ul li > .row")
    page.evaluate("applyData({ ...DATA })")
    assert page.evaluate("document.activeElement.dataset.ref") == "3"
    assert problems == []
    page.close()


def test_names_states_and_marks(browser, page_file):
    page, problems = open_page(browser, page_file)
    for sel, name in (("#project", "Project"), ("#search", "Search the plan"), ("#optsBtn", "View options")):
        assert page.get_attribute(sel, "aria-label") == name
    assert page.evaluate("['viewGraph', 'viewLanes', 'viewTimeline', 'viewLoad'].map(b => document.getElementById(b).getAttribute('aria-pressed'))") == ["true", "false", "false", "false"]
    assert page.evaluate("document.querySelector('main').contains(document.getElementById('cy'))") and page.evaluate("document.querySelector('header h1').textContent") == "taskgraph · demo"
    assert page.evaluate("cy.getElementById('2').data('label')").startswith("⊘ #2 Ship v1") and page.evaluate("cy.getElementById('4').data('label')").startswith("#4 ")
    page.click("#goal")
    page.keyboard.press("ArrowDown")
    active = page.get_attribute("#goal", "aria-activedescendant")
    assert active and page.get_attribute(f"#{active}", "aria-selected") == "true"
    page.keyboard.press("Escape")
    page.click("#filterBtn")
    page.focus("#type-task")
    page.keyboard.press("Escape")
    assert page.is_hidden("#filters") and page.evaluate("document.activeElement.id") == "filterBtn"
    page.click("#optsBtn")
    assert page.is_disabled('input[name="depsMode"][value="all"]') and page.is_disabled('input[name="laneKey"][value="owner"]')
    assert page.evaluate("getComputedStyle(document.querySelector('#depsBy .h')).color") == page.evaluate("getComputedStyle(document.getElementById('stamp')).color")
    page.keyboard.press("Escape")
    tick(page, "#type-task")
    page.wait_for_timeout(120)
    assert page.text_content("#announce").endswith("items shown") and page.get_attribute("#chips", "role") == "list"
    assert problems == []
    page.close()


def test_load_cells_work_from_the_keyboard(browser, load_file):
    path, db = load_file
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"{path.as_uri()}?view=load")
    page.wait_for_selector("#loadView table.load")
    cell = '#loadView td.c[data-group="ann"][data-week="2026-10-19"]'
    assert page.get_attribute(cell, "role") == "button" and page.get_attribute(cell, "aria-label").startswith("ann, week of 19 Oct: 23h of 30h")
    assert page.evaluate("document.querySelectorAll('#loadView th[scope=row]').length") == 3
    page.focus(cell)
    page.keyboard.press("Enter")
    assert page.is_visible("#loadView .loadPick") and page.evaluate("document.activeElement.dataset.week") == "2026-10-19"
    page.focus("#loadView .loadPick li > .row")
    page.keyboard.press(" ")
    assert page.evaluate("pinned") == 2 and page.evaluate("document.activeElement.id") == "panelTitle"
    page.close()


def test_reduced_motion(browser, page_file):
    context = browser.new_context(reduced_motion="reduce")
    page = context.new_page()
    page.goto(page_file.as_uri())
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("MOTION") == 0
    context.close()


MD_NOTE = """## Plan
Run **pilot** with [runbook](https://wiki.example/x) and `kubectl`.
Next line.

1. Freeze
2. Copy
   - count rows
3. Switch

- [x] Comms
- [ ] Rollback

> Decide at SteerCo.

| Wave | Tenants |
|------|--------:|
| 1 | 12 |

```
select 1;
```
<script>alert(1)</script> <img src=x onerror=alert(2)> [bad](javascript:alert(3)) snake_case_name and 2 * 3 * 4."""


def test_notes_render_as_safe_markdown(browser, page_file):
    page, problems = open_page(browser, page_file)
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.evaluate(f"applyData({{ ...DATA, nodes: DATA.nodes.map(n => n.id === 3 ? {{ ...n, notes: {MD_NOTE!r} }} : n) }})")
    page.evaluate("select(3, false)")
    notes = "#panel .notes"
    assert page.evaluate(f"Array.from(document.querySelector('{notes}').children, c => c.tagName)") == ["H5", "P", "OL", "UL", "BLOCKQUOTE", "TABLE", "PRE", "P"]
    assert page.text_content(f"{notes} strong") == "pilot" and page.text_content(f"{notes} p code") == "kubectl"
    assert page.evaluate(f"document.querySelector('{notes} p').innerHTML.includes('<br>')")
    assert page.evaluate(f"Array.from(document.querySelectorAll('{notes} a'), a => a.getAttribute('href'))") == ["https://wiki.example/x"]
    assert page.evaluate(f"document.querySelectorAll('{notes} ol > li > ul > li').length") == 1
    assert page.evaluate(f"Array.from(document.querySelectorAll('{notes} li.task input'), i => [i.checked, i.disabled])") == [[True, True], [False, True]]
    assert page.evaluate(f"document.querySelector('{notes} td:last-child').style.textAlign") == "right"
    assert page.text_content(f"{notes} pre code") == "select 1;"
    last = page.text_content(f"{notes} > p:last-child")
    assert "<script>alert(1)</script>" in last and "snake_case_name" in last and "2 * 3 * 4" in last
    assert page.evaluate(f"document.querySelectorAll('{notes} script, {notes} img, {notes} em').length") == 0
    assert dialogs == [] and problems == []
    page.close()
