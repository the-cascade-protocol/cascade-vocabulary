import re
import subprocess
from pathlib import Path

from contract import ROOT

SELF = Path(__file__).resolve().relative_to(ROOT.resolve()).as_posix()

POINTER = re.compile(r"decisions/(?!README\.md)|decision note|decision record|No note rules this", re.IGNORECASE)


def pointers():
    """Every line of a tracked file outside decisions/ that names a record, as `path:line:text`."""
    done = subprocess.run(
        ["git", "grep", "-n", "-I", "-i", "-E", "decisions/|decision note|decision record|No note rules this", "--", ".",
         ":!decisions/", f":!{SELF}", ":!tests/spec.json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert done.returncode in (0, 1), done.stderr
    return [line for line in done.stdout.splitlines() if POINTER.search(line.split(":", 2)[2])]


class TestChecksThatNoFilePointsAtARemovedDecisionRecord:
    """Checks that no file points at a removed decision record · tests/test_decision_pointers.py

    The decision notes are deleted. A tracked file outside decisions/ that still names one, says a rule has none, or links
    the pages that published them sends a reader to a page that is not there.
    """

    def test_has_no_tracked_file_outside_decisions_that_names_a_record(self):
        """has no tracked file outside decisions/ that names a record"""
        found = pointers()
        assert not found, f"{len(found)} lines:\n" + "\n".join(found)
