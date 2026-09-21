# Experiment Protocol

## Compared methods

1. Hill Climbing
2. Alternating Variable Method (AVM)
3. GPT
4. Gemini

## Repetition

- HC/AVM: seeds are defined in `config/settings.json`.
- GPT/Gemini: independent repetitions are defined by `ai_repetitions` in `config/settings.json`.

## Common evaluation

All generated tests are evaluated by the same `evaluate.py` path.

A test is valid when it compiles and passes on the fixed revision.

A valid test detects a fault when the exact same source also compiles on the buggy revision but fails there.

Final coverage is measured on the fixed revision using JaCoCo instruction, branch, and line coverage for the configured target class.

## Fairness controls

- Fixed revision is used for generation/oracle formation.
- Buggy source is not supplied to any generator.
- No patch, diff, issue description, trigger test, or known failing developer test is supplied to a generator.
- The default fallback is target-aware at class level (`classes.modified`); no patch/line-level location is supplied. This must be disclosed in the report.
- Same case configuration and evaluator are used across all four methods.
- The 854 sorted cases are divided into the fixed, non-overlapping ranges `1-285`, `286-570`, and `571-854`.
- Each bug's four methods run on the same worker responsible for its assigned case range.
- Git commit and worker ID are stored with every task result.

## Known simplification

The search algorithms operate on public target methods whose arguments are primitive values or `String`. The configured receiver must be a public, non-abstract concrete class. A receiver may use either a public no-argument constructor or a supported public parameterized constructor whose arguments are primitive values, `String`, or `Comparable`.

Receiver construction is deterministic. The implementation selects the supported public constructor with the fewest parameters and uses its JVM descriptor as a tie-breaker. Numeric constructor arguments use `0`, `boolean` uses `false`, `char` uses `a`, and `String`/`Comparable` uses `sqa`. These constructor values are fixed receiver setup values and are not currently search variables.

The algorithms also allow a small bounded stateful setup sequence before the target call. Setup actions are discovered only from public APIs and may use primitive/String default values or exact helper classes that themselves have public no-argument constructors.

This is intentionally not a general object-graph generator. Non-public or abstract receiver classes, interfaces, constructors requiring streams/files/collections or other unsupported object types, interface/abstract helper parameters, constructor dependency graphs, and deep arbitrary state construction can remain unsupported. Cases outside this domain may be marked `unsupported` or require a manually configured `concrete_class`.

If `target_class` is blank, the software can use Defects4J `classes.modified` as a target-aware fallback. This must be disclosed in the report; use an explicitly frozen target policy if the course requires a no-bug-location benchmark.

## Test-suite efficiency metrics

For every HC, AVM, GPT, and Gemini run, record the number of generated JUnit `@Test` methods, test-generation time, evaluation time, total duration, validity, fault detection, and JaCoCo instruction/branch/line coverage. Analysis additionally reports coverage per generated test case and time per generated test case. These normalized values are efficiency indicators and do not replace the raw coverage measurements.