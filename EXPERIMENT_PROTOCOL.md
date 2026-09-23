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

## Bounded construction and runtime domain

The search algorithms operate on public target methods whose arguments are primitive values or `String`. Receiver creation uses a deterministic, recursive construction plan supporting public constructors, exact-type public factories, public singleton/default fields, primitive/boxed/String values, enums, empty arrays, common collections, lightweight stream/reader/writer implementations, and bounded discovery of concrete project subtypes. Setup helper arguments can use the same plans.

Construction parameters are structural fixed values and are not HC/AVM search variables. This prevents dependency graphs from multiplying the behavioral search space. Constructor/factory candidates are ranked by recursive construction cost with stable descriptor/name tie-breakers.

Planning has cycle detection, memoized type inspection, maximum depth, maximum inspected types, candidate caps, and a planning timeout. Non-public classes, unresolved domain interfaces/abstract classes, private APIs, builders, and graphs outside these limits can remain unsupported. Reflection access bypass and `Unsafe.allocateInstance` are intentionally not used.

The default post-preparation budget for each HC/AVM task is 180 seconds: at most 110 seconds of search, a 10-second candidate timeout, and a 60-second final-evaluation reserve. Progress output is flushed throughout the search. Defects4J checkout/compile and first-time Docker/tool setup are preparation costs and are not included in this algorithm budget.

If `target_class` is blank, the software can use Defects4J `classes.modified` as a target-aware fallback. This must be disclosed in the report; use an explicitly frozen target policy if the course requires a no-bug-location benchmark.

## Test-suite efficiency metrics

For every HC, AVM, GPT, and Gemini run, record the number of generated JUnit `@Test` methods, test-generation time, evaluation time, total duration, validity, fault detection, and JaCoCo instruction/branch/line coverage. Analysis additionally reports coverage per generated test case and time per generated test case. These normalized values are efficiency indicators and do not replace the raw coverage measurements.
