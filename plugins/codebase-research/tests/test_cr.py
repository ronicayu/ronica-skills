"""Tests for the codebase-research index (scripts/cr.py and its package).

Run: python3 -m unittest discover -s plugins/codebase-research/tests -v
The tree-sitter tests run only when tree-sitter is importable; `cr deps`
installs it into a private virtual environment.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
CR = os.path.join(SCRIPTS, "cr.py")
sys.path.insert(0, SCRIPTS)

from codebase_research import chunk, discover, facts, tokens  # noqa: E402

FILES = {
    "src/main/java/com/acme/clearance/DeclarationService.java": '''package com.acme.clearance;

/**
 * Handles customs declarations.
 */
public class DeclarationService {

    private static final String FIND_SQL = "SELECT id, status FROM DECLARATION WHERE id = ?";

    @Value("${clearance.retry.max}")
    private int maxRetries;

    /** Loads a declaration by its id. */
    public Declaration getDeclarationById(Long declarationId) {
        return jdbc.queryForObject(FIND_SQL, declarationId);
    }

    public void rejectDeclaration(Long id, String reason) {
        jdbc.update("UPDATE DECLARATION SET status = 'REJECTED', reason = ? WHERE id = ?", reason, id);
        jdbc.update("INSERT INTO AUDIT_LOG (entity, action) VALUES ('DECLARATION', 'REJECT')");
        notifier.send("Update failed for the officer");
    }

    // does not compile: missing semicolon
    public int countPending() {
        int n = jdbc.count("select count(*) from declaration where status = 'PENDING'")
        return n;
    }
}
''',
    "src/main/java/com/acme/clearance/DeclarationController.java": '''package com.acme.clearance;

@Controller
@RequestMapping("/declaration")
public class DeclarationController {
    @PostMapping("/reject.do")
    public String reject(Long id) {
        service.rejectDeclaration(id, "manual");
        return "declaration/list";
    }

    @JmsListener(destination = "clearance.inbound.queue")
    public void onMessage(String body) { }
}
''',
    "src/main/webapp/WEB-INF/jsp/declarationList.jsp": '''<%@ page import="com.acme.clearance.Declaration, java.util.List" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ include file="/WEB-INF/jsp/header.jsp" %>
<form action="<%=request.getContextPath()%>/declaration/reject.do" method="post">
  <a href="https://example.org/help">help</a>
</form>
<script>
function confirmReject(id) {
  $.post('/declaration/reject.do', {id: id});
}
</script>
''',
    "src/main/webapp/js/declaration.js": '''var Declaration = {
  load: function (id) {
    return fetch('/api/declaration/' + id);
  }
};
const formatStatus = (status) => status.toUpperCase();
''',
    "src/main/webapp/js/lib/jquery.min.js": "function minified(){return 1}\n",
    "src/main/webapp/WEB-INF/web.xml": '''<web-app>
  <servlet-mapping>
    <url-pattern>*.do</url-pattern>
  </servlet-mapping>
</web-app>
''',
    "src/main/resources/app.properties": "clearance.retry.max=3\n# a comment\n",
    "docs/design.md": '''# Clearance design

## Rejection flow

An officer rejects a declaration. 申报被退回后，系统写入审计日志。

```
# not a heading
```

## Retry policy

Retries up to clearance.retry.max times.
''',
    "target/classes/Generated.java": "class Generated {}\n",
}


def treesitter_importable():
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_java  # noqa: F401
        import tree_sitter_javascript  # noqa: F401
        return True
    except ImportError:
        return False


class Repo:
    """A throwaway git repository holding FILES."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        for rel, text in FILES.items():
            self.write(rel, text)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "init")

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def git(self, *args):
        subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)

    def cr(self, *args, treesitter=False, check=True):
        env = dict(os.environ)
        if not treesitter:
            env["CODEBASE_RESEARCH_NO_TREESITTER"] = "1"
        result = subprocess.run([sys.executable, CR, *args], capture_output=True, text=True,
                                cwd=self.root, env=env)
        if check and result.returncode != 0:
            raise AssertionError("cr %s failed (%d): %s" % (" ".join(args), result.returncode, result.stderr))
        return result

    def close(self):
        self._tmp.cleanup()


class TokenTest(unittest.TestCase):
    def test_identifiers_split_and_join(self):
        for word in ("getUserById", "get_user_by_id", "GET_USER_BY_ID"):
            terms = tokens.terms(word)
            for part in ("get", "user", "by", "id", "getuserbyid"):
                self.assertIn(part, terms, word)

    def test_acronyms_and_digits(self):
        self.assertEqual(tokens.terms("HTTPServer2"), ["http", "server", "2", "httpserver2"])

    def test_cjk_becomes_bigrams(self):
        self.assertEqual(tokens.terms("申报退回"), ["申报", "报退", "退回"])

    def test_query_ors_distinct_terms(self):
        self.assertEqual(tokens.as_query("user User"), '"user"')
        self.assertEqual(tokens.as_query("!!!"), "")


class DiscoverTest(unittest.TestCase):
    def test_excludes_at_any_depth(self):
        patterns = discover.DEFAULT_EXCLUDES
        self.assertTrue(discover.excluded("target/a.java", patterns))
        self.assertTrue(discover.excluded("module/target/a.java", patterns))
        self.assertTrue(discover.excluded("jquery.min.js", patterns))
        self.assertTrue(discover.excluded("web/js/jquery.min.js", patterns))
        self.assertFalse(discover.excluded("src/targeting/a.java", patterns))

    def test_rg_flags_unanchor_directories(self):
        flags = discover.rg_flags(["legacy/lib/**"])
        self.assertIn("-g '!**/target/**'", flags)
        self.assertIn("-g '!*.min.js'", flags)
        self.assertIn("-g '!**/legacy/lib/**'", flags)


class FactTest(unittest.TestCase):
    def facts(self, rel):
        return facts.extract(discover.lang_of(rel), FILES[rel])

    def test_sql_tables_with_direction(self):
        found = {(f.value, f.detail.split()[0]) for f in self.facts(
            "src/main/java/com/acme/clearance/DeclarationService.java") if f.type == "sql_table"}
        self.assertEqual(found, {("DECLARATION", "read"), ("DECLARATION", "write"),
                                 ("AUDIT_LOG", "write"), ("declaration", "read")})

    def test_prose_in_strings_is_not_sql(self):
        found = facts.extract("java", 'log("Update failed for the officer");\n')
        self.assertEqual(found, [])

    def test_urls_handlers_and_jsp(self):
        jsp = self.facts("src/main/webapp/WEB-INF/jsp/declarationList.jsp")
        refs = {f.value for f in jsp if f.type == "url_ref"}
        self.assertEqual(refs, {"/declaration/reject.do"})
        self.assertIn("/WEB-INF/jsp/header.jsp", {f.value for f in jsp if f.type == "include"})
        self.assertIn("java.util.List", {f.value for f in jsp if f.type == "jsp_import"})
        handlers = {f.value for f in self.facts("src/main/java/com/acme/clearance/DeclarationController.java")
                    if f.type == "url_handler"}
        self.assertEqual(handlers, {"/declaration", "/reject.do"})
        self.assertIn("*.do", {f.value for f in self.facts("src/main/webapp/WEB-INF/web.xml")})

    def test_queue_and_config_keys(self):
        controller = self.facts("src/main/java/com/acme/clearance/DeclarationController.java")
        self.assertIn("clearance.inbound.queue", {f.value for f in controller if f.type == "queue"})
        service = self.facts("src/main/java/com/acme/clearance/DeclarationService.java")
        self.assertIn(("clearance.retry.max", "used"), {(f.value, f.detail) for f in service if f.type == "config_key"})


class FallbackChunkTest(unittest.TestCase):
    def setUp(self):
        os.environ["CODEBASE_RESEARCH_NO_TREESITTER"] = "1"

    def tearDown(self):
        os.environ.pop("CODEBASE_RESEARCH_NO_TREESITTER", None)

    def test_regex_symbols_survive_broken_java(self):
        split = chunk.split("java", FILES["src/main/java/com/acme/clearance/DeclarationService.java"])
        self.assertEqual(split.chunker, "lines")
        names = [s.name for s in split.symbols]
        self.assertEqual(names, ["DeclarationService", "getDeclarationById", "rejectDeclaration", "countPending"])

    def test_markdown_ignores_fenced_hash(self):
        split = chunk.split("markdown", FILES["docs/design.md"])
        self.assertEqual([s.name for s in split.symbols],
                         ["Clearance design", "Clearance design > Rejection flow", "Clearance design > Retry policy"])


@unittest.skipUnless(treesitter_importable(), "tree-sitter not installed (run: cr deps)")
class TreeSitterChunkTest(unittest.TestCase):
    def test_one_chunk_per_method_with_its_doc_comment(self):
        split = chunk.split("java", FILES["src/main/java/com/acme/clearance/DeclarationService.java"])
        self.assertEqual(split.chunker, "tree-sitter")
        by_symbol = {c.symbol: (c.start, c.end) for c in split.chunks}
        self.assertEqual(by_symbol["DeclarationService.getDeclarationById(Long declarationId)"], (13, 16))
        self.assertIn("DeclarationService.countPending()", by_symbol)

    def test_javascript_object_methods_and_arrows(self):
        split = chunk.split("javascript", FILES["src/main/webapp/js/declaration.js"])
        self.assertEqual([s.name for s in split.symbols], ["Declaration.load", "formatStatus"])


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_search_returns_pointers_not_code(self):
        self.repo.cr("index", "--quiet")
        out = self.repo.cr("search", "reject", "declaration", "--json").stdout
        hits = json.loads(out)
        self.assertTrue(hits)
        self.assertEqual(set(hits[0]), {"path", "start", "end", "lang", "symbol", "score"})
        paths = {h["path"] for h in hits}
        self.assertIn("src/main/java/com/acme/clearance/DeclarationService.java", paths)
        self.assertNotIn("target/classes/Generated.java", paths)
        self.assertNotIn("src/main/webapp/js/lib/jquery.min.js", paths)

    def test_cjk_search_finds_docs(self):
        self.repo.cr("index", "--quiet")
        out = self.repo.cr("search", "退回", "--kind", "docs").stdout
        self.assertIn("docs/design.md:", out)

    def test_queries_refresh_changed_and_removed_files(self):
        self.repo.cr("index", "--quiet")
        self.repo.write("src/main/java/com/acme/clearance/Archive.java",
                        'class Archive { void purge() { jdbc.update("DELETE FROM ARCHIVE_QUEUE"); } }\n')
        os.remove(os.path.join(self.repo.root, "docs/design.md"))
        status = self.repo.cr("status").stdout
        self.assertIn("out of date: 1 changed or new, 1 removed", status)
        out = self.repo.cr("facts", "--type", "sql_table", "--match", "archive").stdout
        self.assertIn("refreshed 2 file(s) first: 1 added, 0 updated, 1 removed", out)
        self.assertIn("Archive.java:1  sql_table  ARCHIVE_QUEUE  write (DELETE FROM)", out)
        self.assertIn("out of date: 0 changed or new, 0 removed", self.repo.cr("status").stdout)

    def test_files_mode_and_summary(self):
        self.repo.cr("index", "--quiet")
        out = self.repo.cr("search", "declaration", "--files", "--lang", "java").stdout
        self.assertIn("DeclarationService.java", out)
        self.assertNotIn(".jsp", out)
        summary = self.repo.cr("facts", "--summary", "--type", "sql_table").stdout
        self.assertIn("sql_table  DECLARATION  read (FROM)  x2 in 1 file(s)", summary)

    def test_extra_excludes_persist(self):
        self.repo.cr("index", "--quiet", "--exclude", "docs/**")
        self.assertNotIn("docs/design.md", self.repo.cr("map").stdout)
        self.assertIn("-g '!**/docs/**'", self.repo.cr("excludes").stdout)

    def test_index_is_kept_out_of_git(self):
        self.repo.cr("index", "--quiet")
        with open(os.path.join(self.repo.root, ".git", "info", "exclude")) as handle:
            self.assertIn(".codebase-research/", handle.read().split("\n"))
        status = subprocess.run(["git", "-C", self.repo.root, "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")

    def test_no_index_exits_3(self):
        result = self.repo.cr("search", "x", check=False)
        self.assertEqual(result.returncode, 3)
        self.assertIn("run: cr index", result.stderr)

    @unittest.skipUnless(treesitter_importable(), "tree-sitter not installed (run: cr deps)")
    def test_treesitter_index(self):
        out = self.repo.cr("index", treesitter=True).stdout
        self.assertIn("tree-sitter 3", out)
        hits = self.repo.cr("search", "count", "pending", "-k", "1", treesitter=True).stdout
        self.assertIn("DeclarationService.countPending()", hits)


class WrapperTest(unittest.TestCase):
    def test_wrapper_runs_from_anywhere_and_honours_python_override(self):
        bash = shutil.which("bash") or "/bin/bash"
        env = dict(os.environ, CODEBASE_RESEARCH_PYTHON=sys.executable,
                   CODEBASE_RESEARCH_HOME=tempfile.mkdtemp())
        result = subprocess.run([bash, os.path.join(SCRIPTS, "cr"), "deps", "--check"],
                                capture_output=True, text=True, cwd=tempfile.gettempdir(), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("interpreter: %s" % sys.executable, result.stdout)


if __name__ == "__main__":
    unittest.main()
