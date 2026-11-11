import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"
SVG = "{http://www.w3.org/2000/svg}"
TITLES = {"Launch", "Ship v1", "Build feature", "Write docs", "Vendor key", "Undated chore"}
DATED = TITLES - {"Undated chore"}


def tg(db, *args, env=None, check=True):
    full = {**os.environ, "TASKGRAPH_TODAY": "2026-10-13", **(env or {})}
    return subprocess.run([sys.executable, str(SCRIPT), "--db", str(db), "--project", "demo", *args], capture_output=True, text=True, env=full, check=check)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("svg") / "t.db"
    tg(path, "add", "Launch", "--type", "objective", "--meta", "owner=ann")
    tg(path, "add", "Ship v1", "--type", "milestone", "--parent", "1", "--due", "2026-12-01", "--meta", "lane=dev")
    tg(path, "add", "Build feature", "--parent", "1", "--start", "2026-10-20", "--due", "2026-11-20", "--meta", "owner=ann", "lane=dev")
    tg(path, "add", "Write docs", "--parent", "1", "--start", "2026-10-14", "--due", "2026-10-30", "--meta", "owner=bo", "lane=docs")
    tg(path, "add", "Vendor key", "--type", "external", "--due", "2026-11-05", "--meta", "party=Acme", "lane=dev")
    tg(path, "add", "Undated chore", "--meta", "lane=docs")
    tg(path, "dep", "add", "2", "3")
    tg(path, "dep", "add", "3", "5")
    return path


def parse(path):
    root = ET.parse(path).getroot()
    assert root.tag == SVG + "svg"
    return root


def texts(root):
    return {t.text for t in root.iter(SVG + "text")}


def has_title(root, title):
    return any(title in (t or "") for t in texts(root))


def have_engine():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"chromium unavailable: {e}")


@pytest.mark.parametrize("view", ("graph", "lanes", "timeline"))
def test_cli_exports_each_view_as_svg_with_titles_and_edges(db, tmp_path, view):
    have_engine()
    out = tmp_path / f"{view}.svg"
    tg(db, "export", "--svg", str(out), "--view", view, "--state", "?deps=all&theme=dark")
    root = parse(out)
    expected = TITLES if view != "timeline" else DATED
    assert all(has_title(root, t) for t in expected)
    assert len(root.findall(f".//{SVG}path[@class]")) >= 2
    assert all(p.get("d", "").startswith("M") for p in root.iter(SVG + "path"))
    assert root.find(f"{SVG}rect").get("fill") != "#0d1117"  # paper colours, whatever the page theme


def test_cli_goal_narrows_the_view(db, tmp_path):
    have_engine()
    out = tmp_path / "goal.svg"
    tg(db, "export", "--svg", str(out), "--goal", "5")
    root = parse(out)
    assert has_title(root, "Vendor key") and not has_title(root, "Write docs")


def test_cli_load_view_has_no_svg(db, tmp_path):
    out = tmp_path / "load.svg"
    run = tg(db, "export", "--svg", str(out), "--view", "load", check=False)
    assert run.returncode != 0 and "Load view has no SVG" in run.stderr + run.stdout
    assert not out.exists()
    run = tg(db, "export", "--svg", str(out), "--state", "https://x.test/?view=load", check=False)
    assert run.returncode != 0 and not out.exists()


def test_page_button_saves_the_same_svg(db, tmp_path):
    have_engine()
    from playwright.sync_api import sync_playwright

    page_file = tmp_path / "graph.html"
    tg(db, "graph", "--no-open", "--out", str(page_file))
    cli = tmp_path / "cli.svg"
    tg(db, "export", "--svg", str(cli), "--view", "lanes")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(f"{page_file.as_uri()}?view=lanes")
        page.wait_for_function("typeof cy !== 'undefined' && cy.nodes().length > 0")
        page.click("#moreBtn")
        with page.expect_download() as download:
            page.click("#exportSvg")
        saved = tmp_path / "page.svg"
        download.value.save_as(saved)
        assert download.value.suggested_filename.endswith(".svg")
        page.click("#viewLoad")
        assert page.is_disabled("#exportSvg")
        browser.close()
    assert saved.read_text() == cli.read_text().rstrip("\n")


def test_chrome_fallback_without_playwright(db, tmp_path):
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import tg as tgmod
    finally:
        sys.path.pop(0)
    if not tgmod.find_chrome():
        pytest.skip("no Chrome, Chromium or Edge binary found")
    out = tmp_path / "chrome.svg"
    tg(db, "export", "--svg", str(out), env={"TG_SVG_ENGINE": "chrome"})
    root = parse(out)
    assert all(has_title(root, t) for t in TITLES)
    assert len(root.findall(f".//{SVG}path[@class]")) >= 2


def test_error_names_both_engines_when_none_is_available(db, tmp_path):
    run = tg(db, "export", "--svg", str(tmp_path / "x.svg"), env={"TG_SVG_ENGINE": "chrome", "CHROME": str(tmp_path / "missing")}, check=False)
    message = run.stderr + run.stdout
    assert run.returncode != 0 and "Playwright" in message and "Chrome" in message
