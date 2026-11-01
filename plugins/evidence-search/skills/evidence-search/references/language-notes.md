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

## Facts in the fact table

Enumeration questions depend on these. `evs index` extracts them with regular expressions — none
needs compilation or tree-sitter — and stores each with its `path:line`; `evs facts` queries them.

| Fact type | Where it comes from |
| --- | --- |
| `sql_table` | SQL statements in MyBatis, iBATIS and Hibernate XML; `.sql` files; string literals in Java, JavaScript and JSP, joined across the lines of one statement or a run of `append` calls; Hibernate `table=` attributes and JPA `@Table`. String literals inside the SQL are blanked first, so data is never read as a table |
| `url_handler` | `@RequestMapping` and its variants, with a class-level mapping joined to each method's; `@WebServlet`, `@Path`; `<url-pattern>` in `web.xml`; Struts `<action>` |
| `url_ref` | JSP and HTML `action` and `href`; jQuery AJAX, `fetch`, `XMLHttpRequest.open`, `location` assignments |
| `include`, `jsp_import`, `taglib` | JSP directives, `<jsp:include>`, `<jsp:forward>`, `<c:import>` |
| `entry_point` | MDBs: `ejb-jar.xml` `<message-driven>`, `@MessageDriven`, EJBGen `@ejbgen:message-driven`, `implements MessageListener` or `MessageDrivenBean`, Spring `jms:listener` and listener containers. HTTP: `web.xml` servlets, `extends HttpServlet`, Struts actions, Spring controllers. Scheduled: `@Scheduled`, `@Schedule`, `@Timeout`, Quartz jobs and cron expressions, `TimerTask`, `TimedObject`. Startup: `ServletContextListener`, WebLogic `T3StartupDef` and `ApplicationLifecycleListener`, `@Startup`, `main`. `ejb-jar.xml` session beans, `@WebService` |
| `queue` | `weblogic-ejb-jar.xml` `destination-jndi-name` and `destination-resource-link`; activation config; WebLogic JMS modules, including foreign-server destinations (local JNDI name to remote MQ queue); IBM MQ `accessQueue`, `MQQueueManager`, `MQQueue`, `queue://` URIs; JNDI `lookup("jms/…")`; `@JmsListener`, `createQueue`, `createTopic`, Kafka and Rabbit listeners; properties keys naming a queue, topic, destination, channel or queue manager; Markdown and CSV tables |
| `component` | A class in a Markdown or CSV binding table whose column does not name listeners, such as a sender |
| `config_key` | Keys defined in `*.properties`; keys used through `@Value` and `getProperty` |

Not extracted: remote calls (RMI, HTTP clients), file paths, SQL assembled from variables or
constants defined elsewhere, and table names chosen at runtime.

XML files are chunked by named element — mapper statements, Struts actions, Spring beans, servlets
and filters — so a search hit on a mapper reads `select getAccountByUsername`, not a line window.

The table is best effort. String-built SQL, class names constructed at runtime and configuration
resolved at runtime escape it, so cross-check enumerations with grep as SKILL.md describes.

## Finding entry points with grep

Grep for the declaration, not for a method name every listener shares. Use `-i` for XML tags.

| Entry point | Pattern |
| --- | --- |
| MDB, descriptor | `<message-driven>` in any XML; `<message-driven-descriptor>` in WebLogic's |
| MDB, code | `@MessageDriven`, `@ejbgen:message-driven`, `implements\s+[^{]*\bMessage(Listener\|DrivenBean)\b` |
| Queue binding | `destination-jndi-name`, `destinationLookup`, `remote-jndi-name`, `accessQueue\s*\(` |
| HTTP | `<servlet-class>`, `extends\s+HttpServlet`, `@(Request\|Get\|Post)Mapping`, `<action\s` |
| Scheduled | `@Scheduled`, `@Schedule\b`, `@Timeout`, `implements\s+[^{]*\bJob\b`, `<cron-expression>`, `cronExpression` |
| Startup | `ServletContextListener`, `T3StartupDef`, `ApplicationLifecycleListener`, `<startup-class>`, `static\s+void\s+main\s*\(` |

When the descriptors are not in the repository, the binding between a listener and its queue is
often recorded in a document. `evs` reads Markdown pipe tables and CSV files whose header names a
listener (MDB, listener, receiver, consumer), a JNDI name, or a queue (queue, destination, MQ), and
links each row's cells. A binding written as prose is not extracted: search for it.

## Exclusions

Typical build output and vendored code to exclude from both indexes and grep: `target/`, `build/`,
`dist/`, `node_modules/`, `*.min.js`, and any third-party library directory checked into the source
tree (for example a bundled jQuery). Minified files are the worst offenders for grep output: one
line can run to thousands of characters.
