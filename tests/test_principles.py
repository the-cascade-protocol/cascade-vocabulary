import re
from functools import cache

from gherkin.parser import Parser
from rdflib.namespace import OWL, RDF

from contract import CASCADE, FEATURES, QUERIES, ROOT
from ontologies import terms

TESTS = ROOT / "tests"
CLASSES_AND_PROPERTIES = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)
NAMED = re.compile(r"(?:(?<!\w)cascade:|https://ns\.cascadeprotocol\.org/cascade#)([A-Za-z]\w*)")
COMMENT = {".rq": "#", ".sql": "--"}


def listed(name):
    """The names on a list beside this file, one per line."""
    return {line.strip() for line in (TESTS / name).read_text(encoding="utf-8").splitlines() if line.strip()}


def shown(names):
    return "\n" + "\n".join(sorted(names))


def settles(offenders, name):
    """The messages that hold a list to the offenders: each offender is on it, and each name on it is still one."""
    on_the_list = listed(name)
    return (f"not on {name}:{shown(offenders - on_the_list)}" if offenders - on_the_list else "",
            f"on {name} but no longer one:{shown(on_the_list - offenders)}" if on_the_list - offenders else "")


def everything_a_scenario_says(node):
    """Every string in a parsed scenario: its name, its steps' texts, doc strings and table cells."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from everything_a_scenario_says(value)
    elif isinstance(node, list):
        for value in node:
            yield from everything_a_scenario_says(value)


def a_query_without_its_comments(path):
    marker = COMMENT[path.suffix]
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith(marker))


@cache
def names_read():
    """The local names of the cascade terms a query, a kit's expected answers or an example names."""
    texts = [a_query_without_its_comments(path) for path in sorted(QUERIES.rglob("*")) if path.suffix in COMMENT]
    texts += [path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("conformance/*/expected/*"))]
    for path in FEATURES:
        for child in Parser().parse(path.read_text(encoding="utf-8"))["feature"]["children"]:
            for scenario in [child["scenario"]] if "scenario" in child else [
                    inner["scenario"] for inner in child.get("rule", {}).get("children", []) if "scenario" in inner]:
                texts.extend(everything_a_scenario_says(scenario))
    return {name for text in texts for name in NAMED.findall(text)}


@cache
def terms_nothing_reads():
    declared = {subject for kind in CLASSES_AND_PROPERTIES for subject in terms().subjects(RDF.type, kind)
                if str(subject).startswith(str(CASCADE))}
    return {str(subject).removeprefix(str(CASCADE)) for subject in declared} - names_read()


@cache
def rules_without_an_example():
    """Each rule of runtime/*.feature with no Example of its own, by the code its name begins with."""
    return {rule["name"].split(". ")[0]
            for path in sorted(ROOT.glob("runtime/*.feature"))
            for child in Parser().parse(path.read_text(encoding="utf-8"))["feature"]["children"]
            if "rule" in child for rule in [child["rule"]]
            if not any(inner.get("scenario", {}).get("keyword") == "Example" for inner in rule["children"])}


class TestPrinciplesTheSuiteHolds:
    """Principles the suite holds the vocabulary to · ontologies/cascade.ttl, queries/, conformance/*/expected/, runtime/*.feature

    A list beside this file names what breaks a principle today. A list may only shrink: a name that is not on it fails
    the principle, and a name that is on it and no longer breaks the principle fails the list.
    """

    def test_names_every_term_a_query_a_kits_expected_answers_or_an_example_reads(self):
        """names every term a query, a kit's expected answers or an example reads

        A class or a property of `cascade#` is read when `cascade:Name` or its full IRI is written in a query under
        `queries/`, in a kit's `expected/`, or in the text of an example; a comment of a query, a shape and a rule's
        description do not read it. The terms nothing reads are listed in `tests/unread_terms.txt`.
        """
        unlisted, kept = settles(terms_nothing_reads(), "unread_terms.txt")
        assert not (unlisted or kept), "\n".join(filter(None, [unlisted, kept]))

    def test_gives_every_rule_an_example(self):
        """gives every rule of the runtime's features an example

        A rule of `runtime/*.feature` has a child that is an Example; a Background does not count. The rules with none are
        listed in `tests/rules_without_an_example.txt` by the code their name begins with.
        """
        unlisted, kept = settles(rules_without_an_example(), "rules_without_an_example.txt")
        assert not (unlisted or kept), "\n".join(filter(None, [unlisted, kept]))
