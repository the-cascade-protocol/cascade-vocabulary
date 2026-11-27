# cascade-vocabulary — Agent Context

The contract a Cascade pod is built and read by; [`README.md`](README.md) names the parts.

A design here is judged by the eight principles in [`PRINCIPLES.md`](PRINCIPLES.md), and every rule answers to them.
[`CONTRIBUTING.md`](CONTRIBUTING.md) says how to run the tests and what a pull request must pass.

## The rules

Only what no check catches and the files do not show. The number after each rule is the principle in
[`PRINCIPLES.md`](PRINCIPLES.md) that it serves.

- **Content is on a version, not on its record, and no shape requires it but one:** every version of a medication says
  whether it came from a prescription or from a list of what the person takes. A source may omit anything else. (4)
- **Each question is asked once.** Before adding one, look under its kind in `queries/questions/` for the question that
  already returns those rows. (3)
- **Expected answers are written from the rule, never from a runtime's output.** A kit's `expected/` and its examples
  come from [the scenario](https://github.com/the-cascade-protocol/cascade-vocabulary/issues/4), and a rule's examples
  under `runtime/` from the rule they sit under. A query's expected rows come from what the query says it does, on a
  fixture under [`tests/fixtures/`](tests/fixtures) made for that behaviour. (6)
- **A `.sql` is compared with its `.rq` once, by the reference runtime.** To check one while writing it, run
  `npm run conformance -- --sql-only <fixture folder or .sql path>` in a cascade-runtime-js checkout beside this one. (6)
