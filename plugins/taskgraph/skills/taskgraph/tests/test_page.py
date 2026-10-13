import os
import subprocess
import sys
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"
VIEWS = ("graph", "lanes", "timeline")


@pytest.fixture(scope="module")
def page_file(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("page")
    db = tmp / "t.db"
    env = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13"}

    def tg(*args):
        subprocess.run([sys.executable, str(SCRIPT), "--db", str(db), "--project", "demo", *args], check=True, capture_output=True, env=env)

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
    page.close()
