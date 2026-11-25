import re
import subprocess
from pathlib import Path

from contract import ROOT

SELF = Path(__file__).resolve().relative_to(ROOT.resolve()).as_posix()

FORMS = [
    ("a record's file", re.compile(r"decisions/(?!README\.md)[A-Za-z0-9_-]+\.md")),
    ("a rule said to have no record", re.compile(r"No note rules this")),
    ("the published records' address", re.compile(r"://\S*/decisions/")),
    ("the phrase for a record", re.compile(r"decision notes?", re.IGNORECASE)),
]


def pointers():
    """Every line of a tracked file outside decisions/ that names a record, as `path:line: form`."""
    done = subprocess.run(
        ["git", "grep", "-n", "-I", "-i", "-E", "decisions/|No note rules this|decision notes?", "--", ".", ":!decisions/", f":!{SELF}"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert done.returncode in (0, 1), done.stderr
    found = []
    for line in done.stdout.splitlines():
        where, number, text = line.split(":", 2)
        for form, pattern in FORMS:
            if pattern.search(text):
                found.append(f"{where}:{number}: {form}")
    return found


class TestChecksThatNoFilePointsAtARemovedDecisionRecord:
    """Checks that no file points at a removed decision record · tests/test_decision_pointers.py

    The records that were kept in decisions/ are gone, and nothing is checked in them; a tracked file outside decisions/
    that still names one, or says a rule has none, steers a reader to a page that is not there.
    """

    def test_no_tracked_file_outside_decisions_names_a_record(self):
        """no tracked file outside decisions/ names a record"""
        found = pointers()
        assert not found, f"{len(found)} lines:\n" + "\n".join(found)
