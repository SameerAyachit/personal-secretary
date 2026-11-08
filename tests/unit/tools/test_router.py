"""Tests for tools/router.py: keyword-based tool selection (plan §8.1)."""


from secretary.agent.router import Router
from secretary.tools.registry import Registry, SafetyClass, ToolSpec


def _registry_with_sample_tools():
    reg = Registry()
    for name, group, cls in [
        ("task_create", "core", SafetyClass.B),
        ("task_list", "core", SafetyClass.A),
        ("reminder_create", "core", SafetyClass.B),
        ("email_send", "email", SafetyClass.C),
        ("web_search", "research", SafetyClass.A),
    ]:
        reg.register(ToolSpec(name=name, group=group, safety_class=cls, description=name))
    return reg


def test_router_selects_matching_tools():
    reg = _registry_with_sample_tools()
    router = Router(reg)
    router.route("task_create", ["task", "create", "add"])
    router.route("task_list", ["task", "list", "show"])
    router.route("reminder_create", ["remind", "reminder"])
    router.route("email_send", ["send", "email"])
    router.route("web_search", ["search", "web"])

    tools = router.select("add a task to submit the lab report by Friday", {})
    names = {t.name for t in tools}
    assert "task_create" in names
    assert "email_send" not in names


def test_router_returns_core_tools_on_no_match():
    # Core group is always available (§8.6 routing), so a no-match query still
    # returns core tools rather than an empty list.
    reg = _registry_with_sample_tools()
    router = Router(reg)
    router.route("web_search", ["search", "web"])
    tools = router.select("what is the meaning of life", {})
    names = {t.name for t in tools}
    assert "task_create" in names or "task_list" in names
    assert "web_search" not in names


def test_router_core_group_always_available():
    reg = _registry_with_sample_tools()
    router = Router(reg)
    router.route("task_create", ["task"])
    tools = router.select("hello", {})
    names = {t.name for t in tools}
    assert "task_create" in names or "task_list" in names
