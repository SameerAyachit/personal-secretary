"""Tests for tools/registry.py: SafetyClass, ToolSpec, Registry (plan §8.2, §8.5)."""


from secretary.tools.registry import Registry, SafetyClass, ToolSpec


def test_safety_class_values():
    assert SafetyClass.A == "A"
    assert SafetyClass.B == "B"
    assert SafetyClass.C == "C"


def test_register_and_get():
    reg = Registry()
    spec = ToolSpec(
        name="task_list",
        group="core",
        safety_class=SafetyClass.A,
        description="List tasks",
    )
    reg.register(spec)
    assert reg.get("task_list") is spec
    assert reg.get("nope") is None


def test_list_and_schemas():
    reg = Registry()
    reg.register(ToolSpec(name="task_create", group="core", safety_class=SafetyClass.B, description="Create a task"))
    reg.register(ToolSpec(name="task_list", group="core", safety_class=SafetyClass.A, description="List tasks"))
    reg.register(ToolSpec(name="email_send", group="email", safety_class=SafetyClass.C, description="Send email"))
    names = {s.name for s in reg.list()}
    assert names == {"task_create", "task_list", "email_send"}
    schemas = reg.schemas()
    assert {s["name"] for s in schemas} == names
    # Every schema carries its safety class and group.
    for s in schemas:
        assert "safety_class" in s and "group" in s


def test_class_c_never_auto_executes():
    reg = Registry()
    reg.register(ToolSpec(name="email_send", group="email", safety_class=SafetyClass.C, description="Send email"))
    assert reg.get("email_send").safety_class == SafetyClass.C
