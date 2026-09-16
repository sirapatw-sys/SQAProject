# SQA Defects4J Benchmark

Benchmark project for comparing four unit-test generation methods on Defects4J:

1. Hill Climbing
2. Alternating Variable Method (AVM)
3. GPT
4. Gemini

## Design goals

- The Defects4J dataset is **not stored in GitHub**.
- Every member uses the same Docker worker image and the same experiment configuration.
- Work is split by Defects4J bug instance.
- A member assigned a bug runs **all four methods** for that bug.
- Generated tests and small experiment results are stored in this repository.
- Large caches, checked-out projects, build outputs, and the Defects4J dataset remain local.

## Planned workflow

```text
Defects4J inventory
        |
        v
assignments/member_XX.csv
        |
        v
Docker worker on each member's computer
        |
        +--> Hill Climbing
        +--> AVM
        +--> GPT
        +--> Gemini
        |
        v
shared evaluator
        |
        +--> compile status
        +--> test execution
        +--> line/branch coverage
        +--> fault detection
        +--> runtime / counts / errors
        |
        v
results/raw/<project>/<bug_id>/
        |
        v
results/summary/
```

## Important

This scaffold intentionally does not contain the large Defects4J data.
Each machine mounts its local Defects4J folder into the Docker worker.

The target-class scope and the version used for generation (`b` or `f`) are experiment
protocol decisions and are configurable. Do not begin the full benchmark until the
protocol is frozen and the pilot run succeeds on every member's machine.
