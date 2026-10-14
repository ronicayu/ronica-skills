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
    tall = page.evaluate("document.getElementById('legend').getBoundingClientRect().height")
    page.click("#legendToggle")
    short = page.evaluate("document.getElementById('legend').getBoundingClientRect().height")
    assert tall - short >= 20 and tall <= 64 and page.inner_text("#legendToggle") == "Legend ▸"
    page.reload()
    page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
    assert page.evaluate("document.getElementById('legend').classList.contains('closed')")
    page.click("#legendToggle")
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
    page.select_option("#depsMode", "critical")
    assert page.evaluate(drawn) == ["3-2", "5-3"]
    assert page.evaluate("cy.edges('.tl-critical').map(e => e.id()).sort()") == ["3-2", "5-3"]
    assert "deps=critical" in page.url
    page.select_option("#depsMode", "all")
    assert "deps=1" in page.url and len(page.evaluate(drawn)) >= 2
    assert page.evaluate(f"{BY_Y}('.tl-name[of]', 'name')") == ["▾ #1 Launch", "#2 Ship v1", "#3 Build feature", "#5 Vendor key", "#4 Write docs", "#6 Undated chore"]
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
    assert page.input_value("#goal") == "2"
    assert page.inner_text("#goalInfo") == "0/2 done · at risk"
    assert page.evaluate("document.title") == "taskgraph · #2 Ship v1"
    assert problems == []
    page.close()


def test_goal_focus_from_picker_and_panel(browser, page_file):
    page, problems = open_page(browser, page_file)
    everything = page.evaluate(SHOWN)
    assert "4" in everything and "6" in everything and page.is_hidden("#goalInfo")
    options = page.evaluate("Array.from(document.querySelectorAll('#goal option'), o => o.value)")
    assert options == ["", "2", "1"]
    page.select_option("#goal", "2")
    assert page.evaluate(SHOWN) == ["1", "2", "3", "5"] and "goal=2" in page.url
    page.select_option("#goal", "")
    assert page.evaluate(SHOWN) == everything and "goal=" not in page.url
    page.evaluate("select(3, false)")
    page.click("#focusGoal")
    assert page.evaluate(SHOWN) == ["1", "3", "5"] and "goal=3" in page.url
    assert page.input_value("#goal") == "3" and page.inner_text("#focusGoal") == "Show everything"
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
        page.click("#expandAll")
        assert heads(page, view) == ["Objectives", "Data", "Infra", "Programme", "Security"]
        assert page.evaluate(RAGS) == ["red", "amber", "red", "red", "amber"]
        assert problems == []
        page.close()


def test_timeline_nests_only_within_lane(browser, programme_file):
    page, problems = open_page(browser, programme_file, "?view=timeline")
    page.click("#expandAll")
    rows = page.evaluate(f"{BY_Y}('.tl-name', 'name').map(s => s.replace(/ · (RED|AMBER|GREEN)$/, ''))")
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


@pytest.mark.parametrize("view", VIEWS)
def test_readability_floor(browser, tall_file, view):
    page, problems = open_page(browser, tall_file, f"?view={view}")
    for action in (None, "#fit", "#expandAll"):
        if action:
            page.click(action)
        assert abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6, action
        assert page.evaluate(ANCHOR), action
        assert page.evaluate(COVERED) is False
    assert problems == []
    page.close()


INSIDE = """() => {
    const box = document.getElementById('cy').getBoundingClientRect();
    return tasks().every(n => { const b = n.renderedBoundingBox(); return b.x1 >= 0 && b.y1 >= 0 && b.x2 <= box.width && b.y2 <= box.height; });
}"""


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
        page.click("#expandAll")
        bar = page.evaluate(TOOLBAR)
        assert bar["scrollLeft"] == 0 and bar["project"] >= 0
        page.close()


def test_search_reveals_collapsed_and_counts(browser, page_file):
    page, problems = open_page(browser, page_file)
    page.click("#collapseAll")
    page.fill("#search", "docs")
    page.wait_for_timeout(300)
    assert page.evaluate("tasks().filter(n => !n.hasClass('dim')).map(n => n.id())") == ["4"]
    assert page.inner_text("#searchCount") == "1 match"
    assert page.evaluate("expandedIds().has(1)")
    page.fill("#search", "zzz")
    page.wait_for_timeout(300)
    assert page.inner_text("#searchCount") == "No matches"
    page.fill("#search", "e")
    page.wait_for_timeout(300)
    hits = page.evaluate("searchHits('e').map(n => n.id)")
    assert hits == [3, 4, 5, 6] and page.inner_text("#searchCount") == "4 matches"
    page.press("#search", "Enter")
    assert page.evaluate("document.getElementById('panel').style.display") == "block"
    assert page.evaluate("pinned") == hits[0]
    page.press("#search", "Enter")
    assert page.evaluate("pinned") == hits[1]
    page.press("#search", "Shift+Enter")
    assert page.evaluate("pinned") == hits[0]
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
    page.select_option("#goal", "2")
    for t in ("task", "milestone", "decision", "external", "objective", "issue"):
        page.click(f"#type-{t}")
    assert page.evaluate("tasks().length") == 0
    assert page.inner_text("#emptyText") == "Nothing matches the current filters."
    page.click("#emptyAction")
    assert page.evaluate("Array.from(document.querySelectorAll('#types button')).every(b => b.classList.contains('on'))")
    assert page.input_value("#goal") == "" and "goal=" not in page.url
    assert page.evaluate("tasks().length") > 0 and page.is_hidden("#empty")
    assert problems == []
    page.close()


def test_date_format(browser, page_file):
    page, problems = open_page(browser, page_file, "?view=timeline")
    assert page.evaluate("day('2026-10-30')") == "30 Oct"
    assert page.evaluate("day('2027-03-15')") == "15 Mar 2027"
    assert page.evaluate("cy.getElementById('3').data('label')") == "20 Oct–25 Nov · conflict"
    assert page.evaluate("document.querySelector('#goal option[value=\"2\"]').textContent") == "#2 Ship v1 · 1 Dec"
    page.evaluate("select(3, false)")
    text = page.inner_text("#panel")
    assert "Baseline due" in text and "20 Nov (+5d) · plan" in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert re.search(r"Created\s+\d{1,2} Oct \d{2}:\d{2}", text)
    assert re.fullmatch(r"Generated \d{1,2} \w{3}( \d{4})? \d{2}:\d{2}", page.inner_text("#stamp"))
    assert problems == []
    page.close()


def test_status_words_and_rag_headers(browser, programme_file):
    page, problems = open_page(browser, programme_file, "?view=timeline")
    assert page.evaluate("cy.getElementById('2').data('label')") == "15 Dec · at risk"
    page.click("#expandAll")
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


CONTRAST = [  # foreground, background, is text
    ("#9ca3af", "#181c22", True),   # stamp, panel "None", search count
    ("#9ca3af", "#232830", True),   # search placeholder
    ("#6b7280", "#111418", False),  # dependency and part-of edges
    ("#6b7280", "#14181e", False),  # AXIS: Timeline bars and grid
    ("#d1d5db", "#2f3744", True),   # blocked label on blocked fill
    ("#6b7280", "#111418", False),  # blocked border on canvas
    ("#ffffff", "#2563eb", True),   # done label on done fill
    ("#2563eb", "#111418", False),  # done fill on canvas
]


def test_contrast_tokens(browser, page_file):
    for fg, bg, text in CONTRAST:
        assert contrast(fg, bg) >= (4.5 if text else 3.0), (fg, bg, contrast(fg, bg))
    page, problems = open_page(browser, page_file)
    assert page.evaluate("getComputedStyle(document.getElementById('stamp')).color") == "rgb(156, 163, 175)"
    assert page.evaluate("cy.getElementById('2').data('derived_status')") == "blocked"
    assert page.evaluate("cy.getElementById('2').style('background-color')") == "rgb(47,55,68)"
    assert page.evaluate("cy.edges()[0].style('line-color')") == "rgb(107,114,128)"
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


LEGEND_SHOWN = "Array.from(document.querySelectorAll('#legendBody .col > div'), d => [d.textContent.trim(), !d.hidden])"


def legend_shown(page):
    return dict(page.evaluate(LEGEND_SHOWN))


def test_legend_defaults_and_rows(browser, page_file, raid_file):
    for width, closed in ((1280, True), (1440, False)):
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
    page.click("#hideDone")
    assert legend_shown(page)["Done"] is True
    page.close()
    page, problems = open_page(browser, page_file, "?view=lanes")
    assert legend_shown(page)["Lane RAG"] is True
    assert problems == []
    page.close()
    for view in VIEWS:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{page_file.as_uri()}?view={view}")
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        assert page.evaluate("document.getElementById('legend').getBoundingClientRect().height") <= 64
        page.click("#legendToggle")
        assert page.evaluate("document.getElementById('legend').getBoundingClientRect().height") <= 28
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
    page.click("#collapseAll")
    assert page.evaluate(INSIDE)
    assert abs(page.evaluate("cy.zoom() - fitTarget().zoom")) < 1e-6
    page.close()
    page, problems = open_page(browser, tall_file)
    page.click("#expandAll")
    assert abs(page.evaluate("cy.zoom()") - 0.9) < 1e-6
    page.click("#collapseAll")
    assert abs(page.evaluate("cy.zoom() - Math.max(READABLE, fitTarget().zoom)")) < 1e-6
    assert problems == []
    page.close()
