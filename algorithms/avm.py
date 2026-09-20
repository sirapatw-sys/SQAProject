from __future__ import annotations

import random
import time
from typing import Any

import evaluate
from algorithms.candidate_archive import (
    select_candidate_archive,
)


STRINGS = [
    "",
    "a",
    "0",
    "1",
    "-1",
    "test",
    "null",
    " ",
]


def default_value(type_name: str) -> Any:
    if type_name == "boolean":
        return False

    if type_name in {
        "byte",
        "short",
        "int",
        "long",
        "float",
        "double",
    }:
        return 0

    if type_name == "char":
        return "a"

    if type_name == "java.lang.String":
        return ""

    return None


def clamp(type_name: str, value: Any) -> Any:
    if type_name == "byte":
        return max(-128, min(127, int(value)))

    if type_name == "short":
        return max(-32768, min(32767, int(value)))

    if type_name in {"int", "long"}:
        return max(-1000, min(1000, int(value)))

    if type_name in {"float", "double"}:
        return max(
            -1000.0,
            min(1000.0, float(value)),
        )

    return value


def search_method(
    meta: dict[str, Any],
    method: dict[str, Any],
    seed: int,
    max_evals: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    parameter_types = method["parameter_types"]
    setup_sequences = (
        meta.get("setup_sequences") or [[]]
    )

    current = [
        default_value(type_name)
        for type_name in parameter_types
    ]

    cache: dict[
        tuple[Any, ...],
        dict[str, Any],
    ] = {}

    evaluations = 0
    start = time.perf_counter()

    def score(
        setup_index: int,
        values: list[Any],
    ) -> dict[str, Any]:
        nonlocal evaluations

        key = (
            setup_index,
            *tuple(values),
        )

        if key not in cache:
            cache[key] = evaluate.search_candidate(
                meta,
                method,
                values,
                setup_sequences[setup_index],
            )
            evaluations += 1

        return cache[key]

    # Treat the bounded setup sequence as a categorical
    # AVM variable and scan it deterministically.
    current_setup = 0
    current_eval: dict[str, Any] = {
        "ok": False,
        "fitness": -1.0,
    }

    best_setup: int | None = None
    best_values: list[Any] | None = None
    best_eval: dict[str, Any] | None = None

    for setup_index in range(
        len(setup_sequences)
    ):
        if evaluations >= max_evals:
            break

        evaluation = score(
            setup_index,
            current,
        )

        if (
            evaluation.get("ok")
            and (
                best_eval is None
                or evaluation["fitness"]
                > best_eval["fitness"]
            )
        ):
            best_setup = setup_index
            best_values = list(current)
            best_eval = evaluation

            current_setup = setup_index
            current_eval = evaluation

    if (
        best_setup is None
        or best_eval is None
        or best_values is None
    ):
        return []

    current_setup = best_setup
    current = list(best_values)
    current_eval = best_eval

    if not parameter_types:
        return select_candidate_archive(
            method=method,
            setup_sequences=setup_sequences,
            cache=cache,
            limit=max_candidates,
            search_seconds=(
                time.perf_counter() - start
            ),
        )

    variable_order = list(
        range(len(parameter_types))
    )
    rng.shuffle(variable_order)

    changed = True

    while evaluations < max_evals and changed:
        changed = False

        for index in variable_order:
            if evaluations >= max_evals:
                break

            type_name = parameter_types[index]

            if type_name == "boolean":
                candidates: list[Any] | None = [
                    False,
                    True,
                ]
            elif type_name == "java.lang.String":
                candidates = STRINGS
            elif type_name == "char":
                candidates = [
                    "a",
                    "A",
                    "0",
                    " ",
                    "z",
                ]
            else:
                candidates = None

            if candidates is not None:
                local_best = current_eval
                local_values = list(current)

                for value in candidates:
                    if evaluations >= max_evals:
                        break

                    candidate_values = list(current)
                    candidate_values[index] = value

                    evaluation = score(
                        current_setup,
                        candidate_values,
                    )

                    if (
                        evaluation.get("ok")
                        and (
                            not local_best.get("ok")
                            or evaluation["fitness"]
                            > local_best["fitness"]
                        )
                    ):
                        local_best = evaluation
                        local_values = candidate_values

                if local_values != current:
                    current = local_values
                    current_eval = local_best
                    changed = True

                if (
                    current_eval.get("ok")
                    and (
                        best_eval is None
                        or current_eval["fitness"]
                        > best_eval["fitness"]
                    )
                ):
                    best_values = list(current)
                    best_eval = current_eval

                continue

            base = float(current[index])

            plus = list(current)
            plus[index] = clamp(
                type_name,
                base + 1,
            )

            minus = list(current)
            minus[index] = clamp(
                type_name,
                base - 1,
            )

            plus_eval = (
                score(current_setup, plus)
                if evaluations < max_evals
                else {
                    "ok": False,
                    "fitness": -1.0,
                }
            )

            minus_eval = (
                score(current_setup, minus)
                if evaluations < max_evals
                else {
                    "ok": False,
                    "fitness": -1.0,
                }
            )

            options = [
                (
                    current_eval,
                    list(current),
                    0,
                ),
                (
                    plus_eval,
                    plus,
                    1,
                ),
                (
                    minus_eval,
                    minus,
                    -1,
                ),
            ]

            options = [
                option
                for option in options
                if option[0].get("ok")
            ]

            if not options:
                continue

            (
                chosen_eval,
                chosen_values,
                direction,
            ) = max(
                options,
                key=lambda option: option[0][
                    "fitness"
                ],
            )

            if (
                not current_eval.get("ok")
                or chosen_eval["fitness"]
                > current_eval.get(
                    "fitness",
                    -1.0,
                )
            ):
                current = chosen_values
                current_eval = chosen_eval
                changed = True
                step = 2

                while (
                    direction
                    and evaluations < max_evals
                ):
                    candidate_values = list(current)
                    candidate_values[index] = clamp(
                        type_name,
                        float(current[index])
                        + direction * step,
                    )

                    evaluation = score(
                        current_setup,
                        candidate_values,
                    )

                    if (
                        evaluation.get("ok")
                        and evaluation["fitness"]
                        > current_eval["fitness"]
                    ):
                        current = candidate_values
                        current_eval = evaluation
                        step *= 2
                    else:
                        break

            if (
                current_eval.get("ok")
                and (
                    best_eval is None
                    or current_eval["fitness"]
                    > best_eval["fitness"]
                )
            ):
                best_values = list(current)
                best_eval = current_eval

    if best_eval is None:
        return []

    return select_candidate_archive(
        method=method,
        setup_sequences=setup_sequences,
        cache=cache,
        limit=max_candidates,
        search_seconds=(
            time.perf_counter() - start
        ),
    )


def generate(
    meta: dict[str, Any],
    seed: int,
    settings: dict[str, Any],
) -> dict[str, Any]:
    methods = meta["eligible_methods"][
        : int(settings["max_methods_per_case"])
    ]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    max_candidates = int(
        settings.get(
            "search_candidates_per_method",
            1,
        )
    )

    for index, method in enumerate(methods):
        try:
            found = search_method(
                meta=meta,
                method=method,
                seed=seed + index * 1009,
                max_evals=int(
                    settings[
                        "search_max_evaluations"
                    ]
                ),
                max_candidates=max_candidates,
            )

            if found:
                results.extend(found)
            else:
                errors.append({
                    "method": method["name"],
                    "error": "no_valid_candidate",
                })

        except Exception as exception:
            errors.append({
                "method": method["name"],
                "error": str(exception),
            })

    return {
        "method_results": results,
        "errors": errors,
    }