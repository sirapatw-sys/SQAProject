from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Callable


Inspection = dict[str, Any]
Plan = dict[str, Any]


PRIMITIVE_DEFAULTS: dict[str, Any] = {
    "byte": 0,
    "short": 0,
    "int": 0,
    "long": 0,
    "float": 0,
    "double": 0,
    "boolean": False,
    "char": "a",
}

REFERENCE_DEFAULTS: dict[str, tuple[str, Any]] = {
    "java.lang.String": ("java.lang.String", "sqa"),
    "java.lang.CharSequence": ("java.lang.String", "sqa"),
    "java.lang.Comparable": ("java.lang.String", "sqa"),
    "java.lang.Object": ("java.lang.String", "sqa"),
    "java.lang.Byte": ("java.lang.Byte", 0),
    "java.lang.Short": ("java.lang.Short", 0),
    "java.lang.Integer": ("java.lang.Integer", 0),
    "java.lang.Long": ("java.lang.Long", 0),
    "java.lang.Float": ("java.lang.Float", 0),
    "java.lang.Double": ("java.lang.Double", 0),
    "java.lang.Boolean": ("java.lang.Boolean", False),
    "java.lang.Character": ("java.lang.Character", "a"),
    "java.lang.Number": ("java.lang.Integer", 0),
}

STANDARD_IMPLEMENTATIONS = {
    "java.lang.Iterable": "java.util.ArrayList",
    "java.util.Collection": "java.util.ArrayList",
    "java.util.List": "java.util.ArrayList",
    "java.util.Set": "java.util.LinkedHashSet",
    "java.util.SortedSet": "java.util.TreeSet",
    "java.util.NavigableSet": "java.util.TreeSet",
    "java.util.Queue": "java.util.ArrayDeque",
    "java.util.Deque": "java.util.ArrayDeque",
    "java.util.Map": "java.util.LinkedHashMap",
    "java.util.SortedMap": "java.util.TreeMap",
    "java.util.NavigableMap": "java.util.TreeMap",
}


@dataclass(frozen=True)
class PlannerLimits:
    max_depth: int = 3
    max_inspected_types: int = 24
    max_constructors_per_type: int = 8
    max_factories_per_type: int = 6
    timeout_sec: float = 15.0


class ConstructionPlanner:
    """Build a small deterministic object graph without expanding the search space.

    ``inspect_type`` returns the public declaration, constructors, methods and
    optional public static fields of one JVM type. Exploration is deliberately
    bounded and memoized so one difficult class cannot consume a benchmark run.
    """

    def __init__(
        self,
        inspect_type: Callable[[str], Inspection],
        limits: PlannerLimits | None = None,
        find_concrete_subtypes: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.inspect_type = inspect_type
        self.limits = limits or PlannerLimits()
        self.find_concrete_subtypes = find_concrete_subtypes
        self.started = 0.0
        self.inspections: dict[str, Inspection | None] = {}
        self.memo: dict[tuple[str, int], Plan | None] = {}
        self.failures: dict[str, str] = {}

    def plan(self, type_name: str) -> Plan | None:
        self.started = time.monotonic()
        self.inspections.clear()
        self.memo.clear()
        self.failures.clear()
        plan = self._plan(type_name, self.limits.max_depth, ())
        if plan is not None:
            plan = dict(plan)
            plan["planner"] = {
                "inspected_types": len(self.inspections),
                "max_depth": self.limits.max_depth,
            }
        return plan

    def _within_budget(self) -> bool:
        return (
            time.monotonic() - self.started < self.limits.timeout_sec
            and len(self.inspections) < self.limits.max_inspected_types
        )

    def _inspect(self, type_name: str) -> Inspection | None:
        if type_name in self.inspections:
            return self.inspections[type_name]
        if not self._within_budget():
            self.failures.setdefault(type_name, "planner_budget_exhausted")
            return None
        try:
            value = self.inspect_type(type_name)
        except Exception as exc:
            self.failures.setdefault(type_name, f"inspection_failed: {exc}")
            value = None
        self.inspections[type_name] = value
        return value

    @staticmethod
    def _with_cost(plan: Plan, cost: float) -> Plan:
        out = dict(plan)
        out["cost"] = round(cost, 3)
        return out

    def _plan(
        self,
        type_name: str,
        remaining_depth: int,
        visiting: tuple[str, ...],
    ) -> Plan | None:
        key = (type_name, remaining_depth)
        if key in self.memo:
            cached = self.memo[key]
            return None if cached is None else dict(cached)
        if type_name in visiting:
            self.failures.setdefault(type_name, "cycle_detected")
            return None

        if type_name in PRIMITIVE_DEFAULTS:
            result = self._with_cost({
                "strategy": "literal",
                "type": type_name,
                "value_type": type_name,
                "value": PRIMITIVE_DEFAULTS[type_name],
            }, 1.0)
            self.memo[key] = result
            return dict(result)

        if type_name in REFERENCE_DEFAULTS:
            value_type, value = REFERENCE_DEFAULTS[type_name]
            result = self._with_cost({
                "strategy": "literal",
                "type": type_name,
                "value_type": value_type,
                "value": value,
            }, 1.0)
            self.memo[key] = result
            return dict(result)

        if type_name.endswith("[]"):
            result = self._with_cost({
                "strategy": "empty_array",
                "type": type_name,
            }, 1.25)
            self.memo[key] = result
            return dict(result)

        implementation = STANDARD_IMPLEMENTATIONS.get(type_name)
        if implementation:
            result = self._with_cost({
                "strategy": "constructor",
                "type": type_name,
                "class_name": implementation,
                "parameter_types": [],
                "arguments": [],
            }, 2.0)
            self.memo[key] = result
            return dict(result)

        special = self._special_plan(type_name)
        if special is not None:
            self.memo[key] = special
            return dict(special)

        if remaining_depth <= 0 or not self._within_budget():
            self.failures.setdefault(type_name, "maximum_depth_or_budget")
            self.memo[key] = None
            return None

        info = self._inspect(type_name)
        if not info:
            self.memo[key] = None
            return None

        declaration = str(info.get("class_decl", ""))
        if not declaration.startswith("public "):
            self.failures.setdefault(type_name, "class_not_public")
            self.memo[key] = None
            return None

        if " extends java.lang.Enum<" in declaration:
            result = self._with_cost({
                "strategy": "enum_first",
                "type": type_name,
            }, 1.25)
            self.memo[key] = result
            return dict(result)

        next_visiting = (*visiting, type_name)
        candidates: list[Plan] = []

        fields = sorted(
            info.get("static_fields", []),
            key=lambda f: (
                0 if f.get("name") in {"INSTANCE", "DEFAULT", "EMPTY"} else 1,
                str(f.get("name", "")),
            ),
        )
        for field in fields:
            if field.get("type") == type_name:
                candidates.append(self._with_cost({
                    "strategy": "static_field",
                    "type": type_name,
                    "class_name": type_name,
                    "field_name": field["name"],
                }, 1.5))

        is_abstract = (
            " interface " in f" {declaration} "
            or " abstract " in f" {declaration} "
        )
        if not is_abstract:
            constructors = sorted(
                info.get("constructors", []),
                key=lambda c: (len(c.get("parameter_types", [])), c.get("descriptor", "")),
            )[: self.limits.max_constructors_per_type]
            for constructor in constructors:
                argument_plans = self._plan_arguments(
                    list(constructor.get("parameter_types", [])),
                    remaining_depth - 1,
                    next_visiting,
                )
                if argument_plans is None:
                    continue
                candidates.append(self._with_cost({
                    "strategy": "constructor",
                    "type": type_name,
                    "class_name": type_name,
                    "descriptor": constructor.get("descriptor", ""),
                    "parameter_types": list(constructor.get("parameter_types", [])),
                    "arguments": argument_plans,
                }, 3.0 + sum(float(p["cost"]) for p in argument_plans)))

        factory_name_rank = {
            "getInstance": 0,
            "of": 1,
            "create": 2,
            "newInstance": 3,
            "valueOf": 4,
        }
        factories = [
            method for method in info.get("methods", [])
            if method.get("return_type") == type_name
            and " static " in f" {method.get('declaration', '')} "
        ]
        factories.sort(key=lambda m: (
            len(m.get("parameter_types", [])),
            factory_name_rank.get(str(m.get("name")), 50),
            str(m.get("name", "")),
            str(m.get("descriptor", "")),
        ))
        for method in factories[: self.limits.max_factories_per_type]:
            argument_plans = self._plan_arguments(
                list(method.get("parameter_types", [])),
                remaining_depth - 1,
                next_visiting,
            )
            if argument_plans is None:
                continue
            candidates.append(self._with_cost({
                "strategy": "static_factory",
                "type": type_name,
                "class_name": type_name,
                "method_name": method["name"],
                "descriptor": method.get("descriptor", ""),
                "parameter_types": list(method.get("parameter_types", [])),
                "arguments": argument_plans,
            }, 3.5 + sum(float(p["cost"]) for p in argument_plans)))

        if is_abstract and self.find_concrete_subtypes is not None and self._within_budget():
            try:
                subtypes = self.find_concrete_subtypes(type_name)
            except Exception as exc:
                self.failures.setdefault(type_name, f"subtype_discovery_failed: {exc}")
                subtypes = []
            for subtype in subtypes:
                if not self._within_budget():
                    break
                subtype_plan = self._plan(
                    subtype,
                    remaining_depth - 1,
                    next_visiting,
                )
                if subtype_plan is None:
                    continue
                subtype_plan = dict(subtype_plan)
                subtype_plan["requested_type"] = type_name
                subtype_plan["selected_subtype"] = subtype
                subtype_plan["cost"] = round(float(subtype_plan["cost"]) + 1.0, 3)
                candidates.append(subtype_plan)

        if not candidates:
            self.failures.setdefault(type_name, "no_bounded_construction_strategy")
            self.memo[key] = None
            return None

        selected = min(
            candidates,
            key=lambda p: (
                float(p["cost"]),
                len(p.get("arguments", [])),
                str(p.get("strategy", "")),
                str(p.get("descriptor", "")),
                str(p.get("field_name", "")),
            ),
        )
        self.memo[key] = selected
        return dict(selected)

    def _plan_arguments(
        self,
        parameter_types: list[str],
        remaining_depth: int,
        visiting: tuple[str, ...],
    ) -> list[Plan] | None:
        plans: list[Plan] = []
        for parameter_type in parameter_types:
            child = self._plan(parameter_type, remaining_depth, visiting)
            if child is None:
                return None
            plans.append(child)
        return plans

    def _special_plan(self, type_name: str) -> Plan | None:
        if type_name == "java.util.Optional":
            return self._with_cost({
                "strategy": "static_factory",
                "type": type_name,
                "class_name": type_name,
                "method_name": "empty",
                "parameter_types": [],
                "arguments": [],
            }, 1.5)
        if type_name == "java.io.InputStream":
            return self._with_cost({
                "strategy": "constructor",
                "type": type_name,
                "class_name": "java.io.ByteArrayInputStream",
                "parameter_types": ["byte[]"],
                "arguments": [self._with_cost({"strategy": "empty_array", "type": "byte[]"}, 1.25)],
            }, 3.0)
        if type_name == "java.io.OutputStream":
            return self._with_cost({
                "strategy": "constructor",
                "type": type_name,
                "class_name": "java.io.ByteArrayOutputStream",
                "parameter_types": [],
                "arguments": [],
            }, 2.0)
        if type_name == "java.io.Reader":
            child = self._with_cost({
                "strategy": "literal", "type": "java.lang.String",
                "value_type": "java.lang.String", "value": "",
            }, 1.0)
            return self._with_cost({
                "strategy": "constructor", "type": type_name,
                "class_name": "java.io.StringReader",
                "parameter_types": ["java.lang.String"], "arguments": [child],
            }, 3.0)
        if type_name == "java.io.Writer":
            return self._with_cost({
                "strategy": "constructor", "type": type_name,
                "class_name": "java.io.StringWriter",
                "parameter_types": [], "arguments": [],
            }, 2.0)
        return None


def _flatten_plan(plan: Plan, rows: list[list[str]]) -> int:
    child_ids = [_flatten_plan(child, rows) for child in plan.get("arguments", [])]
    strategy = str(plan["strategy"])
    payload = ""
    member = ""
    if strategy == "literal":
        payload = json.dumps(plan.get("value"), ensure_ascii=False, separators=(",", ":"))
        member = str(plan.get("value_type", plan["type"]))
    elif strategy == "static_factory":
        member = str(plan["method_name"])
    elif strategy == "static_field":
        member = str(plan["field_name"])
    row = [
        strategy,
        str(plan["type"]),
        str(plan.get("class_name", "")),
        member,
        ",".join(str(x) for x in plan.get("parameter_types", [])),
        ",".join(str(x) for x in child_ids),
        payload,
    ]
    rows.append(row)
    return len(rows) - 1


def encode_plan(plan: Plan) -> str:
    """Encode a plan for CandidateRunner without requiring a JSON library in Java."""
    rows: list[list[str]] = []
    _flatten_plan(plan, rows)
    raw = "\n".join("\t".join(row) for row in rows)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")
