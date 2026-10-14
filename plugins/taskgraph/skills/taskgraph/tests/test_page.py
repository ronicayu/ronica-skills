import os
import subprocess
import sys
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
    assert page.evaluate("cy.getElementById('tl:today').data('name')") == "Today 10/13"
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
    assert short < tall / 2 and page.inner_text("#legendToggle") == "Legend ▸"
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
    assert "red" in rag and len(rag) == page.evaluate("cy.nodes('.lane-bg').length")
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
    rows = page.evaluate(f"{BY_Y}('.tl-name', 'name')")
    infra = rows.index("Infra")
    assert rows[infra + 1] == "▾ #3 Build landing zone" and rows[infra + 2] == "#4 Write modules"
    assert not any("#3 Build landing zone" in r for r in rows[rows.index("Objectives"):rows.index("Data")])
    assert page.evaluate("cy.nodes('.tl-name[of=\"4\"]').data('tx') === 14 + 14 - TL.names")
    assert problems == []
    page.close()
