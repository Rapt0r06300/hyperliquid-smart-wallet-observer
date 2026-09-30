from hl_observer.skills.optional_registry import OptionalSkillRegistry


def test_optional_skill_broken_dependency_is_unavailable(monkeypatch):
    def broken_find_spec(_module: str):
        raise ValueError("broken module metadata")

    monkeypatch.setattr("hl_observer.skills.optional_registry.importlib.util.find_spec", broken_find_spec)
    reg = OptionalSkillRegistry()
    skill = reg.register("broken", "broken.module")
    assert skill.available is False
    assert reg.unavailable() == ["broken"]
