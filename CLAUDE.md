# cascade-vocabulary — Agent Context

The contract a Cascade pod is built and read by; [`README.md`](README.md) names the parts.

A design here is judged by the eight principles in [`PRINCIPLES.md`](PRINCIPLES.md), and every rule answers to them.
[`CONTRIBUTING.md`](CONTRIBUTING.md) says how to run the tests and what a pull request must pass.

## The rules

Only what no check catches and the files do not show; each names the principle it serves.

- **Content is on a version, not on its record, and no shape requires it:** a source may omit any of it. (2)
- **Each question is asked once.** Before adding one, look under its kind in `queries/questions/` for the question that
  already returns those rows. (3)
- **Expected answers are written from the rule, never from a runtime's output:** a kit's `expected/` and its examples
  from [the scenario](https://github.com/the-cascade-protocol/cascade-vocabulary/issues/4), a rule's examples under
  `runtime/` from the rule they sit under, and a query's expected rows from what the query says it does, on a fixture
  under [`tests/fixtures/`](tests/fixtures) made for that behaviour. (6)
- **Adapters name `ontologies/cascade.ttl` and `ontologies/cascade.shapes.ttl` by path, and no check here runs them:**
  moving a file, or removing a term an adapter writes, needs a change in each adapter too. (6)
- **The why of a change to a term, a shape or a query goes in its commit message;** the file says what, not why. (5)
