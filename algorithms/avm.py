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


def clamp(t: str, value: Any) -> Any:
    if t in {"byte", "short", "int", "long"}:
        lo, hi = (-128, 127) if t == "byte" else ((-32768, 32767) if t == "short" else (-1000, 1000))
        return max(lo, min(hi, int(value)))
    if t in {"float", "double"}:
        return max(-1000.0, min(1000.0, float(value)))
    return value


def search_method(meta: dict[str, Any], method: dict[str, Any], seed: int, max_evals: int) -> dict[str, Any] | None:
    rng = random.Random(seed)
    types = method["parameter_types"]
    setup_sequences = meta.get("setup_sequences") or [[]]
    current = [default_value(t) for t in types]
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

    # Treat the bounded setup sequence as a categorical AVM variable and scan it deterministically.
    current_setup = 0
    current_eval = {"ok": False, "fitness": -1.0}
    best_setup: int | None = None
    best_values: list[Any] | None = None
    best_eval: dict[str, Any] | None = None
    for setup_index in range(len(setup_sequences)):
        if evaluations >= max_evals:
            break
        ev = score(setup_index, current)
        if ev.get("ok") and (best_eval is None or ev["fitness"] > best_eval["fitness"]):
            best_setup, best_values, best_eval = setup_index, list(current), ev
            current_setup, current_eval = setup_index, ev

    if best_setup is None or best_eval is None or best_values is None:
        return None
    current_setup = best_setup
    current = list(best_values)
    current_eval = best_eval

    if not types:
        return {
            "method": method, "values": current, "setup_actions": setup_sequences[current_setup],
            "oracle": best_eval["oracle"], "fitness": best_eval["fitness"],
            "search_coverage": best_eval.get("coverage"), "evaluations": evaluations,
            "unique_candidates": len(cache), "search_seconds": time.perf_counter() - start,
        }

    variable_order = list(range(len(types)))
    rng.shuffle(variable_order)
    changed = True
    while evaluations < max_evals and changed:
        changed = False
        for i in variable_order:
            if evaluations >= max_evals:
                break
            t = types[i]
            if t == "boolean":
                candidates = [False, True]
            elif t == "java.lang.String":
                candidates = STRINGS
            elif t == "char":
                candidates = ["a", "A", "0", " ", "z"]
            else:
                candidates = None

            if candidates is not None:
                local_best = current_eval
                local_values = list(current)
                for v in candidates:
                    if evaluations >= max_evals:
                        break
                    cand = list(current); cand[i] = v
                    ev = score(current_setup, cand)
                    if ev.get("ok") and (not local_best.get("ok") or ev["fitness"] > local_best["fitness"]):
                        local_best, local_values = ev, cand
                if local_values != current:
                    current, current_eval = local_values, local_best
                    changed = True
                if current_eval.get("ok") and (best_eval is None or current_eval["fitness"] > best_eval["fitness"]):
                    best_values, best_eval = list(current), current_eval
                continue

            base = float(current[i])
            plus = list(current); plus[i] = clamp(t, base + 1)
            minus = list(current); minus[i] = clamp(t, base - 1)
            plus_eval = score(current_setup, plus) if evaluations < max_evals else {"ok": False, "fitness": -1}
            minus_eval = score(current_setup, minus) if evaluations < max_evals else {"ok": False, "fitness": -1}
            options = [(current_eval, list(current), 0), (plus_eval, plus, 1), (minus_eval, minus, -1)]
            options = [x for x in options if x[0].get("ok")]
            if not options:
                continue
            chosen_eval, chosen_values, direction = max(options, key=lambda x: x[0]["fitness"])
            if (not current_eval.get("ok")) or chosen_eval["fitness"] > current_eval.get("fitness", -1):
                current, current_eval = chosen_values, chosen_eval
                changed = True
                step = 2
                while direction and evaluations < max_evals:
                    cand = list(current)
                    cand[i] = clamp(t, float(current[i]) + direction * step)
                    ev = score(current_setup, cand)
                    if ev.get("ok") and ev["fitness"] > current_eval["fitness"]:
                        current, current_eval = cand, ev
                        step *= 2
                    else:
                        break
            if current_eval.get("ok") and (best_eval is None or current_eval["fitness"] > best_eval["fitness"]):
                best_values, best_eval = list(current), current_eval

    if best_eval is None or best_values is None:
        return None
    return {
        "method": method,
        "values": best_values,
        "setup_actions": setup_sequences[current_setup],
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
            found = search_method(meta, method, seed + index * 1009, int(settings["search_max_evaluations"]))
            if found:
                results.append(found)
            else:
                errors.append({"method": method["name"], "error": "no_valid_candidate"})
        except Exception as exc:
            errors.append({"method": method["name"], "error": str(exc)})
    return {"method_results": results, "errors": errors}
