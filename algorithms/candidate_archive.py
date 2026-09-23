from __future__ import annotations

from typing import Any


def oracle_signature(
    oracle: dict[str, Any],
) -> tuple[Any, ...]:
    status = oracle.get("status", "")

    if status == "exception":
        return (
            "exception",
            oracle.get("exception_class", ""),
        )

    kind = oracle.get("return_kind", "")
    return_type = oracle.get("return_type", "")

    if kind == "SCALAR":
        return (
            "ok",
            kind,
            return_type,
            oracle.get("return_value", ""),
        )

    if kind == "ARRAY":
        return (
            "ok",
            kind,
            return_type,
            oracle.get("array_component_type", ""),
            tuple(oracle.get("array_values", [])),
        )

    if kind == "VOID_STATE":
        return (
            "ok",
            kind,
            oracle.get("state_method", ""),
            oracle.get("state_return_type", ""),
            oracle.get("state_kind", ""),
            oracle.get("state_value", ""),
        )

    return (
        "ok",
        kind,
        return_type,
    )


def select_candidate_archive(
    method: dict[str, Any],
    setup_sequences: list[list[dict[str, Any]]],
    cache: dict[tuple[Any, ...], dict[str, Any]],
    limit: int,
    search_seconds: float,
) -> list[dict[str, Any]]:
    limit = max(1, int(limit))
    candidates: list[dict[str, Any]] = []

    for key, evaluation in cache.items():
        if not evaluation.get("ok"):
            continue

        setup_index = int(key[0])
        values = list(key[1:])

        candidates.append({
            "method": method,
            "values": values,
            "setup_actions": setup_sequences[
                setup_index
            ],
            "oracle": evaluation["oracle"],
            "fitness": evaluation["fitness"],
            "search_coverage": evaluation.get(
                "coverage"
            ),
        })

    if not candidates:
        return []

    # Python sort is stable, so equal-fitness candidates
    # preserve deterministic evaluation order.
    ranked = sorted(
        candidates,
        key=lambda candidate: -float(
            candidate.get("fitness", -1.0)
        ),
    )

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    seen_behaviors: set[tuple[Any, ...]] = set()

    # First select candidates with distinct fixed-version behavior.
    for candidate in ranked:
        behavior = oracle_signature(
            candidate["oracle"]
        )

        if behavior in seen_behaviors:
            continue

        selected.append(candidate)
        selected_ids.add(id(candidate))
        seen_behaviors.add(behavior)

        if len(selected) >= limit:
            break

    # Then fill remaining slots with different input/setup candidates.
    if len(selected) < limit:
        for candidate in ranked:
            if id(candidate) in selected_ids:
                continue

            selected.append(candidate)
            selected_ids.add(id(candidate))

            if len(selected) >= limit:
                break

    for candidate in selected:
        candidate["evaluations"] = len(cache)
        candidate["unique_candidates"] = len(cache)
        candidate["search_seconds"] = search_seconds

    return selected
