# Contributing to cascade-vocabulary

Thank you for helping. This repository holds the contract a Cascade pod is built and read by: the terms and shapes,
the standard queries, the runtime rules, and the conformance kits. [`README.md`](README.md) names the parts,
[`PRINCIPLES.md`](PRINCIPLES.md) says what a design here is judged by, and [`CLAUDE.md`](CLAUDE.md) lists the few rules
no check catches. Read both before you propose a new term, query or fixture.

Report a security problem privately, by email to contact@cascadeprotocol.org, never in a public issue.

## Set up

You need Python 3.12 and git.

```sh
git clone git@github.com:<you>/cascade-vocabulary.git
cd cascade-vocabulary
python3 -m pip install -r requirements.txt
```

## Run the tests

This is the command CI runs:

```sh
python3 -m pytest -n auto --dist loadgroup
```

While you work, run only what you touched: a file, or `-k <words from a test name>`. A change to a class, a shape or a
fixture also runs the test files that go over every fixture, `tests/test_shapes.py` among them.

A `.sql` is compared with its `.rq` by the reference runtime, not by these tests. To check one while you write it, run
this in a [cascade-runtime-js](https://github.com/the-cascade-protocol/cascade-runtime-js) checkout with this repository
cloned beside it, after its `npm ci` (about 2 seconds for one fixture, 8 for one query), naming a fixture's folder or a
`.sql` path from the root of this repository:

```sh
npm run conformance -- --sql-only allergies-view
```

## What a pull request must pass

All of it must be green before a merge.

- **`vocabulary`**: the test command above. Name a test to read as behaviour; nothing checks the grammar of a name.
- **`compatibility`**: the reference runtime, [cascade-runtime-js](https://github.com/the-cascade-protocol/cascade-runtime-js),
  run over your checkout.
- **`ready-to-merge`**: waits for every pull request yours depends on, and needs a `## Breaking` section listing each
  term, shape or named question renamed or removed, one `old -> new` or `old -> removed` line each, or `None`.

There is no formatter or linter. Keep the style of the file you are in, and write no comment that restates a name, a
constraint or another file.

## Commits and pull requests

Use conventional commits: `feat(vocab): ...`, `fix(shapes): ...`, `test(queries): ...`, `docs: ...`. A change to a term,
a shape or a query says why in its commit message, not in the file.

Put a closing keyword (`closes`, `fixes`, `resolves`) only before an issue the pull request finishes: GitHub closes it
whatever the rest of the sentence says.

## A change that spans two repositories

A change the runtime must follow is two pull requests, one here and one in
[cascade-runtime-js](https://github.com/the-cascade-protocol/cascade-runtime-js), each naming the other on a line of its
own, with the full URL:

```
Depends-On: https://github.com/the-cascade-protocol/cascade-runtime-js/pull/123
```

The `compatibility` check then runs the two together, and `ready-to-merge` holds each until the other can merge. Both
must be branches of the repositories themselves, not of forks: a contributor without write access to the other
repository asks a maintainer to open the counterpart. Editing a description re-runs the checks that read it; if the
named pull request changes after yours ran, re-run yours with `gh run rerun`. The full rules are cascade-bridge-spec's
[`compatibility.md`](https://github.com/the-cascade-protocol/cascade-bridge-spec/blob/main/compatibility.md).

## Licence

Contributions are under the licences the repository states: Apache-2.0, and CC-BY-4.0 for the clinical terms adapted
from the Cascade Protocol specification (see [`NOTICE`](NOTICE)).
