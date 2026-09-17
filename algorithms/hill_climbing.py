from __future__ import annotations

import random
import time
from typing import Any

import evaluate

STRINGS = ["", "a", "0", "1", "-1", "test", "null", " "]


def default_value(t: str) -> Any:
    if t == "boolean": return False
    if t in {"byte", "short", "int", "long", "float", "double"}: return 0
    if t == "char": return "a"
    if t == "java.lang.String": return ""
    return None


def random_value(t: str, rng: random.Random) -> Any:
    if t == "boolean": return rng.choice([False, True])
    if t == "byte": return rng.randint(-128, 127)
    if t == "short": return rng.randint(-1000, 1000)
    if t in {"int", "long"}: return rng.randint(-1000, 1000)
    if t in {"float", "double"}: return round(rng.uniform(-1000.0, 1000.0), 6)
    if t == "char": return chr(rng.randint(32, 126))
    if t == "java.lang.String": return rng.choice(STRINGS)
    return None


def neighbor(values: list[Any], types: list[str], rng: random.Random) -> list[Any]:
    out = list(values)
    if not out:
        return out
    i = rng.randrange(len(out))
    t = types[i]
    if t == "boolean":
        out[i] = not bool(out[i])
    elif t in {"byte", "short", "int", "long"}:
        out[i] = int(out[i]) + rng.choice([-100, -10, -1, 1, 10, 100])
        lo, hi = (-128, 127) if t == "byte" else ((-32768, 32767) if t == "short" else (-1000, 1000))
        out[i] = max(lo, min(hi, out[i]))
    elif t in {"float", "double"}:
        out[i] = float(out[i]) + rng.choice([-100.0, -10.0, -1.0, 1.0, 10.0, 100.0])
        out[i] = max(-1000.0, min(1000.0, out[i]))
    elif t == "char":
        code = ord(str(out[i])[0] if str(out[i]) else "a") + rng.choice([-5, -1, 1, 5])
        out[i] = chr(max(32, min(126, code)))
    elif t == "java.lang.String":
        choices = [x for x in STRINGS if x != out[i]] or STRINGS
        out[i] = rng.choice(choices)
    return out


def search_method(meta: dict[str, Any], method: dict[str, Any], seed: int, max_evals: int, restarts: int) -> dict[str, Any] | None:
    rng = random.Random(seed)
    types = method["parameter_types"]
    setup_sequences = meta.get("setup_sequences") or [[]]
    cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    evaluations = 0
    start = time.perf_counter()

    def score(setup_index: int, values: list[Any]) -> dict[str, Any]:
        nonlocal evaluations
        key = (setup_index, *tuple(values))
        if key not in cache:
            cache[key] = evaluate.search_candidate(meta, method, values, setup_sequences[setup_index])
            evaluations += 1
        return cache[key]

    base_values = [default_value(t) for t in types]
    best_setup: int | None = None
    best_values: list[Any] | None = None
    best_eval: dict[str, Any] | None = None

    # Explore the bounded state structures first. The order is seed-dependent for HC.
    setup_order = list(range(len(setup_sequences)))
    rng.shuffle(setup_order)
    for setup_index in setup_order:
        if evaluations >= max_evals:
            break
        ev = score(setup_index, base_values)
        if ev.get("ok") and (best_eval is None or ev["fitness"] > best_eval["fitness"]):
            best_setup, best_values, best_eval = setup_index, list(base_values), ev

    budgets = max(1, restarts)
    for restart in range(budgets):
        if evaluations >= max_evals:
            break
        current_setup = best_setup if restart == 0 and best_setup is not None else rng.randrange(len(setup_sequences))
        current = list(best_values) if restart == 0 and best_values is not None else [random_value(t, rng) for t in types]
        current_eval = score(current_setup, current)
        if current_eval.get("ok") and (best_eval is None or current_eval["fitness"] > best_eval["fitness"]):
            best_setup, best_values, best_eval = current_setup, list(current), current_eval

        stagnation = 0
        while evaluations < max_evals and stagnation < 8:
            cand_setup = current_setup
            cand = list(current)
            if len(setup_sequences) > 1 and (not types or rng.random() < 0.35):
                choices = [i for i in range(len(setup_sequences)) if i != current_setup]
                cand_setup = rng.choice(choices)
            else:
                cand = neighbor(current, types, rng)
            cand_eval = score(cand_setup, cand)
            if cand_eval.get("ok") and (not current_eval.get("ok") or cand_eval["fitness"] > current_eval["fitness"]):
                current_setup, current, current_eval = cand_setup, cand, cand_eval
                stagnation = 0
                if best_eval is None or cand_eval["fitness"] > best_eval["fitness"]:
                    best_setup, best_values, best_eval = cand_setup, list(cand), cand_eval
            else:
                stagnation += 1

    if best_eval is None or best_values is None or best_setup is None:
        return None
    return {
        "method": method,
        "values": best_values,
        "setup_actions": setup_sequences[best_setup],
        "oracle": best_eval["oracle"],
        "fitness": best_eval["fitness"],
        "search_coverage": best_eval.get("coverage"),
        "evaluations": evaluations,
        "unique_candidates": len(cache),
        "search_seconds": time.perf_counter() - start,
    }


def generate(meta: dict[str, Any], seed: int, settings: dict[str, Any]) -> dict[str, Any]:
    methods = meta["eligible_methods"][: int(settings["max_methods_per_case"])]
    results = []
    errors = []
    for index, method in enumerate(methods):
        try:
            found = search_method(
                meta,
                method,
                seed + index * 1009,
                int(settings["search_max_evaluations"]),
                int(settings["search_restarts"]),
            )
            if found:
                results.append(found)
            else:
                errors.append({"method": method["name"], "error": "no_valid_candidate"})
        except Exception as exc:
            errors.append({"method": method["name"], "error": str(exc)})
    return {"method_results": results, "errors": errors}
