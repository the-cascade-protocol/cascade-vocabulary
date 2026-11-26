"""The W3C test manifests of the query fixtures and the shape cases: each entry's action and result, and what its query
gives over a store."""

import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS, XSD

import sql
from contract import QUERIES, ROOT, named
from engines import literal

MF = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-manifest#")
QT = Namespace("http://www.w3.org/2001/sw/DataAccess/tests/test-query#")
CTM = Namespace("https://ns.cascadeprotocol.org/test-manifest#")


@dataclass(frozen=True)
class Entry:
    iri: str
    name: str
    types: frozenset
    lens: Path | None
    query: Path | None
    result: Path | None
    records: tuple = ()
    comment: str = ""


def path(iri):
    """The local file an IRI the manifest gives names, or None."""
    if iri is None:
        return None
    parts = urlparse(str(iri))
    return Path(url2pathname(parts.path)) if parts.scheme == "file" else None


@cache
def entries(manifest):
    """Each entry the manifest at `manifest` lists, in its order."""
    graph = Graph().parse(Path(manifest), format="turtle")
    [head] = graph.subjects(RDF.type, MF.Manifest)
    found = []
    for entry in Collection(graph, graph.value(head, MF.entries)):
        action = graph.value(entry, MF.action)
        found.append(Entry(
            iri=str(entry), name=str(graph.value(entry, MF.name)), types=frozenset(graph.objects(entry, RDF.type)),
            lens=path(graph.value(action, CTM.lensQueryPath)), query=path(graph.value(action, QT.query)),
            result=path(graph.value(entry, MF.result)),
            records=tuple(sorted(str(record) for record in graph.objects(action, CTM.boundRecord))),
            comment=str(graph.value(entry, RDFS.comment) or "")))
    return found


@cache
def compared_beside(manifest):
    """Each query file, and each folder of queries as a path ending in a slash, that the manifest names by
    ctm:comparesSqlWithSparqlUnderEveryLens, relative to the repository's root."""
    graph = Graph().parse(Path(manifest), format="turtle")
    [head] = graph.subjects(RDF.type, MF.Manifest)
    return tuple(sorted(path(named).resolve().relative_to(ROOT.resolve()).as_posix() + "/" * str(named).endswith("/")
                        for named in graph.objects(head, CTM.comparesSqlWithSparqlUnderEveryLens)))


def lens_name(file):
    lenses = {(QUERIES / relative).resolve(): name for name, relative in named("lenses").items()}
    if file is None or Path(file).resolve() not in lenses:
        raise ValueError(f"{file} is no lens's query file")
    return lenses[Path(file).resolve()]


IRI = r'[^\x00-\x20<>"{}|^`\\]*'
TERM = re.compile(rf'<(?P<iri>{IRI})>'
                  r'|"(?P<text>(?:[^"\\\n\r]|\\.)*)"(?:@(?P<lang>[A-Za-z]+(?:-[A-Za-z0-9]+)*)|\^\^<(?P<datatype>' + IRI + r')>)?')
ESCAPE = re.compile(r"\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|(.))", re.DOTALL)
ECHAR = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}


def listed(result):
    """The variables, in the header's order, and the rows, in the file's order, that a SPARQL 1.1 Query Results TSV file
    holds: a header of `?variable`s, then a line for each row, a field for each variable, an empty field for one the row
    leaves unbound. A field is an IRI in angle brackets or a double-quoted string with `^^<datatype>` or `@language`; a
    blank node or an abbreviated number is refused, since no comparison can match it exactly."""
    lines = Path(result).read_text(encoding="utf-8").split("\n")
    if lines.pop() != "":
        raise ValueError(f"{result} does not end in a newline")
    header = lines.pop(0).split("\t")
    names = [field[1:] for field in header]
    if len(set(names)) != len(names) or not all(field.startswith("?") for field in header):
        raise ValueError(f"{result}: the first line must name each variable once, with a leading ?")
    rows = []
    for line in lines:
        fields = line.split("\t")
        if len(fields) != len(names):
            raise ValueError(f"{result}: a row has {len(fields)} fields, the header {len(names)}")
        rows.append({name: term(field) for name, field in zip(names, fields) if field})
    return names, rows


def expected(result):
    """The variables and the multiset of rows that `listed` reads from the file."""
    names, rows = listed(result)
    return set(names), Counter(row(each) for each in rows)


def unescaped(found, field):
    if found[3] in ECHAR:
        return ECHAR[found[3]]
    if found[3]:
        raise ValueError(f"an expected row holds {field}, whose backslash is no escape of Turtle")
    return chr(int(found[1] or found[2], 16))


def term(field):
    found = TERM.fullmatch(field)
    if found is None:
        raise ValueError(f"an expected row holds {field}, which no comparison can match exactly")
    if found["iri"] is not None:
        return URIRef(found["iri"])
    text = ESCAPE.sub(lambda escape: unescaped(escape, field), found["text"])
    if found["lang"]:
        return literal(text, lang=found["lang"])
    return literal(text, None if found["datatype"] in (None, str(XSD.string)) else URIRef(found["datatype"]))


def row(binding):
    return frozenset((name, node.n3()) for name, node in binding.items())


def as_term(node):
    """The sql.Term of an rdflib node, which `sql.compared` orders and ties."""
    if isinstance(node, URIRef):
        return sql.Term(sql.IRI, str(node))
    if isinstance(node, BNode):
        return sql.Term(sql.BLANK, str(node))
    if node.language:
        return sql.Term(sql.LITERAL, str(node), sql.LANG_STRING, node.language)
    return sql.Term(sql.LITERAL, str(node), str(node.datatype or XSD.string))


def failure(entry, store):
    """Why the entry's query over the store does not give its result, or None when it does: the same rows, and, where
    the query ends in an ORDER BY, in the order the result lists them; rows its keys tie may come either way round."""
    query = Path(entry.query).read_text(encoding="utf-8")
    variables, wanted = listed(entry.result)
    names, solutions = store.answer(query, entry.records)
    if set(variables) != set(names):
        return f"expected the variables {sorted(variables)}, found {sorted(names)}"

    def terms(binding):
        return tuple(as_term(binding[name]) if name in binding else None for name in names)
    lines = sql.compared(names, [terms(each) for each in wanted], [terms(each) for each in solutions],
                         sql.final_order(query, names))
    return "\n".join(lines) or None
