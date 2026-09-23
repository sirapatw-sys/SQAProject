from __future__ import annotations

import base64
import unittest

import d4j
import evaluate
from construction import ConstructionPlanner, PlannerLimits, encode_plan


def info(
    declaration: str,
    constructors: list[list[str]] | None = None,
    methods: list[dict] | None = None,
    fields: list[dict] | None = None,
) -> dict:
    return {
        "class_decl": declaration,
        "constructors": [
            {
                "descriptor": f"({','.join(parameters)})V",
                "parameter_types": parameters,
            }
            for parameters in (constructors or [])
        ],
        "methods": methods or [],
        "static_fields": fields or [],
    }


class ConstructionPlannerTests(unittest.TestCase):
    def planner(self, types: dict[str, dict], **limits: object) -> ConstructionPlanner:
        return ConstructionPlanner(
            lambda name: types[name],
            PlannerLimits(**limits) if limits else PlannerLimits(),
        )

    def test_builds_recursive_constructor_graph_with_collection(self) -> None:
        types = {
            "example.Parser": info(
                "public class example.Parser",
                [["example.Config", "java.util.List"]],
            ),
            "example.Config": info(
                "public class example.Config",
                [["int", "java.lang.String"]],
            ),
        }
        plan = self.planner(types).plan("example.Parser")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["strategy"], "constructor")
        self.assertEqual(plan["arguments"][0]["class_name"], "example.Config")
        self.assertEqual(plan["arguments"][1]["class_name"], "java.util.ArrayList")
        self.assertEqual(plan["arguments"][0]["arguments"][0]["value"], 0)

    def test_detects_cycle_without_recursing_forever(self) -> None:
        types = {
            "example.A": info("public class example.A", [["example.B"]]),
            "example.B": info("public class example.B", [["example.A"]]),
        }
        planner = self.planner(types)
        self.assertIsNone(planner.plan("example.A"))
        self.assertEqual(planner.failures["example.A"], "cycle_detected")

    def test_abstract_type_can_use_static_factory(self) -> None:
        types = {
            "example.Service": info(
                "public abstract class example.Service",
                methods=[{
                    "name": "create",
                    "return_type": "example.Service",
                    "parameter_types": ["java.lang.String"],
                    "descriptor": "(Ljava/lang/String;)Lexample/Service;",
                    "declaration": "public static example.Service create(java.lang.String);",
                }],
            ),
        }
        plan = self.planner(types).plan("example.Service")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["strategy"], "static_factory")
        self.assertEqual(plan["method_name"], "create")

    def test_abstract_type_can_select_bounded_concrete_subtype(self) -> None:
        types = {
            "example.Service": info("public abstract class example.Service"),
            "example.ServiceImpl": info("public class example.ServiceImpl", [[]]),
        }
        planner = ConstructionPlanner(
            lambda name: types[name],
            find_concrete_subtypes=lambda name: ["example.ServiceImpl"] if name == "example.Service" else [],
        )
        plan = planner.plan("example.Service")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["class_name"], "example.ServiceImpl")
        self.assertEqual(plan["requested_type"], "example.Service")

    def test_singleton_field_beats_more_expensive_factory(self) -> None:
        types = {
            "example.Singleton": info(
                "public class example.Singleton",
                constructors=[["java.lang.String"]],
                fields=[{"type": "example.Singleton", "name": "INSTANCE"}],
            ),
        }
        plan = self.planner(types).plan("example.Singleton")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["strategy"], "static_field")

    def test_depth_limit_rejects_deep_graph(self) -> None:
        types = {
            "A": info("public class A", [["B"]]),
            "B": info("public class B", [["C"]]),
            "C": info("public class C", [[]]),
        }
        self.assertIsNone(self.planner(types, max_depth=1).plan("A"))

    def test_wire_format_is_postorder_and_source_is_compilable_shape(self) -> None:
        plan = {
            "strategy": "constructor",
            "type": "example.Config",
            "class_name": "example.Config",
            "parameter_types": ["int", "java.util.List"],
            "arguments": [
                {"strategy": "literal", "type": "int", "value_type": "int", "value": 0, "cost": 1},
                {"strategy": "constructor", "type": "java.util.List", "class_name": "java.util.ArrayList", "parameter_types": [], "arguments": [], "cost": 2},
            ],
            "cost": 6,
        }
        raw = base64.b64decode(encode_plan(plan)).decode("utf-8")
        rows = raw.splitlines()
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[-1].startswith("constructor\texample.Config"))
        self.assertEqual(
            evaluate.construction_java_expression(plan),
            "new example.Config(0, new java.util.ArrayList())",
        )

    def test_non_static_inner_class_uses_enclosing_instance_syntax(self) -> None:
        outer = {
            "strategy": "constructor", "type": "example.Outer",
            "class_name": "example.Outer", "parameter_types": [],
            "arguments": [], "cost": 3,
        }
        plan = {
            "strategy": "constructor", "type": "example.Outer$Inner",
            "class_name": "example.Outer$Inner",
            "parameter_types": ["example.Outer", "int"],
            "arguments": [
                outer,
                {"strategy": "literal", "type": "int", "value_type": "int", "value": 0, "cost": 1},
            ],
            "cost": 7,
        }
        self.assertEqual(
            evaluate.construction_java_expression(plan),
            "new example.Outer().new Inner(0)",
        )

    def test_setup_step_embeds_recursive_plan(self) -> None:
        plan = {
            "strategy": "constructor", "type": "example.Helper",
            "class_name": "example.Helper", "parameter_types": [],
            "arguments": [], "cost": 3,
        }
        encoded = evaluate.encode_setup_step({
            "name": "setHelper",
            "parameter_types": ["example.Helper"],
            "arguments": [{"kind": "plan", "type": "example.Helper", "plan": plan}],
        })
        raw = base64.b64decode(encoded).decode("utf-8")
        self.assertTrue(raw.startswith("setHelper\texample.Helper\tP:"))


class D4JParsingTests(unittest.TestCase):
    def test_extracts_public_static_fields(self) -> None:
        text = """
public class example.Singleton {
  public static final example.Singleton INSTANCE;
  public static int COUNT;
  public final example.Singleton ignored;
}
"""
        fields = d4j.parse_public_static_fields(text)
        self.assertEqual(
            [(field["type"], field["name"]) for field in fields],
            [("example.Singleton", "INSTANCE"), ("int", "COUNT")],
        )


if __name__ == "__main__":
    unittest.main()
