from __future__ import annotations

from core.pbobuilder import tools


def test_dependency_junction_does_not_invoke_cmd_for_metacharacter_path(monkeypatch, tmp_path):
    target = tmp_path / "source"
    link = tmp_path / "isolated" / "@Mod&whoami"
    target.mkdir()
    calls = []

    def fake_create(actual_link, actual_target):
        calls.append((actual_link, actual_target))
        return ""

    monkeypatch.setattr(tools.junction, "create", fake_create)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cmd запускаться не должен")),
    )

    assert tools.link_dependency_dir(str(link), str(target), lambda _text: None)
    assert calls == [(link, target)]


def test_dependency_link_reports_both_safe_fallback_errors(monkeypatch, tmp_path):
    target = tmp_path / "source"
    link = tmp_path / "isolated" / "@Mod"
    target.mkdir()
    messages: list[str] = []

    monkeypatch.setattr(tools.junction, "create", lambda _link, _target: "junction denied")
    monkeypatch.setattr(tools.os, "symlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied")))

    assert not tools.link_dependency_dir(str(link), str(target), messages.append)
    assert any("junction denied" in message for message in messages)
    assert any("denied" in message for message in messages)
