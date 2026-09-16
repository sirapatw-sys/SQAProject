# Experiment Protocol — Draft

## Methods

- Hill Climbing
- Alternating Variable Method (AVM)
- GPT
- Gemini

## Fairness rule

For each assigned Defects4J bug instance, the same worker machine runs all four
methods. This avoids comparing Hill Climbing on one machine with AVM on a very
different machine.

## Shared evaluator

All generated suites are evaluated by the same code path and the same Defects4J
environment.

## Reproducibility metadata to record

- Defects4J version
- Java version
- timezone
- Docker image identifier
- worker id / hardware summary
- project and bug id
- generated-for version (`b` or `f`)
- target scope
- method
- random seed / budget for algorithms
- AI model identifier and generation parameters
- prompt/config hashes
- compile/run status
- coverage
- fault detection
- timing
- error category

## Decisions to freeze before the full benchmark

1. Exact Defects4J version supplied/required by the instructor.
2. Whether generation uses buggy (`b`) or fixed (`f`) revisions.
3. Target scope: all production classes vs a narrower documented scope.
4. JUnit version handling across projects.
5. Algorithm search budget and repetitions.
6. Exact GPT/Gemini model identifiers and API endpoints.
7. Prompt templates.
8. Final metrics and failure categories.
