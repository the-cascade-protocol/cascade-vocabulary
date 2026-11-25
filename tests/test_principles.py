import re

from rdflib.namespace import OWL, RDF, RDFS

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


def local_name(term):
    return str(term).removeprefix(str(CASCADE)) if str(term).startswith(str(CASCADE)) else None


def terms_nothing_names():
    graph = terms()
    declarations = {subject for kind in CLASSES_AND_PROPERTIES for subject in graph.subjects(RDF.type, kind)}
    named = names_named() | {local_name(term) for subject, predicate, value in graph if subject not in declarations
                             for term in (predicate, value)}
    named |= {local_name(shape) for subject in declarations if local_name(subject) in named
              for shape in [*graph.objects(subject, RDFS.domain), *graph.objects(subject, RDFS.range)]}
    return {local_name(subject) for subject in declarations if local_name(subject)} - named


class TestPrinciplesTheSuiteHolds:
    """Principles the suite holds the vocabulary to · ontologies/cascade.ttl, queries/, conformance/*/expected/, runtime/*.feature

    A list beside this file names what breaks a principle today. A list may only shrink: a name that is not on it fails
    the principle, and a name that is on it and no longer breaks the principle fails the list.
    """

    def test_names_every_term_a_query_a_kits_expected_answers_or_an_example_names(self):
        """names every term a query, a kit's expected answers, an example or a file every runtime reads names

        A class or a property of `cascade#` is named when `cascade:Name` or its full IRI is written in a query under
        `queries/`, in a kit's `expected/`, in the text of an example, in `runtime/pod-layout.ttl` or in a file under
        `runtime/rule-list/`, when a statement of `ontologies/cascade.ttl` about something that is not itself a class or a
        property uses it, or when it is the domain or range of a property that is named; a comment of a query, a shape and
        a rule's description do not name it. A term read through a variable is not seen. The terms nothing names are
        listed in `tests/terms_nothing_names.txt`.
        """
        assert sorted(terms_nothing_names()) == sorted(listed("terms_nothing_names.txt"))
