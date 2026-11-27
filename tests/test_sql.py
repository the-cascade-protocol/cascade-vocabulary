import hashlib
import json
import re
import sqlite3

import apsw
import pyoxigraph
import pytest

import sql
from contract import QUERIES, ROOT
from sql import compared, final_order

PINS = ROOT / "tests" / "sql-pins.json"
STRICTEST_SQLITE = "3.54.1"
SCOPE = [path.relative_to(ROOT).as_posix() for path in sorted(QUERIES.rglob("*.rq"))
         if not path.relative_to(QUERIES).as_posix().startswith("matcher/")]


def sql_beside(relative):
    return (ROOT / relative).with_suffix(".sql")


def ported():
    return [relative for relative in SCOPE if sql_beside(relative).is_file()]


def sql_text(relative):
    return sql_beside(relative).read_text(encoding="utf-8")


def screens():
    """The text of each view's `.sql`: the screens list questions read."""
    return [sql_text(relative) for relative in ported() if relative.startswith("queries/views/")]


WHOLE = re.compile(r"^SEARCH \w+ USING (?:COVERING )?INDEX (?:quad_pos \(p=\?|quad_osp \(o[<>]=?\?)(?: AND o[<>]=?\?)*\)$")


def whole_scans(run, text):
    """The b-trees of `term` and `quad`, each by its name, that a statement's bytecode reads from its first row or its
    last, in the order it opens them. EXPLAIN QUERY PLAN names a scan by the alias the statement gives the table, so
    `SCAN e` is no scan of `term` to a pattern over its detail; the cursor's root page is."""
    roots = dict(run("SELECT rootpage, name FROM sqlite_schema WHERE tbl_name IN ('term', 'quad') AND rootpage > 0"))
    reading, found = {}, []
    for row in run("EXPLAIN " + text):
        _, opcode, cursor, root, database = row[:5]
        if opcode in ("OpenRead", "ReopenIdx"):
            reading[cursor] = roots.get(root) if database == 0 else None
        elif opcode in ("Rewind", "Last") and reading.get(cursor):
            found.append(reading[cursor])
    return found


LOOP_OVER = re.compile(r"^(?:SCAN|SEARCH|CO-ROUTINE|MATERIALIZE) (\w+)\b")
STORAGE_ROOTS = re.compile(r"\bquad (\w+) ON \1\.p = k\.storage\s+CROSS JOIN term (\w+) ON \2\.id = \1\.o\b")


def storage_roots(text):
    """The aliases a statement's text gives the storage triples it loops over and the terms they name, the pod's few
    roots, for whole_searches."""
    return [alias for found in STORAGE_ROOTS.findall(text) for alias in found]


def whole_searches(plan, per_root=()):
    """The steps, of one statement's EXPLAIN QUERY PLAN given as (id, parent, detail) rows, that search `quad` by its
    predicate alone or by it and a range of its object, in a loop another loop runs once for each row of: not the first
    loop of its select, or inside a subquery run for each row of the statement's. The SCAN of a CTE of one constant
    row, or its CO-ROUTINE or MATERIALIZE, is no loop for this, nor is a `per_root` alias's loop, the pod's few
    storage roots, once each and only among the first loops of its select, nor is the MATERIALIZE of a CTE a select
    reads, which runs once before the select's first loop."""
    one_row = {detail.split()[1] for step, _, detail in plan if detail.startswith(("CO-ROUTINE ", "MATERIALIZE "))
               and any(parent == step and child == "SCAN CONSTANT ROW" for _, parent, child in plan)}
    leading, rooted, kept = {}, {}, []
    for row in plan:
        named = LOOP_OVER.match(row[2])
        if named and not row[2].startswith("SEARCH ") and named[1] in one_row:
            continue
        if (named and named[1] in per_root and leading.setdefault(row[1], True)
                and named[1] not in rooted.setdefault(row[1], set())):
            rooted[row[1]].add(named[1])
            continue
        leading[row[1]] = False
        kept.append(row)
    plan = kept
    firsts, by_id = {}, {step: (parent, detail) for step, parent, detail in plan}
    for step, parent, detail in plan:
        if not detail.startswith("MATERIALIZE "):
            firsts.setdefault(parent, step)
    found = []
    for step, parent, detail in plan:
        inside, above = firsts.get(parent) != step, parent
        while above in by_id:
            inside = inside or by_id[above][1].startswith("CORRELATED")
            above = by_id[above][0]
        if WHOLE.match(detail) and inside:
            found.append(detail)
    return found


def planning_pod(engine):
    """An empty pod on the engine, made by queries/statements.sql and each screen's tables part alone, as the function
    that runs a script, the one that runs a statement and each view's `.sql` by its parts."""
    if engine.startswith("apsw"):
        connection = apsw.Connection(":memory:")
        for name, function in sql.FUNCTIONS.items():
            connection.create_scalar_function(name, function, -1, deterministic=True)
        connection.execute(sql.SCHEMA.read_text(encoding="utf-8"))
        script = run = connection.execute
    else:
        connection = sql.connected()
        script, run = connection.executescript, connection.execute
    views = {relative: sql.parts(sql_text(relative)) for relative in ported() if relative.startswith("queries/views/")}
    for found in views.values():
        script(found["tables"])
    return script, run, views


def engine_ran(engine):
    """The SQLite an engine of the plan checks runs on, as text, after checking it is the one the engine names: the
    floor run is skipped where apsw is the strictest, the CI step that installs an older one runs it."""
    if engine == "apsw":
        assert apsw.sqlite_lib_version() == STRICTEST_SQLITE
    if engine == "apsw-floor":
        if apsw.sqlite_lib_version() == STRICTEST_SQLITE:
            pytest.skip("the floor run is the CI step that installs an older apsw")
        assert tuple(map(int, apsw.sqlite_lib_version().split("."))) >= sql.MINIMUM_VERSION
    return sqlite3.sqlite_version if engine == "sqlite3" else f"apsw {apsw.sqlite_lib_version()}"


def question_plans(engine):
    """The plan of each statement of each ported question's `.sql`, as (label, path, plan, scans): the label its path, or
    its path and the place of the statement in its prepare part; the plan the statement's EXPLAIN QUERY PLAN rows and
    scans the b-trees it scans, as screen_plans gives a statement's. The answer is planned after its prepare part has
    run on a pod as empty as theirs, asked for no page size after no key, and its plans do not depend on what the pod
    holds."""
    _, run, _ = planning_pod(engine)
    asking = lambda text: run(text, {"page_size": None, "after": None})
    found = []
    for relative in ported():
        if not relative.startswith("queries/questions/"):
            continue
        text = sql_text(relative)
        for place, each in enumerate(sql.prepared(text)):
            found.append((f"{relative}, prepare statement {place + 1}", relative,
                          [(row[0], row[1], row[3]) for row in run("EXPLAIN QUERY PLAN " + each)], whole_scans(run, each)))
            run(each)
        answer = sql.statement(text)
        found.append((relative, relative, [(row[0], row[1], row[3]) for row in asking("EXPLAIN QUERY PLAN " + answer)],
                      whole_scans(asking, answer)))
    return found


VIEW_STATEMENTS = re.compile(r"\bCREATE TEMP TABLE view_statements\b")
LOOP_STEP = re.compile(r"^(?:SCAN|SEARCH|CO-ROUTINE|MATERIALIZE) ")


def made_by_views(entries=400):
    """The rows of `view_statements` that a pod of `entries` entries gives, as the twelve views' triples make them: for each
    entry its member and lead, the node of its current values, whose member owns it, and six values of the node and six of
    the entry, each in a predicate of its own."""
    cascade = "<https://ns.cascadeprotocol.org/cascade#"
    rows = []
    for i in range(entries):
        entry, node, member = f"<urn:cascade:entry:{i:08d}>", f"_:n{i}", f"<urn:x:member-{i}>"
        rows += [("a", entry, cascade + "entryMember>", member), ("a", entry, cascade + "leadMember>", member),
                 ("a", entry, cascade + "memberCurrentValues>", node), ("a", node, cascade + "valuesOfMember>", member)]
        for k in range(6):
            rows += [("a", node, f"<urn:x:node-{k}>", f'"v{i}"'), ("a", entry, f"<urn:x:entry-{k}>", f'"w{i}"')]
    return rows


def unindexed_loops(plan):
    """The steps, of one statement's EXPLAIN QUERY PLAN given as (id, parent, detail) rows, that SCAN a table or a CTE in a
    loop another loop runs once for each row of: not the first loop of its select. A SQLite that joins a table it
    expects to be small with no index gives one."""
    firsts = {}
    for step, parent, detail in plan:
        if LOOP_STEP.match(detail) and not detail.startswith(("MATERIALIZE ", "CO-ROUTINE ")):
            firsts.setdefault(parent, step)
    return [detail for step, parent, detail in plan if detail.startswith("SCAN ") and firsts.get(parent) != step]


def answer_plans_over_rows(engine):
    """The plan of the answer of each question in parts, as (path, plan), after its prepare part has run on an empty pod
    with the rows of made_by_views put into its temporary table of the views' statements when it is made, so that
    what the prepare part does to that table's statistics is in the plan."""
    _, run, _ = planning_pod(engine)
    found = []
    for relative in ported():
        if not relative.startswith("queries/questions/") or "prepare" not in sql.parts(sql_text(relative)):
            continue
        text = sql_text(relative)
        for each in sql.prepared(text):
            run(each)
            if VIEW_STATEMENTS.search(each):
                for row in made_by_views():
                    run("INSERT INTO view_statements (address, s, p, o) VALUES (?, ?, ?, ?)", row)
        found.append((relative, [(row[0], row[1], row[3]) for row in
                                 run("EXPLAIN QUERY PLAN " + sql.statement(text), {"page_size": None, "after": None})]))
    return found


def screen_plans(engine):
    """The plan of each statement of each screen's fill and finish, and of each screen's triples, by the screen, the
    part and the statement's place in it, each as its EXPLAIN QUERY PLAN rows and the b-trees it scans, as whole_scans
    gives them; those of queries/labels.sql too, its fill between the screens' fills and finishes. The pod is empty, made
    by queries/statements.sql and each screen's tables part alone on the engine, each statement planned just before it
    runs; its plans do not depend on what the pod holds."""
    _, run, views = planning_pod(engine)

    def planned(text):
        return [(row[0], row[1], row[3]) for row in run("EXPLAIN QUERY PLAN " + text)], whole_scans(run, text)

    labels = sql.parts(sql_text("queries/labels.rq"))
    plans = {}
    for part in ("fill", "finish"):
        for relative, found in views.items():
            for place, text in enumerate(sql.statements(found[part])):
                plans[relative, part, place] = planned(text)
                run(text)
        if part == "fill":
            for place, text in enumerate(sql.statements(labels["fill"])):
                plans["queries/labels.sql", "fill", place] = planned(text)
                run(text)
    for relative, found in views.items():
        plans[relative, "triples", 0] = planned(found["triples"])
    plans["queries/labels.sql", "triples", 0] = planned(labels["triples"])
    return plans


def pins():
    return json.loads(PINS.read_text(encoding="utf-8"))


def pin_failures(pinned, texts):
    """Each ported `.rq`, of the texts by path, whose hash is not the one pinned for it, and each pin of a query with no
    `.sql`, as what to fix."""
    found = [f"{relative}: pinned {pinned.get(relative)}, its bytes hash to {digest}; check its .sql against it, then "
             f"pin {digest}" for relative, text in texts.items()
             if pinned.get(relative) != (digest := hashlib.sha256(text).hexdigest())]
    return found + [f"{relative}: pinned, but it has no .sql" for relative in sorted(set(pinned) - set(texts))]


class TestSqlBesideEachQuery:
    """SQL beside each query, held to the plans its statistics give and to a pin · queries/**/*.sql, queries/statements.sql, tests/sql-pins.json

    A runtime answers a query from SQLite through the `.sql` beside its `.rq`, over the tables queries/statements.sql
    makes. The runtime's own conformance check compares each `.sql`'s rows with its `.rq`'s, on the fixtures the manifests
    choose; what that comparison over small pods cannot show is held here: the plan of each screen's statements on an
    empty pod, the steps the labels' fill takes, and the pin of each `.rq`. A query outside queries/matcher/ with no
    `.sql` yet is named in tests/sql-unported.txt.
    """

    class TestGivenTheQueries:
        def test_pins_each_ported_rq_by_the_hash_its_sql_was_checked_against(self):
            """pins each ported `.rq` by the hash of the bytes its `.sql` was last checked against

            tests/sql-pins.json holds, for each `.rq` with a `.sql`, the SHA-256 of its bytes. A `.rq` whose bytes hash to
            another, so changed since its `.sql` was checked, fails, even where no fixture's rows tell the two apart; so
            does a pin of a query with no `.sql`.
            """
            assert pin_failures(pins(), {relative: (ROOT / relative).read_bytes() for relative in ported()}) == []

        @pytest.mark.parametrize("engine", ["sqlite3", "apsw", "apsw-floor"])
        def test_plans_each_screen_statement_from_the_shipped_statistics_with_no_whole_predicate_searched_in_a_loop(self, engine):
            """plans each screen statement, on the statistics the schema and the screens ship and no ANALYZE, with no scan of `quad` or `term` and no search of a whole predicate inside a loop

            SQLite plans a statement from the statistics it holds, and with none it plans as if every table held a million
            rows: one fill ran 79 s at 15,000 records against 0.14 s analyzed, by searching `quad` by its predicate alone
            once for each row of another table, and a screen table with none drove a statement from `term`. The pod here is
            empty and has had no ANALYZE; every statement of each screen's fill and finish, and its triples, and of queries/labels.sql, is planned on
            SQLite as the check ships it and on 3.54.1 through apsw. None reads `quad` or `term` from end to end, under
            whatever alias it names the table, or searches `quad` by a predicate alone, or by it and a range of an object,
            in a loop a surrounding loop runs once for each row of, or in a subquery run for each row of its statement's.
            """
            ran = engine_ran(engine)
            found = [f"{view} {part} #{place}: {detail}" for (view, part, place), (plan, scans) in screen_plans(engine).items()
                     for detail in [f"scans {name}" for name in scans] + whole_searches(plan)]
            assert found == [], f"on SQLite {ran}"

        def test_makes_the_labels_in_steps_that_grow_with_the_judgments_and_not_with_their_square(self):
            """makes the labels of judgments that one agent made, each file holding the agent's name, in steps that grow in proportion to them

            A name the agent has is held in the file of each judgment it made, the same statement once for each file. The
            labels' fill is run, after the screens', on a pod of 100 judgments and on one of 400, and the virtual machine's
            steps are counted: a fill that reads all of an agent's names for each judgment takes sixteen times the steps for
            four times the judgments, one that reads them once for each agent about four times.
            """
            cascade = "https://ns.cascadeprotocol.org/cascade#"
            prov = "http://www.w3.org/ns/prov#"

            def steps(judgments):
                store = pyoxigraph.Store()
                agent, label = pyoxigraph.NamedNode(cascade + "CascadeMatcher"), pyoxigraph.NamedNode(
                    "http://www.w3.org/2000/01/rdf-schema#label")
                for i in range(judgments):
                    judgment, file = pyoxigraph.NamedNode(f"urn:x:judgment:{i}"), pyoxigraph.NamedNode(f"urn:x:file:{i}")
                    for triple in [(judgment, pyoxigraph.NamedNode(sql.RDF_TYPE), pyoxigraph.NamedNode(cascade + "Judgment")),
                                   (judgment, pyoxigraph.NamedNode(prov + "wasAttributedTo"), agent),
                                   (judgment, pyoxigraph.NamedNode(cascade + "verdict"), pyoxigraph.NamedNode(cascade + "Same")),
                                   (agent, label, pyoxigraph.Literal("Cascade matcher"))]:
                        store.add(pyoxigraph.Quad(*triple, file))
                connection = sql.screened(sql.loaded(store, "test"), screens())
                counted = []
                connection.set_progress_handler(lambda: counted.append(1), 1000)
                for each in sql.statements(sql.parts(sql_text("queries/labels.rq"))["fill"]):
                    connection.execute(each)
                connection.set_progress_handler(None, 0)
                named = connection.execute("SELECT count(*) FROM label_named WHERE label LIKE '%Cascade matcher%'")
                assert named.fetchone()[0] == judgments
                return len(counted)

            few, many = steps(100), steps(400)
            assert many < 6 * few, f"{few} thousand steps for 100 judgments, {many} for 400"


class TestPlansOfTheQuestions:
    """Plans of each question's SQL · queries/questions/**/*.sql

    A question's `.sql` is planned as a screen's statements are: from the statistics the schema and the screens ship,
    on an empty pod, so that what holds at 15,000 records and not at three is found by its plan and not by a fixture.
    """

    @pytest.mark.parametrize("engine", ["sqlite3", "apsw", "apsw-floor"])
    def test_plans_each_question_from_the_shipped_statistics_with_no_whole_predicate_searched_in_a_loop(self, engine):
        """plans each question, on the statistics the schema and the screens ship and no ANALYZE, with no scan of `quad` or `term` and no search of a whole predicate inside a loop

        Each ported question's `.sql`, asked for no page size after no key, is planned on SQLite as the check ships it
        and on 3.54.1 and on the floor through apsw. None reads `quad` or `term` from end to end, or searches `quad` by a
        predicate alone, or by it and a range of an object, in a loop a surrounding loop runs once for each row of, or in
        a subquery run for each row of its statement's; a loop over the CTE `k` of one constant row, or over the storage
        roots a statement reads before it reads the files under them, is no loop.
        """
        ran = engine_ran(engine)
        found = [f"{label}: {detail}" for label, relative, plan, scans in question_plans(engine)
                 for detail in [f"scans {name}" for name in scans]
                 + whole_searches(plan, storage_roots(sql_text(relative)))]
        assert found == [], f"on SQLite {ran}"

    @pytest.mark.parametrize("engine", ["sqlite3", "apsw", "apsw-floor"])
    def test_plans_each_answer_that_reads_a_temporary_table_its_prepare_part_makes_with_the_table_holding_rows(self, engine):
        """plans each answer that reads a table its prepare part makes with that table holding rows, and no scan in a loop of a table or a CTE it reads

        A pod with no rows gives no statistic for a temporary table, so the plan of an answer over one says nothing of the
        plan at 15,000 records, where the table's own row counts decide whether the answer joins the CTEs it reads through
        an index or scans each once for each row of another. The rows a pod of 400 entries gives the views are put into the
        table `view_statements` when its prepare part makes it, and the answer, planned after the rest of that part has
        run, SCANs no table or CTE in a loop another loop runs once for each row of.
        """
        ran = engine_ran(engine)
        plans = answer_plans_over_rows(engine)
        assert [relative for relative, _ in plans] == ["queries/questions/entry/What it shows.rq"]
        found = [f"{relative}: {detail}" for relative, plan in plans for detail in unindexed_loops(plan)]
        assert found == [], f"on SQLite {ran}"


class TestTheSqlCheck:
    """Checks of the SQL check · tests/test_sql.py, tests/sql.py

    The parts of the checks that stay here are themselves checked: the search of a plan for a whole predicate in a
    loop, the scan of a table under whatever alias, the comparison of rows an ORDER BY ties, which the fixtures'
    pinned results are compared by, and the pin of a `.rq`.
    """

    JUDGMENTS = "queries/questions/pod/How many judgments count.rq"

    def test_reports_a_search_of_quad_by_a_predicate_alone_or_a_range_of_its_object_in_a_loop_and_no_other(self):
        """reports a search of `quad` by a predicate alone, or by it and a range of an object, in a loop, and no other

        A search of `quad` by its predicate alone, or by it and a range of its object, is reported as the second loop of
        a select, and in a subquery run for each row of its statement's, but not as the first loop, nor in a subquery
        run once; a search by an object alone or a graph alone, which the statistics give a handful of rows a value, or
        by a predicate, an object and a subject, is reported nowhere.
        """
        by_predicate = "SEARCH q USING COVERING INDEX quad_pos (p=?)"
        ranged = "SEARCH q USING COVERING INDEX quad_pos (p=? AND o>? AND o<?)"
        assert whole_searches([(2, 0, by_predicate), (6, 0, "SEARCH s USING INTEGER PRIMARY KEY (rowid=?)")]) == []
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, by_predicate)]) == [by_predicate]
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, "SEARCH q USING COVERING INDEX quad_pos (p=? AND o>?)")]) \
            == ["SEARCH q USING COVERING INDEX quad_pos (p=? AND o>?)"]
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, ranged)]) == [ranged]
        assert whole_searches([(2, 0, "SCAN scope"), (5, 0, "CORRELATED SCALAR SUBQUERY 3"), (8, 5, by_predicate)]) \
            == [by_predicate]
        assert whole_searches([(2, 0, "SCAN scope"), (5, 0, "SCALAR SUBQUERY 3"), (8, 5, by_predicate)]) == []
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, "SEARCH q USING COVERING INDEX quad_osp (o=?)"),
                               (9, 0, "SEARCH q USING COVERING INDEX quad_g (g=?)")]) == []
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, "SEARCH q USING COVERING INDEX quad_osp (o=? AND s=? AND p=?)")]) == []
        assert whole_searches([(2, 0, "SCAN k"), (6, 0, "SEARCH q USING COVERING INDEX quad_osp (o>? AND o<?)")]) \
            == ["SEARCH q USING COVERING INDEX quad_osp (o>? AND o<?)"]

    def test_leaves_a_loop_over_a_cte_of_one_constant_row_or_over_the_storage_roots_out_of_the_loops_it_reports(self):
        """leaves a loop over a CTE of one constant row, over the aliases given for the storage roots, and a CTE's MATERIALIZE out of the loops it reports

        A search by a predicate alone after `SCAN k`, where `k` is a CTE made of one constant row, is the first loop of its
        select, as it is after a loop over the roots a statement names, or after the MATERIALIZE of a CTE; after any
        other loop, and after a `k` that is no constant row, it is reported as ever, and so is a second whole search
        after the roots.
        """
        by_predicate = "SEARCH q USING COVERING INDEX quad_pos (p=?)"
        constant = [(2, 0, "CO-ROUTINE k"), (3, 2, "SCAN CONSTANT ROW"), (9, 0, "SCAN k")]
        assert whole_searches(constant + [(12, 0, by_predicate)]) == []
        assert whole_searches([(2, 0, "MATERIALIZE k"), (3, 2, "SCAN CONSTANT ROW"), (9, 6, "SCAN k"),
                               (12, 6, by_predicate)]) == []
        assert whole_searches(constant + [(12, 0, "SEARCH a USING COVERING INDEX quad_pos (p=?)"), (15, 0, by_predicate)]) \
            == [by_predicate]
        assert whole_searches([(2, 0, "CO-ROUTINE k"), (3, 2, "SCAN a"), (9, 0, "SCAN k"), (12, 0, by_predicate)]) \
            == [by_predicate]
        roots = [(9, 0, "SEARCH s USING COVERING INDEX quad_pos (p=?)"),
                 (10, 0, "SEARCH root USING INTEGER PRIMARY KEY (rowid=?)")]
        assert whole_searches(constant + roots + [(12, 0, by_predicate)], per_root=["s", "root"]) == []
        assert whole_searches(constant + roots + [(12, 0, by_predicate)]) == [by_predicate]
        assert whole_searches(constant + roots + [(12, 0, by_predicate), (15, 0, by_predicate)], per_root=["s", "root"]) \
            == [by_predicate]
        assert whole_searches([(2, 0, "MATERIALIZE n"), (3, 2, "SCAN a"), (12, 0, by_predicate)]) == []
        assert whole_searches([(2, 0, "MATERIALIZE n"), (3, 2, "SCAN a"), (9, 0, "SCAN n"), (12, 0, by_predicate)]) \
            == [by_predicate]
        typed = (8, 0, "SEARCH t USING COVERING INDEX quad_pos (p=?)")
        again = (15, 0, "SEARCH s USING COVERING INDEX quad_pos (p=?)")
        assert whole_searches(constant + [typed] + roots, per_root=["s", "root"]) == [roots[0][2]]
        assert whole_searches(constant + [typed, (7, 0, "SEARCH file USING INTEGER PRIMARY KEY (rowid=?)")] + roots,
                              per_root=["s", "root"]) == [roots[0][2]]
        assert whole_searches(constant + roots + [(12, 0, by_predicate), again], per_root=["s", "root"]) == [again[2]]
        assert whole_searches(constant + [(12, 0, "SEARCH a USING COVERING INDEX quad_pos (p=?)"),
                                          (15, 0, "SEARCH k USING COVERING INDEX quad_pos (p=?)")])             == ["SEARCH k USING COVERING INDEX quad_pos (p=?)"]
        assert storage_roots("FROM k CROSS JOIN quad s ON s.p = k.storage\n    CROSS JOIN term root ON root.id = s.o AND "
                             "root.kind <> 1 CROSS JOIN quad t ON t.p = k.type") == ["s", "root"]
        assert storage_roots("FROM k CROSS JOIN quad s ON s.p = k.storage CROSS JOIN quad t ON t.p = k.type") == []

    def test_reports_a_scan_of_quad_or_term_under_whatever_alias_the_statement_names_it_by(self):
        """reports a scan of `quad` or `term` under whatever alias the statement names it by, and no search of either

        The plan of `SELECT e.nt FROM term e` names its scan `SCAN e`, so a pattern over the plan's detail takes it for a
        scan of no table of the pod's; the bytecode's cursor on the table's root page, rewound, is a scan under any name.
        A search by the table's key, and a scan of a table that is neither, are not reported.
        """
        connection = sql.connected()
        connection.execute("CREATE TABLE other (x INTEGER)")
        for text, alias in (("SELECT e.nt FROM term e", "e"), ("SELECT p.s FROM quad p", "p"),
                            ("SELECT k.x FROM other k CROSS JOIN term t", "t")):
            assert any(row[3].startswith(f"SCAN {alias}") for row in connection.execute("EXPLAIN QUERY PLAN " + text))
            assert whole_scans(connection.execute, text) != [], text
        for text in ("SELECT t.id FROM term t WHERE t.nt = 'x'", "SELECT q.o FROM quad q WHERE q.s = 1 AND q.p = 2",
                     "SELECT x FROM other"):
            assert whole_scans(connection.execute, text) == [], text

    def test_compares_rows_an_order_by_ties_as_a_multiset_and_the_runs_it_orders_in_order(self):
        """compares rows an ORDER BY ties as a multiset, and the runs of rows it orders in their order

        Rows ordered by a dateTime pass in either order where SPARQL's `<` does not order them, a value with no zone
        and one with a zone within fourteen hours of it, and where they hold one term; rows it does order fail turned
        round, naming the row. A condition ordering by the value's STR, or a SUBSTR of it, orders by that text, so
        rows whose texts differ are ordered, and rows whose texts are one are ordered by the next condition. Each
        condition of the ORDER BY gives a key of the columns whose first bound value it orders by: one projected
        variable, or a COALESCE of them, alone or in an expression; a condition that is neither is refused by name.
        """
        def at(value):
            return (sql.Term(sql.LITERAL, value, sql.XSD + "dateTime"),)
        unzoned, zoned, later = at("2024-01-01T10:00:00"), at("2024-01-01T05:00:00-08:00"), at("2024-01-03T00:00:00Z")
        term = [((0,), None)]
        assert compared(["t"], [unzoned, zoned, later], [zoned, unzoned, later], term) == []
        assert compared(["t"], [later, later], [later, later], term) == []
        assert compared(["t"], [unzoned, later], [unzoned, later], term) == []
        assert compared(["t"], [unzoned, later], [later, unzoned], term) == [
            f"the same rows in another order, from row 1: expected ?t={unzoned[0]}, found ?t={later[0]}"]
        assert compared(["t"], [zoned, unzoned], [unzoned, zoned], [((0,), (1, None, False))]) == [
            f"the same rows in another order, from row 1: expected ?t={zoned[0]}, found ?t={unzoned[0]}"]
        day = (1, 10, True)
        assert compared(["t", "u"], [(unzoned[0], zoned[0]), (zoned[0], unzoned[0])],
                        [(zoned[0], unzoned[0]), (unzoned[0], zoned[0])], [((0,), day)]) == []
        assert compared(["t", "u"], [(unzoned[0], unzoned[0]), (zoned[0], zoned[0])],
                        [(zoned[0], zoned[0]), (unzoned[0], unzoned[0])], [((0,), day), ((1,), (1, None, False))]) != []
        first_bound = [((0, 1), day), ((0, 1), (1, None, True))]
        assert compared(["t", "u"], [(None, later[0]), (unzoned[0], zoned[0])], [(unzoned[0], zoned[0]), (None, later[0])],
                        first_bound) != []
        assert compared(["t", "u"], [(None, later[0]), (unzoned[0], zoned[0])], [(None, later[0]), (unzoned[0], zoned[0])],
                        first_bound) == []
        assert final_order("SELECT ?a ?b ?c WHERE { } ORDER BY DESC(?b) ?a STR(?c) ?c", ["a", "b", "c"]) == [
            ((1,), None), ((0,), None), ((2,), (1, None, False)), ((2,), None)]
        assert final_order('SELECT ?a ?b WHERE { } ORDER BY DESC(COALESCE(SUBSTR(STR(?a), 1, 10), "")) ?b',
                           ["a", "b"]) == [((0,), (1, 10, True)), ((1,), None)]
        assert final_order('SELECT ?a ?b WHERE { } ORDER BY DESC(COALESCE(SUBSTR(STR(COALESCE(?a, ?b)), 1, 10), ""))',
                           ["a", "b"]) == [((0, 1), (1, 10, True))]
        assert final_order("SELECT ?a WHERE { } GROUP BY ?a", ["a"]) is None
        for text in ("CONCAT(?a, ?b) ?a", "?z ?a", "?a COALESCE(?a, ?z)", "COALESCE(?a, ?b, 1)", "?a 1"):
            with pytest.raises(ValueError, match="ORDER BY condition"):
                final_order(f"SELECT ?a ?b WHERE {{ }} ORDER BY {text}", ["a", "b"])

    def test_reports_a_ported_rq_whose_bytes_changed_without_its_pin(self):
        """reports a ported `.rq` whose bytes changed since its pin, with the hash to pin once its `.sql` is checked

        The bytes of `How many judgments count.rq`, with a comment added, are checked against tests/sql-pins.json; the
        check names the query and the new hash.
        """
        changed = (ROOT / self.JUDGMENTS).read_bytes() + b"# changed\n"
        digest = hashlib.sha256(changed).hexdigest()
        found = pin_failures({self.JUDGMENTS: pins()[self.JUDGMENTS]}, {self.JUDGMENTS: changed})
        assert len(found) == 1 and found[0].startswith(f"{self.JUDGMENTS}: ") and digest in found[0]
