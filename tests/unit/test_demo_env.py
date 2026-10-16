"""tools.demo_env — the Docker demo's generated secrets."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from app.modules.identity.domain import validate_password
from tools import demo_env


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_env, "STATE", tmp_path)
    monkeypatch.setattr(demo_env, "FILE", tmp_path / "demo.env")
    return tmp_path / "demo.env"


def test_init_generates_once_and_keeps_values(state, capsys):
    assert demo_env.main(["init"]) == 0
    first = demo_env.read()
    assert set(first) == {"SECRET_KEY", "NEOTV_ADMIN_PASSWORD"}
    assert len(first["SECRET_KEY"]) >= 32
    assert demo_env.main(["init"]) == 0  # second start: same keys, sessions stay valid
    assert demo_env.read() == first
    assert "kept" in capsys.readouterr().out
    if os.name == "posix":
        assert stat.S_IMODE(state.stat().st_mode) == 0o600


def test_init_fills_only_what_is_missing(state):
    state.write_text("SECRET_KEY=" + "k" * 40 + "\n", encoding="utf-8")
    demo_env.init()
    values = demo_env.read()
    assert values["SECRET_KEY"] == "k" * 40
    assert values["NEOTV_ADMIN_PASSWORD"]


@pytest.mark.parametrize("_", range(20))
def test_generated_password_satisfies_the_policy(_):
    validate_password(demo_env._password(), username=demo_env.ADMIN)  # raises if weak


def test_exec_injects_the_file_but_explicit_env_wins(state, monkeypatch):
    state.write_text("SECRET_KEY=from-file-" + "x" * 30 + "\nNEOTV_ADMIN_PASSWORD=p\n", encoding="utf-8")
    monkeypatch.setenv("NEOTV_ADMIN_PASSWORD", "explicit")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    seen = {}
    monkeypatch.setattr(os, "execvp", lambda file, argv: seen.update(file=file, argv=argv))
    demo_env.main(["exec", "--", sys.executable, "-V"])
    assert seen == {"file": sys.executable, "argv": [sys.executable, "-V"]}
    assert os.environ["SECRET_KEY"].startswith("from-file-")
    assert os.environ["NEOTV_ADMIN_PASSWORD"] == "explicit"


def test_exec_without_secrets_names_the_missing_step(state, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(SystemExit, match="'secrets' service must run first"):
        demo_env.main(["exec", "--", "true"])


def test_banner_shows_url_user_and_password(state, monkeypatch, capsys):
    state.write_text("NEOTV_ADMIN_PASSWORD=Neo-abc-12tv!\n", encoding="utf-8")
    monkeypatch.delenv("NEOTV_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:9090")
    demo_env.main(["banner"])
    out = capsys.readouterr().out
    assert "http://localhost:9090" in out and "Neo-abc-12tv!" in out and demo_env.ADMIN in out


def test_setup_stops_on_a_failed_step_and_tmdb_is_optional(state, monkeypatch, capsys):
    calls: list[tuple[str, ...]] = []

    def fake_run(cmd, check):
        calls.append(tuple(cmd[2:]))
        return type("R", (), {"returncode": 1 if cmd[2:] == ["tools.seed_demo", "--tmdb"] else 0})()

    monkeypatch.setattr(demo_env.subprocess, "run", fake_run)
    monkeypatch.setenv("NEOTV_ADMIN_PASSWORD", "x")
    monkeypatch.setenv("TMDB_READ_TOKEN", "t")
    assert demo_env.setup() == 0  # TMDB failing does not fail the demo
    assert calls[1:] == [("tools.seed_demo",), ("tools.seed_demo", "--tmdb")]
    assert "import incomplete" in capsys.readouterr().out

    calls.clear()
    monkeypatch.setattr(demo_env.subprocess, "run", lambda cmd, check: type("R", (), {"returncode": 1})())
    assert demo_env.setup() == 1  # admin creation failed → stop, no seed
