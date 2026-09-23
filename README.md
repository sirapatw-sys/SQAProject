# SQA Defects4J Benchmark — Simple 3-Worker Version

This repository compares four Java unit-test generation approaches on Defects4J:

- Hill Climbing
- Alternating Variable Method (AVM)
- GPT
- Gemini

The project is intentionally small enough for a 3-person student team to understand and operate. The four generators are separate, but checkout/evaluation/result handling is shared so all methods are measured the same way.

## Core files

```text
run.py                  main runner, case partitioning, checkpoint/resume
d4j.py                  Defects4J checkout/compile/API discovery
evaluate.py             candidate fitness + JUnit evaluation + JaCoCo
analyze.py              merge all members' JSON results into CSV
algorithms/
  hill_climbing.py
  avm.py
ai/
  gpt.py
  gemini.py
harness/
  CandidateRunner.java
config/
  cases.csv
  settings.json
```

Docker/environment/config files are separate because they are infrastructure, not benchmark logic.

## Evaluation protocol

For every configured Defects4J bug:

1. Checkout both `<bug>f` and `<bug>b`.
2. Generate/search using the fixed revision only.
3. Build a JUnit test from the fixed behavior.
4. Compile and run the generated test on the fixed revision.
5. Measure final JaCoCo instruction/branch/line coverage on the fixed revision.
6. Compile and run the exact same generated test on the buggy revision.
7. `fault_detected = fixed passes AND buggy compiles AND buggy fails`.

Do not feed patches, source diffs, issue descriptions, triggering tests, or developer bug-revealing tests into GPT/Gemini or the search algorithms.

### Target selection note

`target_class` can be frozen manually in `config/cases.csv`. If left blank, this implementation falls back to Defects4J `classes.modified` and records:

```text
target_selection_source = defects4j_classes.modified
```

That is a **target-aware** benchmark configuration. If your report requires a stricter no-bug-location protocol, freeze a target-selection policy before the final experiment and fill `target_class` explicitly instead of using the fallback.

`concrete_class` remains an optional manual override. HC/AVM now run a bounded construction planner first. It recursively resolves public constructors, exact-type public static factories, singleton/default public static fields, primitives and boxed values, strings, enums, empty arrays, common collection interfaces, lightweight stream/reader/writer implementations, and a capped batch scan for concrete project subtypes of abstract/interface receivers. The chosen construction graph is deterministic and is recorded as `construction_plan` in metadata/results.

Construction is deliberately separate from HC/AVM input search. Constructor dependencies are fixed structural values; only supported target-method inputs and bounded setup choices enter the search space. Cycles, non-public classes, unresolved abstract/domain interfaces, and graphs that exceed the configured depth/type/time limits remain `unsupported` instead of causing unbounded exploration.

Runtime controls in `config/settings.json` cap planning, candidate execution, total search, and the complete algorithm run. The default algorithm budget is 180 seconds, with 110 seconds for search and 60 seconds reserved for final fixed/buggy evaluation. This budget starts after Defects4J checkout/compile preparation; a cold Docker checkout is infrastructure time and is reported separately by the console flow. Progress is line-buffered and printed during candidate evaluation.

## 1. Setup

```bash
cp .env.example .env
```

Edit `.env`:

```text
D4J_ROOT=/home/YOUR_USER/defects4j
LOCAL_UID=1000
LOCAL_GID=1000

GPT_API_KEY=...
GEMINI_API_KEY=...
```

Set the **same model names on all three computers** in `config/settings.json`:

```json
"gpt_model": "YOUR_GPT_MODEL",
"gemini_model": "YOUR_GEMINI_MODEL"
```

API endpoints and output/source limits are also frozen in `config/settings.json`, so they are included in the `experiment_id`.

Install Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

Check environment:

```bash
python3 d4j.py check
```

The Docker worker is persistent. JaCoCo CLI and agent are downloaded automatically the first time they are needed, then reused for the rest of the process.

## 2. cases.csv

Example:

```csv
project,bug_id,target_class,concrete_class,method,enabled
Chart,1,,org.jfree.chart.renderer.category.BarRenderer,,true
```

Columns:

- `project`, `bug_id`: Defects4J case.
- `target_class`: optional explicit target. Blank uses the configured fallback.
- `concrete_class`: optional public receiver override. Its construction graph must be resolvable within the configured planner limits.
- `method`: optional. Leave blank to test up to `max_methods_per_case` eligible public methods.
- `enabled`: `true` or `false`.

Generate an inventory from the local Defects4J installation:

```bash
python3 d4j.py inventory --out config/cases.csv
```

This creates rows for all active bugs. You can then manually fill special `concrete_class` or `method` cells where required.

## 3. Run one case first

```bash
python3 run.py --project Chart --bug 1 --worker member1
```

Or only selected methods:

```bash
python3 run.py --project Chart --bug 1 --methods hill_climbing avm
```

```bash
python3 run.py --project Chart --bug 1 --methods gpt gemini
```

## 4. Split the 854 cases across 3 people

Every member should use the **same Git commit**, `config/cases.csv`, and `config/settings.json`.

The enabled cases are sorted deterministically by `(project, bug_id)` and then divided into three non-overlapping, contiguous ranges. Case ranges are 1-based and inclusive.

Member 1:

```bash
python3 run.py \
  --case-range 1-285 \
  --methods hill_climbing avm gpt gemini \
  --worker member1
```

Member 2:

```bash
python3 run.py \
  --case-range 286-570 \
  --methods hill_climbing avm gpt gemini \
  --worker member2
```

Member 3:

```bash
python3 run.py \
  --case-range 571-854 \
  --methods hill_climbing avm gpt gemini \
  --worker member3
```

Each assigned bug runs all four methods on the same worker machine. Use only the assigned `--case-range` command so every case is executed exactly once.

Running all four methods for every assigned bug is preferable to assigning one algorithm per person, because HC/AVM/GPT/Gemini for a bug then share the same local environment.

## 5. Checkpoint and resume

Every seed/repetition is saved immediately as its own JSON result.

Algorithm runs use the configured seeds, e.g.:

```text
seed_101.json
seed_202.json
seed_303.json
```

AI runs use:

```text
run_1.json
run_2.json
run_3.json
```

Re-run the same command after a crash, shutdown, or interruption. `completed` and `unsupported` tasks are skipped automatically.

Use `--force` only if you intentionally want to rerun completed tasks.

## 6. GPT/Gemini quota behavior

Temporary 429/server errors are retried with backoff.

If an API continues returning a quota/rate-limit condition, the current task is saved as:

```text
status = paused_quota
```

That provider is deferred for the rest of the current process, while the other methods continue.

Later, after quota/credit resets, run the same command again. `paused_quota` is not considered complete, so it is retried. Already completed HC/AVM/GPT/Gemini tasks are not repeated.

## 7. Result layout

```text
results/workers/
  member1/
    Chart/
      1/
        hill_climbing/
          seed_101.json
          seed_202.json
          seed_303.json
        avm/
        gpt/
        gemini/
```

Generated tests and AI prompt/response files are stored under:

```text
generated_tests/<worker>/<project>/<bug>/<method>/<run_id>/
```

Each JSON records the worker, Git commit, `experiment_id`, target selection source, model/seed, validity, fault detection, coverage, duration, and generated test path. The `experiment_id` hashes the benchmark code/config/prompt so results from mismatched experiment definitions are not silently combined.

## 8. Merge the three members' results

Copy each member's result directory into the same repository under `results/workers/` and run:

```bash
python3 analyze.py
```

Outputs:

```text
results/summary/all_results.csv
results/summary/summary_by_method.csv
results/summary/summary_by_project.csv
```

These files can be imported into Excel/Google Sheets for charts and statistical analysis. `summary_by_method.csv` reports both fault-detecting runs and unique Defects4J bugs detected, so repeated seeds/runs do not inflate the bug count.

## 9. Search simplifications

The algorithmic generators intentionally support a manageable student-project search space:

- public target methods
- primitive and `String` target arguments
- public no-argument or supported public parameterized construction for the configured concrete receiver
- a **small bounded stateful setup sequence** before the target call
- setup actions are public instance `void` methods with at most the configured number of parameters
- setup arguments may use primitive/String defaults or an exact public helper class with a public no-arg constructor
- manually configured concrete receiver class when needed
- final oracle derived from fixed behavior

The stateful search is deliberately bounded by `stateful_max_setup_actions`, `stateful_max_setup_parameters`, `stateful_max_setup_steps`, and `stateful_max_sequences` in `config/settings.json`. It does not read trigger tests, patches, or known bug setups.

Hill Climbing and AVM use the same candidate domain and evaluation infrastructure, but different search behavior:

- Hill Climbing: seed-dependent setup exploration, random restarts, and local input/setup mutations.
- AVM: deterministic categorical exploration of bounded setup sequences, followed by variable-by-variable exploratory moves and numeric pattern moves.

This remains much simpler than a general Java object-graph generator. It will not construct arbitrary interfaces, multi-constructor dependency graphs, or deep object networks; unsupported cases are recorded instead of hidden by project-specific hardcoding.

## 10. Recommended workflow

Before launching hundreds of bugs:

```text
1. Run Chart-1 with HC/AVM only.
2. Inspect the generated JUnit files and JSON.
3. Run GPT/Gemini once each and confirm API configuration.
4. Run 5–10 bugs with --limit.
5. Freeze Git commit + settings + cases.csv.
6. Start the three assigned case ranges.
7. Merge and analyze after all workers finish.
```

Do not start the full Defects4J inventory until this pilot succeeds on all three computers.

### Runtime warning

HC/AVM still launch a Java candidate process and collect JaCoCo search coverage for each evaluated input. This keeps the implementation simple and transparent, but a full 854-bug run can take a long time. Use the pilot to measure average runtime before freezing `search_max_evaluations`, `max_methods_per_case`, and the number of repetitions. Do not change those settings after the final experiment starts.

## Efficiency metrics recorded per run

Each result now records `test_case_count`, `generation_time_sec`, and `evaluation_time_sec` in addition to total duration, validity, fault detection, and JaCoCo instruction/branch/line coverage. `analyze.py` also reports coverage-per-test and time-per-test indicators so methods that generate different numbers of JUnit test cases can be compared more fairly. Coverage itself remains the primary metric; coverage-per-test is a normalized efficiency indicator.
