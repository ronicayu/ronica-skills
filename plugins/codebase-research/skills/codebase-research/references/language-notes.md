# Language notes

Practical notes for searching Java, JSP and JavaScript codebases, and for building indexes over
them. Read the section you need.

## Searching identifiers

Identifiers are compound words. A search for one part of a name should still find it, and a search
for the full name should not be drowned out by its parts.

| Object | Rule |
| --- | --- |
| Java identifiers | Split camelCase, PascalCase and `UPPER_SNAKE`; keep the whole word too |
| Packages and qualified names | Split on `.`; keep the full string too |
| JavaScript | As Java; handle identifiers that start with `$` or `_` |
| URL paths | Split on `/`; keep the full path too |
| JSP tags | Keep `c:forEach`; also index `forEach` |
| Stop words | Avoid general-purpose stop-word lists: `get`, `use` and `server` carry meaning in code |
| Chinese or other CJK comments | Need a CJK tokenizer or character n-grams |

With grep, cover the forms an identifier takes: `getUserById`, `get_user_by_id`, `user_by_id`, and
the SQL or URL spelling where relevant. `-S` (smart case) keeps the pattern case-insensitive until
it contains an uppercase letter.

## Parsing code that does not compile

tree-sitter does not need the code to compile. It is an error-tolerant parser: syntax errors become
`ERROR` or `MISSING` nodes and the rest of the file parses normally. It cannot resolve types, bind
symbols across files or build an exact call graph — those need a compiler or language server.

| Source | Chunking | Metadata worth extracting |
| --- | --- | --- |
| Java | tree-sitter by class and method; fall back to line chunks where `ERROR` nodes dominate | Class name, method signature, annotations, Javadoc, package |
| JavaScript | tree-sitter by function and class | Function name, JSDoc, request URLs |
| JSP | Whole file when small, overlapping line chunks when large; inline `<script>` blocks through tree-sitter-javascript | `page import`, `include`, `taglib`, `form action`, links and AJAX URLs |
| Documentation | By heading structure, keeping the heading path | Heading path, document version or date, identifiers mentioned |

There is no official tree-sitter grammar for JSP. Treat a JSP file as HTML with embedded Java and
extract its structure with rules. Do not skip scriptlets (`<% … %>`): in legacy applications they
often hold business logic that has to be findable. Wrapping a scriptlet in a dummy method before
parsing it as Java is an untested idea; try it on real files before relying on it.

Call sites extracted by name are leads, not facts. A method name can match several classes or
overloads; confirm by reading the code before writing a call relationship into a conclusion.

## Facts worth extracting into a table

Enumeration questions depend on these. Extract them with tree-sitter queries and rules — none needs
compilation — and store each with its `path:line`.

| Fact | Where it comes from |
| --- | --- |
| SQL statements and table names | Java string literals; MyBatis or Hibernate XML mappings |
| URL to handler | Servlet annotations, `web.xml`, Spring or Struts configuration; JSP `form action` and AJAX calls |
| Queues, topics, remote calls | JMS or MQ names, RMI interfaces, HTTP client calls |
| File paths and configuration keys | String literals, `*.properties` files |
| Page composition | JSP `include` and custom tags |

The table is best effort. String-built SQL, class names constructed at runtime and configuration
resolved at runtime escape it, so cross-check enumerations with grep as SKILL.md describes.

## Exclusions

Typical build output and vendored code to exclude from both indexes and grep: `target/`, `build/`,
`dist/`, `node_modules/`, `*.min.js`, and any third-party library directory checked into the source
tree (for example a bundled jQuery). Minified files are the worst offenders for grep output: one
line can run to thousands of characters.
