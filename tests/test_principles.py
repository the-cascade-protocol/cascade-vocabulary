import re

from rdflib.namespace import OWL, RDF

from contract import CASCADE, LAYOUT, QUERIES, ROOT, feature_documents
from ontologies import terms

TESTS = ROOT / "tests"
CLASSES_AND_PROPERTIES = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property)
NAMED = re.compile(r"(?:(?<![\w:])cascade:|https://ns\.cascadeprotocol\.org/cascade#)([A-Za-z]\w*)")
COMMENT = {".rq": "#", ".sql": "--"}


def listed(name):
    return {line.strip() for line in (TESTS / name).read_text(encoding="utf-8").splitlines() if line.strip()}


def a_query_without_its_comments(path):
    marker = COMMENT[path.suffix]
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith(marker))


def names_named():
    """The local names of the cascade terms a query, a kit's expected answers, an example or a file every runtime reads names."""
    texts = [a_query_without_its_comments(path) for path in sorted(QUERIES.rglob("*")) if path.suffix in COMMENT]
    texts += [path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("conformance/*/expected/*"))]
    texts += [path.read_text(encoding="utf-8") for path in [LAYOUT, *sorted(ROOT.glob("runtime/rule-list/*.ttl"))]]
    texts += [str(pickles) for _, _, pickles in feature_documents()]
    return {name for text in texts for name in NAMED.findall(text)}


def terms_nothing_names():
    declared = {subject for kind in CLASSES_AND_PROPERTIES for subject in terms().subjects(RDF.type, kind)
                if str(subject).startswith(str(CASCADE))}
    return {str(subject).removeprefix(str(CASCADE)) for subject in declared} - names_named()


def rules_without_an_example():
    """Each rule of the features, by the code its name begins with, with no scenario among its children."""
    return {child["rule"]["name"].split(". ")[0]
            for _, document, _ in feature_documents() for child in document["feature"]["children"]
            if "rule" in child and not any("scenario" in inner for inner in child["rule"]["children"])}


class TestPrinciplesTheSuiteHolds:
    """Principles the suite holds the vocabulary to · ontologies/cascade.ttl, queries/, conformance/*/expected/, runtime/*.feature

    A list beside this file names what breaks a principle today. A list may only shrink: a name that is not on it fails
    the principle, and a name that is on it and no longer breaks the principle fails the list.
    """

    def test_names_every_term_a_query_a_kits_expected_answers_or_an_example_names(self):
        """names every term a query, a kit's expected answers, an example or a file every runtime reads names

        A class or a property of `cascade#` is named when `cascade:Name` or its full IRI is written in a query under
        `queries/`, in a kit's `expected/`, in the text of an example, in `runtime/pod-layout.ttl` or in a file under
        `runtime/rule-list/`; a comment of a query, a shape and a rule's description do not name it. A term read through
        a variable is not seen. The terms nothing names are listed in `tests/terms_nothing_names.txt`.
        """
        assert sorted(terms_nothing_names()) == sorted(listed("terms_nothing_names.txt"))

    def test_gives_every_rule_an_example(self):
        """gives every rule of the features, the kits' included, an example

        A rule of a `.feature` file under `runtime/` or `conformance/` has a child that is an Example. The rules with none
        are listed in `tests/rules_without_an_example.txt` by the code their name begins with.
        """
        assert sorted(rules_without_an_example()) == sorted(listed("rules_without_an_example.txt"))
