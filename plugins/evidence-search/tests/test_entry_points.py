"""Entry points and queue bindings: WebLogic descriptors, annotations, IBM MQ, and documented tables.

Run: python3 -m unittest discover -s plugins/evidence-search/tests
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

from evidence_search import facts  # noqa: E402
from test_evs import Repo  # noqa: E402


def found(lang, text, fact_type=None):
    return {(f.type, f.value, f.detail, f.line) for f in facts.extract(lang, text)
            if fact_type is None or f.type == fact_type}


EJB_JAR = """<?xml version="1.0"?>
<!DOCTYPE ejb-jar PUBLIC "-//Sun Microsystems, Inc.//DTD Enterprise JavaBeans 2.0//EN" "http://java.sun.com/dtd/ejb-jar_2_0.dtd">
<ejb-jar>
  <enterprise-beans>
    <message-driven>
      <ejb-name>PermitMDB</ejb-name>
      <ejb-class>sg.gov.tn.permit.PermitReceiver</ejb-class>
      <transaction-type>Container</transaction-type>
      <message-driven-destination>
        <destination-type>javax.jms.Queue</destination-type>
      </message-driven-destination>
    </message-driven>
    <session>
      <ejb-name>ClearanceService</ejb-name>
      <home>sg.gov.tn.ClearanceHome</home>
      <remote>sg.gov.tn.Clearance</remote>
      <ejb-class>sg.gov.tn.ClearanceBean</ejb-class>
    </session>
  </enterprise-beans>
</ejb-jar>
"""

WEBLOGIC_EJB_JAR = """<weblogic-ejb-jar>
  <weblogic-enterprise-bean>
    <ejb-name>PermitMDB</ejb-name>
    <message-driven-descriptor>
      <destination-jndi-name>jms/PermitInQueue</destination-jndi-name>
      <connection-factory-jndi-name>jms/TNConnectionFactory</connection-factory-jndi-name>
    </message-driven-descriptor>
  </weblogic-enterprise-bean>
</weblogic-ejb-jar>
"""

JMS_MODULE = """<weblogic-jms xmlns="http://xmlns.oracle.com/weblogic/weblogic-jms">
  <foreign-server name="MQServer">
    <foreign-destination name="PermitIn">
      <local-jndi-name>jms/PermitInQueue</local-jndi-name>
      <remote-jndi-name>TN.PERMIT.REQ</remote-jndi-name>
    </foreign-destination>
  </foreign-server>
  <queue name="AuditQueue">
    <jndi-name>jms/AuditQueue</jndi-name>
  </queue>
</weblogic-jms>
"""


class DescriptorTest(unittest.TestCase):
    def test_ejb_jar_mdb_and_session(self):
        got = found("xml", EJB_JAR, "entry_point")
        self.assertEqual(got, {
            ("entry_point", "sg.gov.tn.permit.PermitReceiver", "mdb queue (ejb-jar, ejb-name PermitMDB)", 7),
            ("entry_point", "sg.gov.tn.ClearanceBean", "ejb session remote (ejb-jar, ejb-name ClearanceService)", 17)})

    def test_weblogic_destination_and_foreign_mq(self):
        self.assertEqual(found("xml", WEBLOGIC_EJB_JAR), {
            ("queue", "jms/PermitInQueue", "mdb PermitMDB listens (weblogic-ejb-jar destination-jndi-name)", 5)})
        self.assertEqual(found("xml", JMS_MODULE), {
            ("queue", "jms/PermitInQueue", "weblogic foreign destination -> TN.PERMIT.REQ", 4),
            ("queue", "TN.PERMIT.REQ", "remote queue behind jms/PermitInQueue (weblogic foreign server)", 5),
            ("queue", "jms/AuditQueue", "weblogic jms queue AuditQueue", 9)})

    def test_descriptors_found_by_content_not_name(self):
        renamed = EJB_JAR.replace("<ejb-jar>", "<ejb-jar xmlns:j2ee='x'>")
        self.assertTrue(found("xml", renamed, "entry_point"))


class JavaTest(unittest.TestCase):
    def test_annotated_mdb_over_several_lines(self):
        java = ('package sg.gov.tn;\n'
                '@MessageDriven(name = "ClearanceMDB",\n'
                '    activationConfig = {\n'
                '        @ActivationConfigProperty(propertyName = "destinationLookup",\n'
                '                                  propertyValue = "jms/ClearanceIn") })\n'
                'public class ClearanceReceiver implements MessageListener {\n'
                '    public void onMessage(Message m) { }\n}\n')
        self.assertEqual(found("java", java), {
            ("entry_point", "sg.gov.tn.ClearanceReceiver", "mdb (@MessageDriven)", 6),
            ("queue", "jms/ClearanceIn", "mdb ClearanceReceiver listens (@MessageDriven destinationLookup)", 5)})

    def test_ejbgen_tags(self):
        java = ('package sg.gov.tn;\n/**\n * @ejbgen:message-driven\n *   ejb-name = AuditMDB\n'
                ' *   destination-jndi-name = jms/AuditQueue\n */\npublic class AuditReceiver\n'
                '    implements MessageDrivenBean, MessageListener { }\n')
        got = found("java", java)
        self.assertIn(("entry_point", "sg.gov.tn.AuditReceiver", "mdb (EJBGen @ejbgen:message-driven)", 7), got)
        self.assertIn(("queue", "jms/AuditQueue", "mdb AuditReceiver listens (EJBGen destination-jndi-name)", 5), got)
        self.assertNotIn("mdb (implements MessageListener)", {d for _, _, d, _ in got})

    def test_ibm_mq_literals_and_constants(self):
        java = ('class Sender {\n  static final String OUT = "TN.PERMIT.REPLY";\n'
                '  void send() {\n    MQQueueManager qm = new MQQueueManager("TNQM01");\n'
                '    qm.accessQueue(OUT, 16);\n    qm.accessQueue(Config.AUDIT_QUEUE, 16);\n'
                '    qm.accessQueue("TN.AUDIT.OUT", 16);\n  }\n}\n')
        self.assertEqual(found("java", java, "queue"), {
            ("queue", "TNQM01", "IBM MQ queue manager", 4),
            ("queue", "TN.PERMIT.REPLY", "IBM MQ accessQueue (via constant OUT)", 5),
            ("queue", "Config.AUDIT_QUEUE", "IBM MQ accessQueue (constant, defined elsewhere)", 6),
            ("queue", "TN.AUDIT.OUT", "IBM MQ accessQueue", 7)})

    def test_other_entry_points(self):
        java = ('package sg.gov.tn;\n'
                'public class Boot implements ServletContextListener { }\n'
                'class Purge implements org.quartz.Job { }\n'
                'class Startup implements T3StartupDef { }\n'
                'class Jobs {\n  @Scheduled(cron = "0 0 2 * * *")\n  public void nightly() { }\n'
                '  public static void main(String[] args) { }\n}\n'
                'class Upload extends HttpServlet { }\n')
        got = {(v, d) for _, v, d, _ in found("java", java, "entry_point")}
        self.assertEqual(got, {
            ("sg.gov.tn.Boot", "startup ServletContextListener"),
            ("sg.gov.tn.Purge", "scheduled quartz job"),
            ("sg.gov.tn.Startup", "startup weblogic T3StartupDef"),
            ("sg.gov.tn.Jobs.nightly", "scheduled @Scheduled cron 0 0 2 * * *"),
            ("sg.gov.tn.Jobs.main", "startup main method"),
            ("sg.gov.tn.Upload", "http servlet class")})

    def test_spring_jms_listener_xml(self):
        xml = ('<beans>\n  <jms:listener-container>\n'
               '    <jms:listener destination="jms/PermitInQueue" ref="permitHandler" method="handle"/>\n'
               '  </jms:listener-container>\n</beans>\n')
        self.assertEqual(found("xml", xml), {
            ("entry_point", "permitHandler.handle", "mdb spring jms:listener", 3),
            ("queue", "jms/PermitInQueue", "spring jms:listener -> permitHandler.handle listens", 3)})


class DocumentedBindingTest(unittest.TestCase):
    TABLE = ("# Messaging\n\n| MDB | JNDI name | MQ queue | Notes |\n| --- | --- | --- | --- |\n"
             "| `PermitReceiver` | jms/PermitInQueue | TN.PERMIT.REQ | from traders |\n"
             "| Owner | Team | Contact | Phone |\n")

    def test_markdown_table_rows(self):
        self.assertEqual(found("markdown", self.TABLE), {
            ("entry_point", "PermitReceiver", "mdb documented in table (column MDB)", 5),
            ("queue", "jms/PermitInQueue", "JNDI name documented in table (column JNDI name)", 5),
            ("queue", "TN.PERMIT.REQ", "queue documented in table (column MQ queue)", 5)})

    def test_csv_sender_is_a_component_not_an_entry_point(self):
        csv_text = "Component,Destination JNDI,Queue\nsg.gov.tn.ReplySender,jms/Reply,TN.PERMIT.REPLY\n"
        got = {(t, v) for t, v, _, _ in found("csv", csv_text)}
        self.assertEqual(got, {("component", "sg.gov.tn.ReplySender"), ("queue", "jms/Reply"),
                               ("queue", "TN.PERMIT.REPLY")})

    def test_tables_without_bindings_are_ignored(self):
        self.assertEqual(found("markdown", "| Name | Role |\n| --- | --- |\n| Ann | Lead |\n"), set())


class LinkTest(unittest.TestCase):
    """The chain from a class in code to its queue, through whichever source records the binding."""

    def setUp(self):
        self.repo = Repo()
        self.repo.write("tn/src/sg/gov/tn/permit/PermitReceiver.java",
                        "package sg.gov.tn.permit;\npublic class PermitReceiver\n"
                        "    implements MessageDrivenBean, MessageListener {\n}\n")

    def tearDown(self):
        self.repo.close()

    def linked_queues(self):
        out = self.repo.evs("facts", "--type", "entry_point", "--match", "PermitReceiver",
                            "--path", "tn/*").stdout
        return [line.strip() for line in out.splitlines() if line.strip().startswith("->")]

    def test_documented_table_links_class_to_queues(self):
        self.repo.write("docs/messaging.md", DocumentedBindingTest.TABLE)
        self.repo.evs("index", "--quiet")
        links = self.linked_queues()
        self.assertTrue(any("jms/PermitInQueue" in link for link in links), links)
        self.assertTrue(any("TN.PERMIT.REQ" in link for link in links), links)

    def test_weblogic_descriptors_link_class_to_mq_queue(self):
        self.repo.write("deploy/ejb-jar.xml", EJB_JAR)
        self.repo.write("deploy/weblogic-ejb-jar.xml", WEBLOGIC_EJB_JAR)
        self.repo.write("deploy/tn-jms.xml", JMS_MODULE)
        self.repo.evs("index", "--quiet")
        links = self.linked_queues()
        self.assertTrue(any("deploy/weblogic-ejb-jar.xml:5  queue  jms/PermitInQueue" in link for link in links), links)
        self.assertTrue(any("TN.PERMIT.REQ" in link for link in links), links)


if __name__ == "__main__":
    unittest.main()
