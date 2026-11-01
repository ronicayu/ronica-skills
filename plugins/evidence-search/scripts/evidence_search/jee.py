"""Entry points and messaging in Java EE, WebLogic and IBM MQ applications.

Descriptors are recognised by their content, not their file name, so a
renamed or split ejb-jar.xml still counts. Each finding is
(type, value, detail, offset, ref): offset is a character offset in the
file, and ref holds space-separated link keys that tie facts in different
files together:

  ejb:<ejb-name>     ejb-jar.xml, weblogic-ejb-jar.xml, @MessageDriven(name=...)
  class:<FQN>        a class named by a descriptor and the class itself
  dest:<name>        a message-destination-link and the destination it names
  jndi:<name>        a JNDI name and the WebLogic JMS module entry behind it
  bean:<id>          a Spring bean and the listener container that uses it
  mq:<queue>         an IBM MQ queue name in code, config or a foreign server

Types: entry_point (detail starts with mdb, http, scheduled, startup,
webservice or ejb) and queue.
"""

import re

_P = r"(?:[\w-]+:)?"  # optional XML namespace prefix


def _tag(name):
    return re.compile(r"<%s%s\b[^>]*>\s*([^<]*?)\s*</%s%s\s*>" % (_P, name, _P, name), re.S)


_EJB_NAME = _tag("ejb-name")
_EJB_CLASS = _tag("ejb-class")
_MSG_DEST_LINK = _tag("message-destination-link")
_MSG_DEST_NAME = _tag("message-destination-name")
_DEST_TYPE = _tag("(?:message-)?destination-type")
_DEST_JNDI = _tag("destination-jndi-name")
_DEST_RESOURCE_LINK = _tag("destination-resource-link")
_JNDI_NAME = _tag("jndi-name")
_LOCAL_JNDI = _tag("local-jndi-name")
_REMOTE_JNDI = _tag("remote-jndi-name")
_REMOTE = _tag("(?:remote|business-remote|home)")
_ACTIVATION = re.compile(
    r"<%sactivation-config-property-name>\s*([^<]+?)\s*</%sactivation-config-property-name>\s*"
    r"<%sactivation-config-property-value>\s*([^<]+?)\s*</%sactivation-config-property-value>" % (_P, _P, _P, _P), re.S)
_DESTINATION_PROPERTIES = {"destination", "destinationlookup", "destinationjndiname", "destinationname"}


def _blocks(text, name):
    return re.finditer(r"<%s%s\b[^>]*>(.*?)</%s%s\s*>" % (_P, name, _P, name), text, re.S)


def _first(pattern, block):
    match = pattern.search(block)
    return (match.group(1).strip(), match.start(1)) if match and match.group(1).strip() else (None, None)


# ------------------------------------------------------------------ xml


def _ejb_jar(text, out):
    for block in _blocks(text, "message-driven"):
        body, base = block.group(1), block.start(1)
        name, _ = _first(_EJB_NAME, body)
        cls, cls_at = _first(_EJB_CLASS, body)
        refs = " ".join(k for k in (name and "ejb:" + name, cls and "class:" + cls) if k)
        kind = _first(_DEST_TYPE, body)[0] or ""
        kind = " " + kind.split(".")[-1].lower() if kind else ""
        out.append(("entry_point", cls or name, "mdb%s (ejb-jar%s)" % (kind, ", ejb-name " + name if name else ""),
                    base + (cls_at or 0), refs))
        for prop, value in _ACTIVATION.findall(body):
            if prop.strip().lower() in _DESTINATION_PROPERTIES:
                at = base + body.find(value)
                out.append(("queue", value.strip(), "mdb %s listens (activation-config %s)" % (name or cls, prop.strip()),
                            at, refs + " jndi:" + value.strip()))
        link, link_at = _first(_MSG_DEST_LINK, body)
        if link:
            out.append(("queue", link, "mdb %s listens (message-destination-link)" % (name or cls), base + link_at,
                        refs + " dest:" + link.split("#")[-1]))
    for block in _blocks(text, "session"):
        body, base = block.group(1), block.start(1)
        name, _ = _first(_EJB_NAME, body)
        cls, cls_at = _first(_EJB_CLASS, body)
        if not (name or cls):
            continue
        remote = " remote" if _REMOTE.search(body) else ""
        refs = " ".join(k for k in (name and "ejb:" + name, cls and "class:" + cls) if k)
        out.append(("entry_point", cls or name, "ejb session%s (ejb-jar%s)" % (remote, ", ejb-name " + name if name else ""),
                    base + (cls_at or 0), refs))


def _weblogic_ejb_jar(text, out):
    for block in _blocks(text, "weblogic-enterprise-bean"):
        body, base = block.group(1), block.start(1)
        name, _ = _first(_EJB_NAME, body)
        if not name or "message-driven-descriptor" not in body:
            continue
        for pattern, label in ((_DEST_JNDI, "destination-jndi-name"), (_DEST_RESOURCE_LINK, "destination-resource-link")):
            value, at = _first(pattern, body)
            if value:
                out.append(("queue", value, "mdb %s listens (weblogic-ejb-jar %s)" % (name, label), base + at,
                            "ejb:%s jndi:%s" % (name, value)))
    for block in _blocks(text, "message-destination-descriptor"):
        body, base = block.group(1), block.start(1)
        name, _ = _first(_MSG_DEST_NAME, body)
        value, at = _first(_DEST_JNDI, body)
        if name and value:
            out.append(("queue", value, "message-destination %s (weblogic)" % name, base + at,
                        "dest:%s jndi:%s" % (name, value)))


def _weblogic_jms_module(text, out):
    for kind in ("queue", "topic", "uniform-distributed-queue", "uniform-distributed-topic",
                 "distributed-queue", "distributed-topic"):
        for block in re.finditer(r"<%s%s\b([^>]*)>(.*?)</%s%s\s*>" % (_P, kind, _P, kind), text, re.S):
            name = re.search(r"\bname\s*=\s*\"([^\"]+)\"", block.group(1))
            value, at = _first(_JNDI_NAME, block.group(2))
            if value:
                out.append(("queue", value, "weblogic jms %s %s" % (kind, name.group(1) if name else ""),
                            block.start(2) + at, "jndi:" + value))
    for block in _blocks(text, "foreign-destination"):
        body, base = block.group(1), block.start(1)
        local, local_at = _first(_LOCAL_JNDI, body)
        remote, remote_at = _first(_REMOTE_JNDI, body)
        if local:
            out.append(("queue", local, "weblogic foreign destination -> %s" % (remote or "?"), base + local_at,
                        "jndi:" + local))
        if remote:
            out.append(("queue", remote, "remote queue behind %s (weblogic foreign server)" % (local or "?"),
                        base + remote_at, ("jndi:%s mq:%s" % (local, remote)) if local else "mq:" + remote))


_WEB_SERVLET_CLASS = _tag("servlet-class")
_WEB_LISTENER_CLASS = _tag("listener-class")
_JOB_CLASS = _tag("job-class")
_CRON = _tag("cron-expression")
_SPRING_JMS_LISTENER = re.compile(r"<%slistener\b[^>]*\bdestination\s*=\s*\"([^\"]+)\"[^>]*>" % _P)
_SPRING_CONTAINER = re.compile(
    r"<bean\b[^>]*\bclass\s*=\s*\"[^\"]*(?:DefaultMessageListenerContainer|SimpleMessageListenerContainer)\"[^>]*>(.*?)</bean>",
    re.S)
_PROPERTY = re.compile(r"<property\b[^>]*\bname\s*=\s*\"(\w+)\"[^>]*\b(value|ref)\s*=\s*\"([^\"]+)\"")
_CRON_PROPERTY = re.compile(r"<property\b[^>]*\bname\s*=\s*\"cronExpression\"[^>]*\bvalue\s*=\s*\"([^\"]+)\"")


def _web_and_spring(text, out):
    for value, at in ((m.group(1), m.start(1)) for m in _WEB_SERVLET_CLASS.finditer(text)):
        out.append(("entry_point", value, "http servlet (web.xml)", at, "class:" + value))
    for value, at in ((m.group(1), m.start(1)) for m in _WEB_LISTENER_CLASS.finditer(text)):
        out.append(("entry_point", value, "startup listener (web.xml)", at, "class:" + value))
    for value, at in ((m.group(1), m.start(1)) for m in _JOB_CLASS.finditer(text)):
        out.append(("entry_point", value, "scheduled quartz job", at, "class:" + value))
    for match in _CRON.finditer(text):
        out.append(("entry_point", match.group(1), "scheduled cron expression", match.start(1), ""))
    for match in _CRON_PROPERTY.finditer(text):
        out.append(("entry_point", match.group(1), "scheduled cron expression (spring)", match.start(1), ""))
    for match in _SPRING_JMS_LISTENER.finditer(text):
        ref = re.search(r"\bref\s*=\s*\"([^\"]+)\"", match.group(0))
        method = re.search(r"\bmethod\s*=\s*\"([^\"]+)\"", match.group(0))
        bean = ref.group(1) if ref else "?"
        target = bean + ("." + method.group(1) if method else "")
        out.append(("entry_point", target, "mdb spring jms:listener", match.start(), "bean:" + bean))
        out.append(("queue", match.group(1), "spring jms:listener -> %s listens" % target, match.start(1),
                    "bean:%s jndi:%s" % (bean, match.group(1))))
    for container in _SPRING_CONTAINER.finditer(text):
        props = {name: (kind, value, container.start(1) + m.start(3))
                 for m in _PROPERTY.finditer(container.group(1)) for name, kind, value in [m.groups()]}
        listener = props.get("messageListener")
        bean = listener[1] if listener else "?"
        if listener:
            out.append(("entry_point", bean, "mdb spring listener container", listener[2], "bean:" + bean))
        for key in ("destinationName", "destination"):
            if key in props:
                _, value, at = props[key]
                out.append(("queue", value, "spring listener container -> %s listens (%s)" % (bean, key), at,
                            "bean:%s jndi:%s" % (bean, value)))


def xml(text):
    out = []
    if re.search(r"<%s(?:message-driven|session)\b" % _P, text):
        _ejb_jar(text, out)
    if re.search(r"<%s(?:weblogic-enterprise-bean|message-destination-descriptor)\b" % _P, text):
        _weblogic_ejb_jar(text, out)
    if re.search(r"<%s(?:weblogic-jms|foreign-server|foreign-destination)\b" % _P, text):
        _weblogic_jms_module(text, out)
    _web_and_spring(text, out)
    return out


# ----------------------------------------------------------------- java

_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_CLASS = re.compile(r"\b(class|interface|enum)\s+(\w+)([^{;]*)\{")
_MESSAGE_DRIVEN = re.compile(r"@(?:[\w.]+\.)?MessageDriven\b")
_EJBGEN_MDB = re.compile(r"@ejbgen:message-driven\b(.*?)\*/", re.S)
_STRING_ARG = r"\s*=\s*\"([^\"]+)\""
_SCHEDULE = re.compile(r"@(Scheduled|Schedule|Schedules|Timeout)\b")
_METHOD_AFTER = re.compile(
    r"\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)*"
    r"(?:<[^>]+>\s+)?[\w<>\[\],.? ]+?\s+(\w+)\s*\(")
_MAIN = re.compile(r"\bpublic\s+static\s+void\s+main\s*\(\s*(?:final\s+)?String")

# (type keyword in class header, detail)
_HEADER_RULES = [
    (re.compile(r"\bMessageListener\b"), "mdb (implements MessageListener)"),
    (re.compile(r"\bMessageDrivenBean\b"), "mdb (implements MessageDrivenBean)"),
    (re.compile(r"\bextends\s+(?:javax\.servlet\.http\.)?HttpServlet\b"), "http servlet class"),
    (re.compile(r"\bextends\s+(?:[\w.]*\.)?(?:Action|DispatchAction|LookupDispatchAction|MappingDispatchAction|"
                r"ActionSupport)\b"), "http struts action"),
    (re.compile(r"\bServletContextListener\b"), "startup ServletContextListener"),
    (re.compile(r"\bT3StartupDef\b"), "startup weblogic T3StartupDef"),
    (re.compile(r"\bextends\s+(?:weblogic\.application\.)?ApplicationLifecycleListener\b"),
     "startup weblogic ApplicationLifecycleListener"),
    (re.compile(r"\bimplements\b[^{]*\b(?:org\.quartz\.)?(?:Stateful)?Job\b"), "scheduled quartz job"),
    (re.compile(r"\bextends\s+(?:[\w.]*\.)?QuartzJobBean\b"), "scheduled quartz job"),
    (re.compile(r"\bextends\s+(?:java\.util\.)?TimerTask\b"), "scheduled TimerTask"),
    (re.compile(r"\bTimedObject\b"), "scheduled EJB TimedObject"),
]
_CLASS_ANNOTATIONS = [
    (re.compile(r"@(?:javax\.jws\.|jakarta\.jws\.)?WebService\b"), "webservice @WebService"),
    (re.compile(r"@(?:Rest)?Controller\b"), "http spring controller"),
    (re.compile(r"@Startup\b"), "startup @Startup"),
]

_MQ = [
    (re.compile(r"\baccessQueue\s*\(\s*(?:\"([^\"]+)\"|([A-Za-z_][\w.]*))"), "IBM MQ accessQueue"),
    (re.compile(r"\bnew\s+MQQueueManager\s*\(\s*(?:\"([^\"]+)\"|([A-Za-z_][\w.]*))"), "IBM MQ queue manager"),
    (re.compile(r"\bnew\s+MQQueue\s*\(\s*(?:\"([^\"]+)\"|([A-Za-z_][\w.]*))"), "IBM MQ JMS MQQueue"),
    (re.compile(r"\"queue://[^/\"]*/([^\"?]+)"), "IBM MQ queue URI"),
    (re.compile(r"\bcreate(?:Queue|Topic)\s*\(\s*([A-Za-z_][\w.]*)\s*\)"), "JMS createQueue (constant)"),
    (re.compile(r"\blookup\s*\(\s*\"((?:java:comp/env/)?jms/[^\"]+)\""), "JNDI lookup"),
]


def _balanced(text, start):
    """End offset of the parenthesised group opening at or after START, or START."""
    open_at = text.find("(", start)
    if open_at < 0 or text[start:open_at].strip():
        return start
    depth = 0
    for index in range(open_at, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _annotation_args(text, match):
    end = _balanced(text, match.end())
    return text[match.end():end], end


def java(text):
    out = []
    package = _PACKAGE.search(text)
    prefix = package.group(1) + "." if package else ""
    classes = [(m.start(), m.group(2), m.group(3), m.start(2)) for m in _CLASS.finditer(text) if m.group(1) == "class"]

    def class_after(offset):
        for start, name, header, at in classes:
            if start >= offset:
                return name, header, at
        return None, "", offset

    def class_before(offset):
        found = None
        for start, name, header, at in classes:
            if start <= offset:
                found = name
        return found

    annotated = set()
    for match in _MESSAGE_DRIVEN.finditer(text):
        args, end = _annotation_args(text, match)
        name, _, at = class_after(end)
        if not name:
            continue
        annotated.add(name)
        fqn = prefix + name
        ejb = re.search(r"\b(?:name|ejbName)" + _STRING_ARG, args)
        refs = "class:%s ejb:%s" % (fqn, ejb.group(1) if ejb else name)
        out.append(("entry_point", fqn, "mdb (@MessageDriven)", at, refs))
        destinations = re.findall(r"propertyName\s*=\s*\"(\w+)\"\s*,\s*propertyValue\s*=\s*\"([^\"]+)\"", args)
        for key in ("mappedName", "destinationJndiName", "destinationName", "destination"):
            for value in re.findall(r"\b%s%s" % (key, _STRING_ARG), args):
                destinations.append((key, value))
        for key, value in destinations:
            if key.lower() in _DESTINATION_PROPERTIES or key == "mappedName":
                out.append(("queue", value, "mdb %s listens (@MessageDriven %s)" % (name, key),
                            match.start() + text[match.start():end].find(value), refs + " jndi:" + value))
    for match in _EJBGEN_MDB.finditer(text):
        body = match.group(1)
        name, _, at = class_after(match.start())
        if not name or name in annotated:
            continue
        annotated.add(name)
        fqn = prefix + name
        ejb = re.search(r"\bejb-name\s*=\s*\"?([\w.-]+)", body)
        refs = "class:%s ejb:%s" % (fqn, ejb.group(1) if ejb else name)
        out.append(("entry_point", fqn, "mdb (EJBGen @ejbgen:message-driven)", at, refs))
        dest = re.search(r"\bdestination-jndi-name\s*=\s*\"?([\w./:-]+)", body)
        if dest:
            out.append(("queue", dest.group(1), "mdb %s listens (EJBGen destination-jndi-name)" % name,
                        match.start(1) + body.find(dest.group(1)), refs + " jndi:" + dest.group(1)))

    for start, name, header, at in classes:
        fqn = prefix + name
        window = text[max(0, start - 600):start]
        last_brace = max(window.rfind("}"), window.rfind(";"))
        annotations = window[last_brace + 1:] if last_brace >= 0 else window
        for pattern, detail in _HEADER_RULES:
            if pattern.search(header) and not (detail.startswith("mdb") and name in annotated):
                out.append(("entry_point", fqn, detail, at, "class:" + fqn))
                break
        for pattern, detail in _CLASS_ANNOTATIONS:
            if pattern.search(annotations):
                out.append(("entry_point", fqn, detail, at, "class:" + fqn))

    for match in _SCHEDULE.finditer(text):
        args, end = _annotation_args(text, match)
        method = _METHOD_AFTER.match(text, end)
        owner = class_before(match.start())
        if not method or not owner:
            continue
        detail = "scheduled @%s" % match.group(1)
        cron = re.search(r"\b(?:cron|expression)" + _STRING_ARG, args)
        if cron:
            detail += " cron %s" % cron.group(1)
        out.append(("entry_point", "%s%s.%s" % (prefix, owner, method.group(1)), detail, method.start(1),
                    "class:" + prefix + owner))

    for match in _MAIN.finditer(text):
        owner = class_before(match.start())
        if owner:
            out.append(("entry_point", prefix + owner + ".main", "startup main method", match.start(),
                        "class:" + prefix + owner))

    for pattern, detail in _MQ:
        for match in pattern.finditer(text):
            literal = match.group(1)
            constant = match.group(2) if pattern.groups >= 2 else None
            value = literal if literal is not None else constant
            if not value:
                continue
            label = detail
            if literal is None:
                resolved = re.search(r"\b%s\s*=\s*\"([^\"]+)\"" % re.escape(value.split(".")[-1]), text)
                if resolved:
                    label = "%s (via constant %s)" % (detail.replace(" (constant)", ""), value)
                    value = resolved.group(1)
                elif not detail.endswith("(constant)"):
                    label = detail + " (constant, defined elsewhere)"
            refs = "jndi:" + value if value.startswith(("jms/", "java:")) else "mq:" + value
            out.append(("queue", value, label, match.start(), refs))
    return out


# ----------------------------------------------------------- properties

_QUEUE_KEY = re.compile(r"(queue|topic|destination|qmgr|queue[._-]?manager|channel)", re.I)
_PROPERTY_LINE = re.compile(r"^\s*([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*[=:]\s*(\S+)\s*$", re.M)


def properties(text):
    out = []
    for match in _PROPERTY_LINE.finditer(text):
        key, value = match.group(1), match.group(2)
        if _QUEUE_KEY.search(key) and not value.startswith(("${", "#")):
            out.append(("queue", value, "config key %s" % key, match.start(2), "jndi:%s mq:%s" % (value, value)))
    return out
