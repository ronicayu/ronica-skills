#!/usr/bin/env python3
"""Run the agentic-team tests in parallel worker processes, with the same result as the serial run.

    python3.11 plugins/agentic-team/tests/run_parallel.py [-j N] [-k PATTERN] [--timeout S] [TEST ...]

It finds the tests as `python3.11 -m unittest discover -s plugins/agentic-team/tests` does, then hands them one
at a time to `-j` worker processes (default: the number of CPUs). A worker takes the next test when it is free, so
one slow test does not hold up a fixed slice. Longest tests first: the time of each test goes to `.durations.json`
beside this file (git-ignored) after every run. A test that kills its worker, or runs longer than --timeout
seconds, is reported as an error and the run goes on. The exit code is 0 only when every test passed.

TEST is a module, a class, a test (dotted, as for unittest) or a path to a test file; with none, all tests run.
-k PATTERN works as for unittest: a test runs when its name holds PATTERN (a pattern with `*` is a glob); repeat it
for more than one. `-j 1` runs the tests in a single worker, in the order of the serial run when there is no
.durations.json file.

Every test builds its own temporary folders, so tests do not share state across processes (see the README). The
tests start no class or module fixtures, so each test is loaded and run alone.
"""

import argparse
import json
import multiprocessing
import multiprocessing.connection
import os
import signal
import sys
import tempfile
import time
import traceback
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TIMEOUT = 900  # seconds one test may run; the slowest test takes well under a minute
LINE = "=" * 70
THIN = "-" * 70


def load(start, names, patterns):
    """The tests to run: (list of ids in discovery order, list of tests that failed to import)."""
    sys.path.insert(0, start)  # discover does this too; a test named on the command line needs it
    loader = unittest.TestLoader()
    if patterns:
        loader.testNamePatterns = [p if "*" in p else f"*{p}*" for p in patterns]
    if names:
        suite = unittest.TestSuite()
        for name in names:
            if name.endswith(".py"):  # a test file, from the current folder or from the tests folder
                path = os.path.abspath(name) if os.path.exists(name) else os.path.join(start, name)
                name = os.path.splitext(os.path.relpath(path, start))[0].replace(os.sep, ".")
            suite.addTests(loader.loadTestsFromName(name))
    else:
        suite = loader.discover(start)  # the same start directory and pattern as `unittest discover -s tests`
    ids, broken = [], []

    def walk(item):
        if isinstance(item, unittest.TestSuite):
            for sub in item:
                walk(sub)
        elif type(item).__module__ == "unittest.loader" and type(item).__name__ == "_FailedTest":
            broken.append(item)
        else:
            ids.append(item.id())

    walk(suite)
    return ids, broken


def execute(test):
    """Run one test (or one suite) and return what happened, as plain data that crosses a process boundary."""
    result = unittest.TestResult()
    result.buffer = True  # the output of a test that passes is dropped, as with `unittest -b`
    started = time.perf_counter()
    try:
        test.run(result)
    except BaseException:  # a test that ends the interpreter's flow (SystemExit) is an error of that test only
        result.errors.append((test, traceback.format_exc()))
    seconds = time.perf_counter() - started
    return {
        "run": result.testsRun,
        "seconds": seconds,
        "failures": [(str(t), tb) for t, tb in result.failures],
        "errors": [(str(t), tb) for t, tb in result.errors],
        "skipped": [(str(t), why) for t, why in result.skipped],
        "xfail": [(str(t), tb) for t, tb in result.expectedFailures],
        "xpass": [str(t) for t in result.unexpectedSuccesses],
    }


def worker(conn):
    """A worker process: say it is ready, then run each test it is sent and send back the outcome, until None."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the parent stops its workers
    loader = unittest.TestLoader()
    conn.send(("ready", None))
    while True:
        test_id = conn.recv()
        if test_id is None:
            return
        conn.send(("done", (test_id, execute(loader.loadTestsFromName(test_id)))))


class Slot:
    """One worker process, its pipe and the test it runs now."""

    def __init__(self, context):
        self.conn, child = context.Pipe()
        self.process = context.Process(target=worker, args=(child,), daemon=True)
        self.process.start()
        child.close()
        self.test = None
        self.since = 0.0
        self.stopping = False  # told to exit: it holds no test and is not replaced

    def close(self):
        if self.process.is_alive():
            self.process.kill()
        self.process.join(timeout=5)
        self.conn.close()


def error_record(text, seconds):
    return {"run": 1, "seconds": seconds, "failures": [], "errors": [("", text)], "skipped": [], "xfail": [], "xpass": []}


def run_all(ids, jobs, timeout, on_done):
    """Run the ids in `jobs` workers; call on_done(test_id, data) as each finishes."""
    context = multiprocessing.get_context("spawn")
    queue = list(ids)
    slots = [Slot(context) for _ in range(jobs)]
    waiting = len(ids)

    def lost(slot, text):
        """The test of a worker that died or ran too long is an error; the worker is replaced while tests remain."""
        nonlocal waiting
        test_id, seconds = slot.test, time.monotonic() - slot.since
        data = error_record(text, seconds)
        data["errors"] = [(f"{test_id}", text)]
        on_done(test_id, data)
        waiting -= 1
        slot.close()
        slots.remove(slot)
        if queue:
            slots.append(Slot(context))

    try:
        while waiting:
            by_wait = {}
            for slot in slots:
                if not slot.stopping:  # a worker told to exit has nothing more to say
                    by_wait[slot.conn] = slot
                    by_wait[slot.process.sentinel] = slot
            for item in multiprocessing.connection.wait(list(by_wait), timeout=1.0):
                slot = by_wait[item]
                if slot not in slots:
                    continue
                message = None
                try:
                    if slot.conn.poll():
                        message = slot.conn.recv()
                except (EOFError, OSError):
                    pass
                if message is None:
                    if slot.process.is_alive():
                        continue
                    slot.process.join()
                    if slot.test is not None:
                        lost(slot, f"the worker process died (exit code {slot.process.exitcode}) while it ran this test\n")
                    else:  # it died before its first test
                        slot.close()
                        slots.remove(slot)
                        if queue:
                            slots.append(Slot(context))
                    continue
                if message[0] == "done":
                    on_done(*message[1])
                    waiting -= 1
                    slot.test = None
                if queue:
                    slot.test, slot.since = queue.pop(0), time.monotonic()
                    slot.conn.send(slot.test)
                else:
                    slot.stopping = True
                    slot.conn.send(None)
            for slot in list(slots):
                if slot.test is not None and time.monotonic() - slot.since > timeout:
                    slot.process.kill()
                    slot.process.join()
                    lost(slot, f"the test ran longer than {timeout:g} s and was stopped\n")
            if waiting and all(slot.stopping for slot in slots):
                raise RuntimeError("no worker is left but tests remain")
    finally:
        for slot in slots:
            slot.close()


def read_durations(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def write_durations(path, old, new, keep):
    """Merge the times of this run into the file. `keep` is the set of ids that exist, or None to keep all."""
    merged = dict(old)
    merged.update(new)
    if keep is not None:
        merged = {k: v for k, v in merged.items() if k in keep}
    try:
        fd, tmp = tempfile.mkstemp(prefix=".durations.", suffix=".tmp", dir=os.path.dirname(path))
        with os.fdopen(fd, "w") as fh:
            json.dump({k: round(v, 3) for k, v in sorted(merged.items())}, fh, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass  # the file is only a hint for the order


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the agentic-team tests in parallel.")
    parser.add_argument("tests", nargs="*", help="module, class, test or test file to run (default: all)")
    parser.add_argument("-j", "--jobs", type=int, default=0, help="worker processes (default: the number of CPUs)")
    parser.add_argument("-k", dest="patterns", action="append", default=[], metavar="PATTERN",
                        help="run only tests whose name holds PATTERN (as for unittest)")
    parser.add_argument("--start-dir", default=HERE, help="where the tests are (default: this folder)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds one test may run")
    args = parser.parse_args(argv)
    if args.jobs < 0:
        parser.error("-j must not be negative")

    start = os.path.abspath(args.start_dir)
    durations = os.path.join(start, ".durations.json")
    ids, broken = load(start, args.tests, args.patterns)
    old = read_durations(durations)
    order = {test_id: index for index, test_id in enumerate(ids)}
    # unknown tests first (in discovery order), then the known ones, longest first
    ids.sort(key=lambda i: (i in old, -old.get(i, 0.0), order[i]))

    total = {"run": 0, "failures": [], "errors": [], "skipped": [], "xfail": [], "xpass": []}
    times = {}

    def on_done(test_id, data):
        total["run"] += data["run"]
        for key in ("failures", "errors", "skipped", "xfail", "xpass"):
            total[key] += data[key]
        times[test_id] = data["seconds"]
        mark = ("E" if data["errors"] else "F" if data["failures"] else "x" if data["xfail"]
                else "u" if data["xpass"] else "s" if data["skipped"] else ".")
        sys.stderr.write(mark)
        sys.stderr.flush()

    started = time.perf_counter()
    for test in broken:  # a module that does not import: the error of the import, as unittest reports it
        data = execute(test)
        total["run"] += data["run"]
        total["errors"] += data["errors"]
        total["failures"] += data["failures"]
        sys.stderr.write("E")
    jobs = max(1, min(args.jobs or os.cpu_count() or 1, len(ids) or 1))
    try:
        if ids:
            run_all(ids, jobs, args.timeout, on_done)
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130
    elapsed = time.perf_counter() - started

    stream = sys.stderr
    stream.write("\n")
    for flavour, key in (("ERROR", "errors"), ("FAIL", "failures")):
        for description, text in sorted(total[key]):
            stream.write(f"{LINE}\n{flavour}: {description}\n{THIN}\n{text}\n")
    stream.write(f"{THIN}\nRan {total['run']} test{'s' if total['run'] != 1 else ''} in {elapsed:.3f}s (-j {jobs})\n\n")
    infos = []
    for label, key in (("failures", "failures"), ("errors", "errors"), ("skipped", "skipped"),
                       ("expected failures", "xfail"), ("unexpected successes", "xpass")):
        if total[key]:
            infos.append(f"{label}={len(total[key])}")
    success = not (total["failures"] or total["errors"] or total["xpass"])  # as TestResult.wasSuccessful
    stream.write(("OK" if success else "FAILED") + (f" ({', '.join(infos)})" if infos else "") + "\n")
    stream.write("\n10 slowest tests:\n")
    for test_id, seconds in sorted(times.items(), key=lambda kv: -kv[1])[:10]:
        stream.write(f"  {seconds:8.2f}s  {test_id}\n")
    stream.flush()

    write_durations(durations, old, times, None if args.tests or args.patterns else set(ids))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
