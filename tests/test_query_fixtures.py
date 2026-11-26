import hashlib
import os
import pickle
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from time import perf_counter

import pytest
import rdflib
from rdflib import OWL, RDF, RDFS, XSD, Graph, URIRef

from contract import CASCADE, PROV, QUERIES, ROOT, built, derivations, named, query, questions
import engines
from engines import ENGINES, Oxigraph, Rdflib, bound_to_records, marked_groups
from manifests import Entry, entries, expected, failure, lens_name, row
from pods import ADDRESS, FIXTURES, built_once, every_fixture, on_its_worker

LENSES = sorted(named("lenses"))
JUDGMENT = "https://ns.cascadeprotocol.org/cascade#Judgment"
ASKED = {**questions(), **{f"matcher/{name}": relative for name, relative in named("matcher").items()}}


def entry_id(fixture, entry):
    """What a case's id says once of the fixture and its entry. Ignoring a leading `matcher-` and `the-`, an entry whose
    words run inside the fixture's is the fixture's name; a fixture whose words run inside the entry's is the entry's
    name, behind `matcher-` for a matcher fixture; any other pair is joined. No name is cut."""
    def words(name):
        return name.removeprefix("matcher-").removeprefix("the-").split("-")

    def runs_inside(inner, outer):
        return any(outer[start:start + len(inner)] == inner for start in range(len(outer) - len(inner) + 1))

    said, entered = words(fixture.name), words(entry.name)
    if runs_inside(entered, said):
        return fixture.name
    if runs_inside(said, entered):
        return f"matcher-{entry.name}" if fixture.name.startswith("matcher-") and not entry.name.startswith("matcher-") else entry.name
    return f"{fixture.name}-{entry.name}"


SLOW_ON_RDFLIB = ("matcher-same-variation-through-current-tables", "matcher-same-result-by-value-and-unit",
                  "matcher-same-product-code", "matcher-same-note-type-and-text")


def slow_on_rdflib(fixture):
    """Whether a case of the fixture takes seconds on rdflib, which evaluates a comparison once for each record it is
    bound to: the fixture's cases are each a part of its group, built again on the worker that draws one."""
    return fixture.name.startswith(SLOW_ON_RDFLIB)


ENTRIES = [on_its_worker(fixture, entry, id=entry_id(fixture, entry), says=f"{fixture.comment} {entry.comment}",
                         part=entry.name if slow_on_rdflib(fixture) else None)
           for fixture in FIXTURES for entry in entries(fixture.manifest)]


def listing_most_unlisted_queries_first():
    """The fixtures, each after the ones that list the most queries no fixture before it lists, then those that list
    none, the more a fixture lists first: a fixture lists a query to show what it gives."""
    listed = {}
    for case in ENTRIES:
        listed.setdefault(case.values[0], set()).add(Path(case.values[1].query).resolve())
    ordered, unlisted = [], {(QUERIES / relative).resolve() for relative in ASKED.values()}
    while unlisted:
        fixture = max(listed, key=lambda fixture: len(listed[fixture] & unlisted), default=None)
        if fixture is None or not listed[fixture] & unlisted:
            break
        ordered.append(fixture)
        unlisted -= listed.pop(fixture)
    return ordered + sorted((fixture for fixture in FIXTURES if fixture not in ordered),
                            key=lambda fixture: -len(listed.get(fixture, ())))


def lenses_that_differ(fixture):
    """Each lens whose derived state over the fixture no lens before it gives: under the others every query reads the
    same pod."""
    found = {}
    for lens in LENSES:
        found.setdefault(frozenset(built_once(fixture, "oxigraph", lens).derived), lens)
    return sorted(found.values())


def holds_a_judgment(fixture):
    """Whether the fixture holds a judgment. A lens writes cascade:countsUnderLens and nothing else
    (TestDerivationOrder in test_queries.py), so lenses differ only in which judgments count: over a
    pod with no judgment every lens adds the same triples, and every later step reads the same pod."""
    return built_once(fixture, "oxigraph", LENSES[0]).store.ask(f"ASK {{ ?j a <{JUDGMENT}> }}")


BOTH_ENGINES = (
    "every-row-names-its-sources", "medications-possibly-the-same", "every-reason-a-record-is-in-no-view",
    "my-reports-notes-and-documents", "matcher-same-business-identifier-and-test-code-within-one-organization-bound-per-side",
    "two-dispenses-from-a-retrieved-document-judged-the-same", "a-before-outranks-the-clocks", "a-clock-found-behind",
    "a-profiles-hospital-is-its-organizations-current-name", "a-table-revised-elsewhere-keeps-the-matcher-judgment",
    "allergies-view", "variant-classifications-agreement")
assert set(BOTH_ENGINES) <= {fixture.name for fixture in FIXTURES}


def steps_that_add(build):
    """Each derivation, lens and query that writes a view, that adds a triple to the build's derived state or makes a view
    file hold a subject of its own."""
    return {step for step, added in build.added_by_step.items() if added} | {
        built()[path] for path, triples in build.files.items()
        if any(subject != URIRef(ADDRESS + path) for subject, _, _ in triples)}


PREFIX = re.compile(r"PREFIX\s+(\w*):\s*<([^>]*)>")
PREFIXED = re.compile(r"(?<![\w<:/#])(\w*):(\w+)\b")


def iris_named(text):
    """The IRIs a query's text names, written in full or with one of its own prefixes."""
    prefixes = dict(PREFIX.findall(text))
    body = PREFIX.sub("", text)
    return {prefixes[prefix] + name for prefix, name in PREFIXED.findall(body) if prefix in prefixes} | set(
        re.findall(r"<([^<>\s]+)>", body))


def read_by_the_fixtures_own_queries(fixture):
    """The IRIs named by the queries the fixture's manifest lists from the fixture's own folder: its probes."""
    return set().union(*(iris_named(Path(entry.query).read_text(encoding="utf-8")) for entry in entries(fixture.manifest)
                         if entry.query is not None and fixture.folder in Path(entry.query).parents))


def steps_a_probe_reads(build, read):
    """Each derivation and lens that added a triple whose predicate, or class where it states one, is in `read`."""
    return {step for step, added in build.added_by_step.items()
            if any(str(predicate) in read or (predicate == RDF.type and str(found) in read)
                   for _, predicate, found in added)}


SYMMETRIC = sorted(Graph().parse(ROOT / "ontologies" / "cascade.ttl").subjects(RDF.type, OWL.SymmetricProperty))


SHOWN_AND_LEFT_OUT_ALIKE = """
    PREFIX cascade: <https://ns.cascadeprotocol.org/cascade#>
    SELECT ?record WHERE {
      ?record a cascade:Record .
      BIND (EXISTS { ?record cascade:inEntry [] } AS ?shown)
      BIND (EXISTS { ?record cascade:leftOutFor [] } AS ?leftOut)
      FILTER (?shown = ?leftOut)
    }"""


VOCABULARY = Graph().parse(ROOT / "ontologies" / "cascade.ttl")
ACTIVITIES = [PROV.Activity, *VOCABULARY.transitive_subjects(RDFS.subClassOf, PROV.Activity)]


def used_by_no_activity(store):
    kinds = " ".join(f"<{kind}>" for kind in dict.fromkeys(ACTIVITIES))
    return store.select(f"SELECT DISTINCT ?s WHERE {{ ?s <{PROV.used}> [] "
                        f"FILTER NOT EXISTS {{ VALUES ?kind {{ {kinds} }} ?s a ?kind }} }}")


MARKED = {name: relative for name, relative in named("matcher").items() if marked_groups(query(relative))}
CURRENT_VERSIONS = "SELECT DISTINCT ?record WHERE { ?record <http://purl.org/pav/hasCurrentVersion> [] }"


PERSONS_JUDGMENTS = """
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX cascade: <https://ns.cascadeprotocol.org/cascade#>
    SELECT ?judgment WHERE { ?judgment a cascade:Judgment ; prov:wasAttributedTo/a prov:Person }"""


MATCHER_FIXTURES = [on_its_worker(fixture, id=fixture.name) for fixture in FIXTURES if fixture.name.startswith("matcher-")]


def rows_of(store, text):
    return Counter(row(found) for found in store.select(text))


def every_other_current_record(store):
    return sorted(str(found["record"]) for found in store.select(CURRENT_VERSIONS))[::2]


class TestWhatEachQueryGives:
    """What each query gives over a small pod · tests/fixtures/*/manifest.ttl

    A fixture is a few Turtle files laid out as a pod, with a manifest of the rows that queries give over it. Each fixture
    shows one behaviour, and a runtime whose engine gives other rows over the same files has that behaviour wrong.
    """

    class TestGivenAQueryAFixturesManifestLists:
        """given a query that a fixture's manifest lists"""

        @pytest.mark.parametrize("fixture, entry", ENTRIES)
        def test_gives_the_rows_the_manifest_expects_on_each_engine(self, fixture, entry):
            """gives the rows the manifest expects, on each engine

            For each query a fixture's manifest lists, the fixture is built on Oxigraph and on rdflib under the entry's
            lens, the query is run on each, and its rows are compared with the entry's expected result; an engine that
            gives other rows fails. Where the query ends in an ORDER BY the rows are compared in the order the result
            lists them, the rows its keys tie as a set.
            """
            stores = {engine: built_once(fixture, engine, lens_name(entry.lens)).store for engine in sorted(ENGINES)}
            failed = {engine: why for engine, store in stores.items() if (why := failure(entry, store))}
            assert not failed, "\n\n".join(f"on {engine}:\n{why}" for engine, why in failed.items())

    class TestGivenAnImmunizationASecondSourceJoins:
        """given `a-second-source-joins-an-immunization`, its pod built with and without each original"""

        JOINS = next(fixture for fixture in FIXTURES if fixture.name == "a-second-source-joins-an-immunization")
        PORTAL, DOWNLOAD = URIRef("urn:x:mmrFromPortal"), URIRef("urn:x:mmrFromDownload")

        @staticmethod
        def entry_named_from(member):
            return URIRef(f"{ADDRESS}clinical/immunizations.ttl#{hashlib.sha256(str(member).encode()).hexdigest()}")

        def asked(self, question, record, without):
            store = built_once(self.JOINS, "oxigraph", LENSES[0], frozenset(without)).store
            return store.select(bound_to_records(query(questions()[question]), [str(record)]))

        def shows(self, record, *without):
            return {(row["record"], row["entry"]) for row in self.asked("record/Which entry shows it", record, without)}

        @pytest.mark.xdist_group(JOINS.name)
        def test_shows_the_first_record_in_the_entry_renamed_for_both_records_once_the_second_joins(self):
            """shows the first record, once the second source joins, in the entry renamed from the record that sorts first, which holds both"""
            before = self.shows(self.PORTAL, "download.ttl", "judgments.ttl")
            after = self.shows(self.PORTAL) | self.shows(self.DOWNLOAD)
            renamed = self.entry_named_from(self.DOWNLOAD)
            assert before == {(self.PORTAL, self.entry_named_from(self.PORTAL))}
            assert after == {(self.PORTAL, renamed), (self.DOWNLOAD, renamed)}

        @pytest.mark.xdist_group(JOINS.name)
        def test_shows_a_record_whose_original_was_removed_in_no_entry_and_gives_no_reason(self):
            """shows a record whose original was removed in no entry once the pod is rebuilt, and gives no reason it is in none

            So the pod no longer holds it, which a record hidden from every view, with its reason, is not.
            """
            removed = ("portal.ttl",)
            assert self.shows(self.PORTAL, *removed) == set()
            assert self.asked("record/Why it is in no view", self.PORTAL, removed) == []
            assert self.shows(self.DOWNLOAD, *removed) == {(self.DOWNLOAD, self.entry_named_from(self.DOWNLOAD))}

    class TestGivenTheFixturesTogether:
        def test_leaves_no_query_without_a_fixture_over_which_it_adds_a_triple_or_gives_a_row(self):
            """leaves no query without a fixture over which it adds a triple or gives a row

            Takes every derivation, lens, view and question or comparison, and strikes off each that, over some fixture,
            adds a triple to the derived state, makes a view file hold a subject of its own, or (under a lens that
            matters there) gives rows; any query left unstruck is never shown to do anything by a fixture. A fixture that
            holds no judgment is read under the first lens only, for every lens gives it one derived state, and a question
            is run only until some fixture strikes it off. The fixtures are taken in the order that reaches every query a
            manifest lists soonest, and no more are built once none is left.
            """
            quiet = {*derivations(LENSES[0]), *named("lenses").values(), *built().values(), *ASKED.values()}
            for fixture in listing_most_unlisted_queries_first():
                if not quiet:
                    break
                judged = holds_a_judgment(fixture)
                differing = lenses_that_differ(fixture) if judged else LENSES[:1]
                for lens in LENSES if judged else LENSES[:1]:
                    build = built_once(fixture, "oxigraph", lens)
                    quiet -= steps_that_add(build)
                    if lens in differing:
                        quiet -= {relative for relative in set(ASKED.values()) & quiet if build.store.gives_a_row(query(relative))}
            assert quiet == set()

        def test_leaves_no_derivation_or_lens_without_a_fixture_whose_own_query_reads_what_it_adds(self):
            """leaves no derivation or lens without a fixture whose own query reads what it adds

            Takes every derivation and lens, and strikes off each that, over some fixture, adds a triple whose predicate
            (or, for a type, whose class) is named by a query the fixture's manifest lists from its own folder, which
            pins that derivation's rows over that fixture; any left over is pinned only through the questions that read
            what it adds, so one that added a wrong statement no question reads would pass. A fixture that holds no
            judgment is read under the first lens only.
            """
            quiet = {*derivations(LENSES[0]), *named("lenses").values()}
            for fixture in FIXTURES:
                read = read_by_the_fixtures_own_queries(fixture)
                if not quiet or not read:
                    continue
                for lens in LENSES if holds_a_judgment(fixture) else LENSES[:1]:
                    quiet -= steps_a_probe_reads(built_once(fixture, "oxigraph", lens), read)
            assert quiet == set()


class TestDerivedStateOnTwoEngines:
    """Derived state two engines build alike · queries/derivations/, queries/lenses/, queries/views/

    A pod's derived state is what the derivations and a lens add to it, and the views are written from it. The suite builds
    every fixture on Oxigraph, and on rdflib under the lens of each entry its manifest lists; a few are built on both
    under each lens and compared in full, so a query that only one engine reads as written shows here.
    """

    class TestGivenTheFixturesChosenForBothEngines:
        def test_leaves_no_derivation_lens_or_view_that_adds_nothing_over_them(self):
            """leaves no derivation, lens or query that writes a view without a fixture chosen for both engines over which it adds a triple

            Takes every derivation, lens and query that writes a view, and strikes off each that, over some fixture chosen
            for both engines, adds a triple to the derived state or makes a view file hold a subject of its own, under
            every lens if the fixture holds a judgment and under the first otherwise; any left would be compared between
            the engines over a pod it does nothing to.
            """
            quiet = {*derivations(LENSES[0]), *named("lenses").values(), *built().values()}
            for fixture in FIXTURES:
                if fixture.name in BOTH_ENGINES:
                    for lens in LENSES if holds_a_judgment(fixture) else LENSES[:1]:
                        quiet -= steps_that_add(built_once(fixture, "oxigraph", lens))
            assert quiet == set()

    class TestGivenAnyFixture:
        @pytest.mark.parametrize("fixture", [on_its_worker(fixture, id=fixture.name) for fixture in FIXTURES
                                             if fixture.name in BOTH_ENGINES])
        def test_builds_the_same_derived_state_and_the_same_files_on_both_engines(self, fixture):
            """builds the same derived state and the same files on both engines

            Each of the few fixtures chosen for both engines is built on Oxigraph and on rdflib, under every lens if it
            holds a judgment and under the first otherwise; the triples each derivation adds, and the files written, are
            compared between the two builds. Every other fixture is built on both engines under the lens of each manifest
            entry, which compares the rows that entry pins.
            """
            judged = holds_a_judgment(fixture)
            for lens in LENSES if judged else LENSES[:1]:
                one, other = (built_once(fixture, engine, lens) for engine in sorted(ENGINES))
                assert one.added_by_step == other.added_by_step, lens
                assert one.files == other.files, lens

        @every_fixture
        def test_differs_between_the_lenses_only_when_the_pod_holds_a_judgment(self, fixture):
            """differs between the lenses only when the pod holds a judgment

            A fixture with no judgment must have one derived state under every lens, so the lenses that differ over it
            are the first lens alone.
            """
            assert holds_a_judgment(fixture) or lenses_that_differ(fixture) == LENSES[:1]

        @every_fixture
        def test_adds_only_triples_that_no_file_of_the_pod_states(self, fixture):
            """adds only triples that no file of the pod states

            For each lens, the triples the derivations add are compared with the triples of the fixture's own files: the
            added set is not empty, and shares no triple with them.
            """
            for lens in LENSES:
                build = built_once(fixture, "oxigraph", lens)
                files = set().union(*(build.store.triples(ADDRESS + path) for path in fixture.files()))
                assert build.derived and build.derived.isdisjoint(files), lens


class TestWhatIsTrueOfAnyPod:
    """What is true of any pod once its derivations have run · queries/derivations/, ontologies/cascade.ttl

    Some things hold of every pod, whatever it holds: a runtime or an app may rely on each without checking. They are
    asserted over every fixture, so a new fixture that breaks one fails.
    """

    class TestGivenAnyFixture:
        @every_fixture
        def test_holds_each_symmetric_property_both_ways(self, fixture):
            """holds each symmetric property both ways

            A runtime may then find what a record reaches through currentlySame by union-find, as an entry.
            """
            assert SYMMETRIC
            for lens in LENSES:
                store = built_once(fixture, "oxigraph", lens).store
                for predicate in SYMMETRIC:
                    one_way = f"SELECT ?a ?b WHERE {{ ?a <{predicate}> ?b FILTER NOT EXISTS {{ ?b <{predicate}> ?a }} }}"
                    assert store.select(one_way) == [], (lens, str(predicate))

        @every_fixture
        def test_leaves_a_record_out_of_every_view_exactly_when_a_derivation_recorded_a_reason(self, fixture):
            """leaves a record out of every view exactly when a derivation recorded a reason

            Under each lens, a record that is in a view (`cascade:inEntry`) and one that has a recorded reason to be
            left out (`cascade:leftOutFor`) are the same as each other: none has both or neither.
            """
            for lens in LENSES:
                assert built_once(fixture, "oxigraph", lens).store.select(SHOWN_AND_LEFT_OUT_ALIKE) == [], lens

        @every_fixture
        def test_reads_a_statements_member_not_in_the_pod_exactly_when_the_pod_states_nothing_of_it(self, fixture):
            """reads a statement's member as not in the pod exactly when the pod states nothing of it

            For each row of `record/Where each record a statement names is now`, under each lens that differs, the row
            reads "not in the pod" when every triple with the member as subject is one a derivation added, and "in no
            entry" when one is not, so a predicate a derivation comes to add about a member must join the query's list.
            It finds only a predicate that some fixture's absent member receives.
            """
            text = query(questions()["record/Where each record a statement names is now"])
            for lens in lenses_that_differ(fixture):
                build = built_once(fixture, "oxigraph", lens)
                added = {tuple(map(str, triple)) for triple in build.derived}
                for found in build.store.select(text):
                    outcome = str(found["outcome"])
                    if outcome not in ("not in the pod", "in no entry"):
                        continue
                    member = str(found["record"])
                    every = build.store.select(f"SELECT ?p ?o WHERE {{ {{ <{member}> ?p ?o }} "
                                               f"UNION {{ GRAPH ?g {{ <{member}> ?p ?o }} }} }}")
                    stated = {(member, str(each["p"]), str(each["o"])) for each in every} - added
                    assert bool(stated) == (outcome == "in no entry"), (lens, member, outcome, stated)

        @every_fixture
        def test_gives_each_derivation_the_same_answer_with_the_views_in_the_pod(self, fixture):
            """gives each derivation the same answer with the views in the pod

            The pod is built, which writes its views into it, and under each lens every derivation and the lens's own
            query is run again over it: each gives the answer it gave as it ran, as it does when it reads only
            statements and other derivations.
            """
            for lens in LENSES:
                build = built_once(fixture, "oxigraph", lens)
                assert [relative for relative, answer in build.answers.items()
                        if build.store.construct(query(relative)) != answer] == [], lens

        @every_fixture
        def test_holds_no_qualified_attribution(self, fixture):
            """holds no `prov:qualifiedAttribution`

            So no role sits on an attribution, which PROV does not allow: a role sits on the act that generated the
            document or judgment.
            """
            store = built_once(fixture, "oxigraph", LENSES[0]).store
            assert not store.ask(f"ASK {{ ?s <{PROV.qualifiedAttribution}> ?attribution }}")

        @every_fixture
        def test_states_prov_used_only_of_an_act(self, fixture):
            """states `prov:used` only of an act

            An entity says what it came from with prov:wasDerivedFrom: prov:used has an activity for its domain, and a
            subclass of prov:Activity is one.
            """
            assert used_by_no_activity(built_once(fixture, "oxigraph", LENSES[0]).store) == []

        @every_fixture
        def test_reads_a_persons_judgment_exactly_when_the_everyday_lens_counts_it(self, fixture):
            """reads a person's judgment in `derivations/revision-judgments.rq` exactly when the everyday lens counts it

            Each person-attributed judgment gets probe triples for three verdicts (erroneous, before, clock-discounted);
            the judgments `revision-judgments.rq` writes a result for are compared with those the everyday lens marks as
            counted, and must be the same set for each verdict.
            """
            store = ENGINES["oxigraph"]()
            for path in fixture.files():
                store.load(fixture.folder / path, ADDRESS + path)
            judgments = {row["judgment"] for row in store.select(PERSONS_JUDGMENTS)}
            probe = lambda judgment, role: URIRef(f"urn:probe:{role}:{judgment}")
            store.add({triple for judgment in judgments for triple in (
                (judgment, CASCADE.verdict, CASCADE.Erroneous), (judgment, PROV.hadMember, probe(judgment, "wrong")),
                (probe(judgment, "wrong"), RDF.type, CASCADE.Revision),
                (judgment, CASCADE.verdict, CASCADE.Before), (judgment, CASCADE.earlierMember, probe(judgment, "earlier")),
                (judgment, PROV.hadMember, probe(judgment, "later")),
                (judgment, CASCADE.verdict, CASCADE.ClockDiscounted), (judgment, PROV.hadMember, probe(judgment, "act")),
                (probe(judgment, "discounted"), PROV.wasGeneratedBy, probe(judgment, "act")),
                (probe(judgment, "discounted"), RDF.type, CASCADE.Revision))})
            read = store.construct(query("derivations/revision-judgments.rq"))
            counted = {judgment for judgment, _, _ in store.construct(query(named("lenses")["everyday"]))} & judgments
            assert {j for j in judgments if (probe(j, "wrong"), CASCADE.revisionJudgedErroneousBy, j) in read} == counted
            assert {j for j in judgments if (probe(j, "earlier"), CASCADE.judgedBefore, probe(j, "later")) in read} == counted
            assert {j for j in judgments if (probe(j, "discounted"), CASCADE.observationTimeDiscountedBy, j) in read} == counted


class TestMatcherComparisons:
    """Matcher comparisons a runtime binds to records · queries/matcher/, runtime/rule-list/"""

    class TestGivenAMatcherFixture:
        """given a fixture named `matcher-…`"""

        @pytest.mark.parametrize("fixture", MATCHER_FIXTURES)
        def test_gives_bound_in_the_groups_it_marks_the_rows_it_gives_unbound(self, fixture):
            """gives, bound in the groups it marks, the rows it gives unbound for the same records"""
            store = built_once(fixture, "oxigraph", LENSES[0]).store
            records = every_other_current_record(store)
            assert MARKED and records
            for name, relative in MARKED.items():
                text = query(relative)
                unbound = Counter(row(found) for found in store.select(text) if str(found["record"]) in records)
                assert rows_of(store, bound_to_records(text, records)) == unbound, name


class TestChecksOfTheFixtureTools:
    """Checks of the fixtures' own tools · tests/engines.py, tests/manifests.py

    The fixtures are built and compared by code in `tests/`. These cases show that code what it must catch.
    """

    class TestWarm:
        """`engines.warm()`"""

        @pytest.fixture(autouse=True)
        def a_store_of_its_own_and_a_run_outside_xdist(self, tmp_path, monkeypatch):
            monkeypatch.setattr(engines, "PARSES", tmp_path)
            monkeypatch.setattr(engines, "FAILED_READS", 0)
            monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
            monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)

        def test_is_not_delayed_by_a_file_a_killed_run_left_beside_a_parse(self):
            """is not delayed by a file a killed run left beside a query's parse"""
            text = "SELECT ?s WHERE { ?s ?p ?o }"
            stem = engines.stored(text).stem
            for leftover in (".lock", ".4242.part"):
                engines.stored(text).with_name(stem + leftover).write_bytes(b"")
            start = perf_counter()
            engines.warm([text], wait=5)
            assert engines.stored(text).is_file() and perf_counter() - start < 2

        def test_parses_the_queries_at_its_own_place_in_the_list_first_and_then_any_that_are_missing(self, monkeypatch):
            """parses first the queries at its own place in the list, as many places as there are workers, and then any no one has stored"""
            texts = sorted(f"SELECT ?s{n} WHERE {{ ?s ?p ?o }}" for n in range(6))
            parsed = []
            monkeypatch.setattr(engines, "parse", lambda text: parsed.append(text) or "tree")
            monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
            monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", "3")
            engines.warm(texts, wait=0)
            assert parsed == [*texts[1::3], *(text for text in texts if text not in texts[1::3])]

        def test_stores_a_query_whose_parse_raises_as_none_whatever_the_error(self, monkeypatch):
            """stores a query whose parse raises as none, whatever the error, and raises none itself"""
            def fails(text):
                raise RuntimeError(text)

            monkeypatch.setattr(engines, "parse", fails)
            text = "SELECT ?s WHERE { ?s ?p ?o }"
            engines.warm([text], wait=0)
            assert engines.stored(text).is_file() and engines.read_stored(text) is None

        def test_reads_no_parse_from_a_file_it_cannot_read(self):
            """reads no parse from a file it cannot read, or one a killed run left cut short, as if none were stored"""
            text = "SELECT ?s WHERE { ?s ?p ?o }"
            engines.stored(text).mkdir()
            assert engines.read_stored(text) is None
            engines.stored(text).rmdir()
            whole = pickle.dumps(engines.parse(text))
            for cut in (b"", whole[: len(whole) // 2], whole[:-1]):
                engines.stored(text).write_bytes(cut)
                assert engines.read_stored(text) is None, len(cut)

        def test_is_not_stopped_by_a_store_folder_removed_while_it_runs(self, monkeypatch):
            """is not stopped by a store folder another run removed while it ran, and stores the parse again"""
            texts = [f"SELECT ?s{n} WHERE {{ ?s ?p ?o }}" for n in range(2)]
            real = engines.parse

            def parse_after_the_folder_goes(text):
                shutil.rmtree(engines.PARSES, ignore_errors=True)
                return real(text)

            monkeypatch.setattr(engines, "parse", parse_after_the_folder_goes)
            engines.warm(texts, wait=0)
            monkeypatch.setattr(engines, "parse", real)
            engines.warm(texts, wait=0)
            assert all(engines.stored(text).is_file() for text in texts)

        @pytest.mark.parametrize("bad", [b"not a pickle", b"cnosuchmodule\nthing\n.", b"\x80\x04K"])
        def test_replaces_a_stored_file_that_does_not_read_with_a_good_one(self, bad):
            """replaces a stored file that does not read, whatever the error reading it raises, with a good one"""
            text = "SELECT ?s WHERE { ?s ?p ?o }"
            engines.stored(text).write_bytes(bad)
            engines.warm([text], wait=0)
            assert engines.stored(text).is_file() and engines.read_stored(text) is not None

        def test_warns_once_naming_the_store_when_more_than_a_few_stored_reads_fail(self):
            """warns once, naming the store, when more than a few stored reads fail in one process"""
            texts = [f"SELECT ?s{n} WHERE {{ ?s ?p ?o }}" for n in range(8)]
            for text in texts:
                engines.stored(text).write_bytes(b"cut")
            with pytest.warns(UserWarning, match=re.escape(str(engines.PARSES))) as warned:
                for text in texts:
                    assert engines.read_stored(text) is None
            assert len(warned) == 1

    class TestUseParseStore:
        """`engines.use_parse_store()`"""

        @pytest.fixture(autouse=True)
        def the_store_put_back(self, monkeypatch):
            monkeypatch.setattr(engines, "PARSES", engines.PARSES)

        def test_puts_the_store_in_a_folder_of_the_one_it_is_given_the_same_folder_each_time(self, tmp_path):
            """puts the store in a folder of the one it is given, the same folder each time"""
            engines.use_parse_store(tmp_path)
            first = engines.PARSES
            assert first.parent == tmp_path and first.is_dir() and first.name.startswith("parses-")
            engines.use_parse_store(tmp_path)
            assert engines.PARSES == first

        def test_puts_the_store_in_another_folder_when_the_version_of_rdflib_changes(self, tmp_path, monkeypatch):
            """puts the store in another folder when the version of rdflib changes"""
            engines.use_parse_store(tmp_path)
            first = engines.PARSES
            monkeypatch.setattr(rdflib, "__version__", rdflib.__version__ + ".other")
            engines.use_parse_store(tmp_path)
            assert engines.PARSES != first and engines.PARSES.parent == tmp_path

        def test_puts_the_store_in_another_folder_when_engines_py_changes(self, tmp_path, monkeypatch):
            """puts the store in another folder when engines.py, which rebuilds a parse, changes"""
            engines.use_parse_store(tmp_path)
            first = engines.PARSES
            changed = tmp_path / "engines.py"
            changed.write_bytes(Path(engines.__file__).read_bytes() + b"\n# changed\n")
            monkeypatch.setattr(engines, "__file__", str(changed))
            engines.use_parse_store(tmp_path)
            assert engines.PARSES != first and engines.PARSES.parent == tmp_path

        def test_removes_the_stores_of_other_keys_untouched_for_a_week_and_keeps_the_rest(self, tmp_path):
            """removes the folders of other keys under the one it is given whose newest file is over seven days old, and keeps its own, the newer ones and whatever is no store"""
            engines.use_parse_store(tmp_path)
            kept = engines.PARSES / "a.pickle"
            kept.write_bytes(b"kept")
            for name, days in (("parses-old", 8), ("parses-live", 1)):
                (tmp_path / name).mkdir()
                file = tmp_path / name / "b.pickle"
                file.write_bytes(b"other")
                when = time.time() - days * 86400
                os.utime(file, (when, when))
            (tmp_path / "parses-mixed").mkdir()
            (tmp_path / "parses-mixed" / "old.pickle").write_bytes(b"x")
            os.utime(tmp_path / "parses-mixed" / "old.pickle", (1, 1))
            (tmp_path / "parses-mixed" / "new.pickle").write_bytes(b"x")
            (tmp_path / "elsewhere").mkdir()
            engines.use_parse_store(tmp_path)
            assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
                ["elsewhere", engines.PARSES.name, "parses-live", "parses-mixed"])
            assert kept.read_bytes() == b"kept"

    class TestPrepared:
        """`engines.prepared()`"""

        def test_keeps_a_literal_as_written_when_the_text_was_parsed_first_by_parse_once(self):
            """keeps a literal as written when the query's text was parsed first through `parse_once()`"""
            text = "SELECT ?x { BIND(01 AS ?x) }"
            engines.parse_once(text)
            assert str(Rdflib().select(text)[0]["x"]) == "01"

    class TestGivesARow:
        """`Oxigraph.gives_a_row()`"""

        def test_is_true_of_a_select_with_a_row_and_false_of_one_with_none(self):
            """is true of a select that gives a row and false of one that gives none"""
            store = Oxigraph()
            store.add([(URIRef("urn:x:a"), RDF.type, CASCADE.Record)])
            assert store.gives_a_row(f"SELECT ?s WHERE {{ ?s a <{CASCADE.Record}> }}")
            assert not store.gives_a_row(f"SELECT ?s WHERE {{ ?s a <{CASCADE.Judgment}> }}")

    class TestUsedByNoActivity:
        """`used_by_no_activity()`"""

        def test_returns_nothing_for_an_act_typed_only_as_a_subclass_of_prov_activity(self):
            """returns nothing for an act typed only as a subclass of `prov:Activity`"""
            act, thing = URIRef("urn:cascade:act:1"), URIRef("urn:cascade:thing:1")
            store = Oxigraph()
            store.add([(act, RDF.type, CASCADE.MatcherRun), (act, PROV.used, thing)])
            assert used_by_no_activity(store) == []

        def test_returns_a_thing_that_uses_something_and_is_no_act(self):
            """returns a thing that uses something and is no act

            Given an act that uses a thing and that thing using the act in turn, `used_by_no_activity()` returns exactly
            one subject: the thing.
            """
            act, thing = URIRef("urn:cascade:act:1"), URIRef("urn:cascade:thing:1")
            store = Oxigraph()
            store.add([(act, RDF.type, CASCADE.MatcherRun), (act, PROV.used, thing), (thing, PROV.used, act)])
            assert len(used_by_no_activity(store)) == 1

    class TestLoadGraphs:
        """`Store.load_graphs()`"""

        def test_loads_a_trig_files_default_graph_and_its_named_graph_alike_on_each_engine(self, tmp_path):
            """loads a TriG file's default graph and its named graph alike on each engine, against one base"""
            path = tmp_path / "rows.trig"
            path.write_text("<a> <urn:x:b> <urn:x:c> . <g> { <urn:x:d> <urn:x:e> <f> . }", encoding="utf-8")
            loaded = {}
            for name, engine in ENGINES.items():
                store = engine()
                store.load_graphs(path, ADDRESS + "rows.trig")
                loaded[name] = (store.triples(), store.triples(ADDRESS + "g"))
            assert {name: [len(graph) for graph in graphs] for name, graphs in loaded.items()} == {name: [1, 1] for name in ENGINES}
            assert loaded["oxigraph"] == loaded["rdflib"]

    class TestExpected:
        """`manifests.expected()`"""

        TERMS = [
            ("<urn:x:a>", URIRef("urn:x:a")),
            ('"two words"', engines.literal("two words")),
            ('""', engines.literal("")),
            (f'"3"^^<{XSD.integer}>', engines.literal("3", XSD.integer)),
            (f'"007"^^<{XSD.integer}>', engines.literal("007", XSD.integer)),
            (f'"x"^^<{XSD.string}>', engines.literal("x")),
            ('"chat"@fr', engines.literal("chat", lang="fr")),
            ('"a\\tb\\nc \\"q\\" \\\\ \\u001F"', engines.literal('a\tb\nc "q" \\ \x1f')),
            ("", None),
        ]

        def test_reads_a_tsv_answer_as_its_variables_and_a_multiset_of_rows(self, tmp_path):
            """reads a TSV answer as its variables and the multiset of its rows, each term as written, an empty field as unbound"""
            answer = tmp_path / "answer.tsv"
            for field, term in self.TERMS:
                answer.write_text(f"?a\t?b\n{field}\t<urn:x:z>\n{field}\t<urn:x:z>\n", encoding="utf-8")
                found = {"a": term, "b": URIRef("urn:x:z")} if term is not None else {"b": URIRef("urn:x:z")}
                assert expected(answer) == ({"a", "b"}, Counter({row(found): 2})), field
            answer.write_text("?a\t?b\n", encoding="utf-8")
            assert expected(answer) == ({"a", "b"}, Counter())
            answer.write_text("?a\n\n<urn:x:a>\n", encoding="utf-8")
            assert expected(answer) == ({"a"}, Counter({row({}): 1, row({"a": URIRef("urn:x:a")}): 1}))

        def test_takes_no_term_it_cannot_match_exactly(self, tmp_path):
            """takes no blank node, no abbreviated number, no long-quoted string, no escape Turtle lacks, no short or
            long row, no missing final newline and no variable twice, which no comparison can match exactly"""
            answer = tmp_path / "answer.tsv"
            for field in ("_:b0", "1", '"""x"""', '"a\\qb"'):
                answer.write_text(f"?a\n{field}\n", encoding="utf-8")
                with pytest.raises(ValueError, match=f"holds {re.escape(field)}"):
                    expected(answer)
            for text, why in (("?a\t?b\n<urn:x:a>\n", "1 fields"), ("?a\n<urn:x:a>\t<urn:x:b>\n", "2 fields"),
                              ("?a\n<urn:x:a>", "newline"), ("?a\t?a\n<urn:x:a>\t<urn:x:b>\n", "once")):
                answer.write_text(text, encoding="utf-8", newline="\n")
                with pytest.raises(ValueError, match=why):
                    expected(answer)

    class TestFailure:
        """`manifests.failure()`"""

        def test_returns_a_sentence_naming_the_variables(self, tmp_path):
            """returns a sentence naming the variables for a query whose columns are not its result's"""
            query, result = tmp_path / "q.rq", tmp_path / "r.tsv"
            query.write_text("SELECT ?a WHERE { ?a ?b ?c }", encoding="utf-8")
            result.write_text("?z\n", encoding="utf-8")
            entry = Entry(iri="urn:x:e", name="e", types=frozenset(), lens=None, query=query, result=result)
            assert "variables" in (failure(entry, ENGINES["oxigraph"]()) or "")

        def test_returns_a_sentence_naming_the_rows_given_in_another_order_unless_the_keys_tie_them(self, tmp_path):
            """returns a sentence naming the rows given in another order where the query's ORDER BY keys put them in one, and none where they tie"""
            query, result = tmp_path / "q.rq", tmp_path / "r.tsv"
            query.write_text('SELECT ?a ?b WHERE { VALUES (?a ?b) { (1 "x") (2 "y") (2 "z") } } ORDER BY ?a', encoding="utf-8")
            entry = Entry(iri="urn:x:e", name="e", types=frozenset(), lens=None, query=query, result=result)
            one, two = f'"1"^^<{XSD.integer}>', f'"2"^^<{XSD.integer}>'

            def failed(*rows):
                result.write_text("".join(["?a\t?b\n", *(f"{a}\t\"{b}\"\n" for a, b in rows)]), encoding="utf-8", newline="\n")
                return failure(entry, ENGINES["oxigraph"]())
            assert failed((one, "x"), (two, "y"), (two, "z")) is None
            assert failed((one, "x"), (two, "z"), (two, "y")) is None
            assert "another order, from row 1" in failed((two, "y"), (one, "x"), (two, "z"))
            assert "missing" in failed((one, "x"), (two, "y"), (two, "w"))

    class TestQueryFixtureIds:
        """`entry_id()`"""

        def test_joins_no_two_names_when_one_contains_the_other_and_keeps_each_id_unique_and_under_120_characters(self):
            """joins no fixture name to an entry name when one contains the other, keeps each id under 120 characters, and gives no two cases one id"""
            def bare(name):
                return name.removeprefix("matcher-").removeprefix("the-")
            ids = [case.id for case in ENTRIES]
            joined = [case.id for case in ENTRIES
                      if case.id == f"{case.values[0].name}-{case.values[1].name}"
                      and (f"-{bare(case.values[1].name)}-" in f"-{bare(case.values[0].name)}-"
                           or f"-{bare(case.values[0].name)}-" in f"-{bare(case.values[1].name)}-")]
            assert not joined and not [i for i in ids if len(i) >= 120] and len(set(ids)) == len(ids)
