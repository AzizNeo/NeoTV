"""Architecture fitness functions — the puzzle rules, executable.

These fail with a message that says *what* rule broke and *where*, so a new
module (or a refactor) cannot silently erode the architecture.
"""

from __future__ import annotations

import ast
import re

import pytest
from flask import Flask

from app.kernel.errors import DisabledDependencyError
from app.kernel.http.endpoint import EndpointDoc
from app.kernel.http.errors import ErrorMap
from app.kernel.registry import load_manifests
from app.kernel.settings import PROJECT_ROOT
from app.modules import INSTALLED_MODULES
from tests.support.factory import make_app

MODULES_DIR = PROJECT_ROOT / "app" / "modules"
UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
GENERIC_CODES = {"VALIDATION_FAILED", "RATE_LIMITED", "INTERNAL_ERROR", "NOT_FOUND", "METHOD_NOT_ALLOWED"}


@pytest.fixture(scope="module")
def full_app() -> Flask:
    return make_app(schema="none")


def _endpoint_docs(app: Flask) -> dict[str, EndpointDoc]:
    docs = {}
    for rule in app.url_map.iter_rules():
        view = app.view_functions[rule.endpoint]
        doc = getattr(view, "__endpoint_doc__", None)
        if doc is not None:
            docs[f"{','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))} {rule.rule}"] = doc
    return docs


def _statically_raised_codes() -> set[str]:
    """Codes raised directly (ApiError("X"), Deny("X"), TokenInvalidError("X"), …) anywhere in app/."""
    codes: set[str] = set()
    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in {
                "ApiError",
                "Deny",
                "TokenInvalidError",
                "error_response",
            }:
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    codes.add(first.value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in GENERIC_CODES:
                codes.add(node.value)
    return codes


def test_every_module_directory_is_installed_or_the_template() -> None:
    on_disk = {p.parent.name for p in MODULES_DIR.glob("*/manifest.py")}
    installed = {m.rsplit(".", 1)[-1] for m in INSTALLED_MODULES}
    stray = on_disk - installed - {"_template"}
    assert not stray, f"module folders not in INSTALLED_MODULES (dead code or forgotten registration): {sorted(stray)}"


def test_manifests_are_complete_and_namespaced() -> None:
    for manifest in load_manifests(INSTALLED_MODULES):
        package = MODULES_DIR / manifest.name
        assert SEMVER.match(manifest.version), f"{manifest.name}: version must be semver"
        assert manifest.description.strip(), f"{manifest.name}: description is required"
        assert (package / "api.py").exists() or not manifest.provides, (
            f"{manifest.name}: provides capabilities but has no public api.py"
        )
        for exc, (status, code) in manifest.error_map.items():
            assert UPPER_SNAKE.match(code), f"{manifest.name}: error code {code!r} must be UPPER_SNAKE"
            assert 400 <= status <= 599, f"{manifest.name}: {exc.__name__} maps to non-error status {status}"
        for route in manifest.routes:
            assert route.url_prefix.startswith("/api/v1/"), f"{manifest.name}: routes live under /api/v1/"
        for name in manifest.beat_schedule:
            assert name.startswith(f"{manifest.name}."), f"{manifest.name}: beat entry {name!r} not namespaced"


def test_celery_task_names_are_namespaced(full_app: Flask) -> None:
    installed = {m.rsplit(".", 1)[-1] for m in INSTALLED_MODULES}
    celery = full_app.extensions["celery"]
    for task_name in celery.tasks:
        if task_name.startswith("celery."):
            continue
        owner = task_name.split(".", 1)[0]
        assert owner in installed | {"kernel"}, f"task {task_name!r} is not namespaced by its module"


def test_documented_error_codes_exist(full_app: Flask) -> None:
    error_map: ErrorMap = full_app.extensions["container"].resolve(ErrorMap)
    known = {entry["code"] for entry in error_map.describe().values()} | _statically_raised_codes()
    problems = [
        f"{route}: documents {code!r} which nothing can raise"
        for route, doc in _endpoint_docs(full_app).items()
        for code in doc.errors
        if code not in known
    ]
    assert not problems, "\n".join(problems)


def test_every_api_route_goes_through_endpoint(full_app: Flask) -> None:
    docs = _endpoint_docs(full_app)
    bare = [
        rule.rule
        for rule in full_app.url_map.iter_rules()
        if rule.rule.startswith("/api/v1/")
        and not any(rule.rule in key for key in docs)
        and not rule.rule.startswith(("/api/v1/health", "/api/v1/kernel/metrics"))
    ]
    assert not bare, f"routes bypassing @endpoint (no auth/validation/contract): {bare}"


@pytest.mark.parametrize(
    "module", ["recommendations", "library", "drm", "admin", "billing", "devices", "live", "titles"]
)
def test_optional_modules_can_be_switched_off(module: str) -> None:
    app = make_app(schema="none", disabled_modules=[module])
    assert module not in app.extensions["modules"]


@pytest.mark.parametrize(
    ("module", "dependant"), [("playback", "catalog"), ("profile", "catalog"), ("identity", "kernel")]
)
def test_required_providers_cannot_be_switched_off(module: str, dependant: str) -> None:
    with pytest.raises(DisabledDependencyError, match=dependant):
        make_app(schema="none", disabled_modules=[module])


def test_shared_kernel_has_no_framework_imports() -> None:
    forbidden = ("flask", "sqlalchemy", "celery", "redis", "requests", "pydantic", "app.kernel", "app.modules")
    for path in (PROJECT_ROOT / "app" / "shared_kernel").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            for name in names:
                assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_openapi_contract_is_current() -> None:
    import json

    from app.kernel.http.openapi import build_openapi
    from tools.openapi_app import app

    committed = json.loads((PROJECT_ROOT / "openapi" / "openapi.json").read_text(encoding="utf-8"))
    with app.app_context():
        assert build_openapi(app) == committed, "openapi/openapi.json is stale: python -m tools.devctl openapi"


def test_template_scaffold_produces_a_bootable_module() -> None:
    """`flask kernel new-module` output must boot as-is (the template never rots).

    Booted in a subprocess: importing the probe's models into this process
    would leak its table into the shared metadata of every later test."""
    import shutil
    import subprocess
    import sys
    import textwrap

    from app.kernel.cli import scaffold_module

    name = "zz_scaffold_probe"
    target = scaffold_module(name)
    try:
        assert (target / "manifest.py").read_text(encoding="utf-8").count(f'name="{name}"') == 1
        probe = textwrap.dedent(f"""
            from app.modules import INSTALLED_MODULES
            from tests.support.factory import make_app
            app = make_app(installed=[*(m.rsplit(".", 1)[-1] for m in INSTALLED_MODULES), "{name}"])
            assert "{name}" in app.extensions["modules"]
            assert app.test_client().get("/api/v1/{name}/items").status_code == 401
            print("BOOTED")
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120, check=False
        )
        assert "BOOTED" in result.stdout, result.stderr[-3000:]
    finally:
        shutil.rmtree(target, ignore_errors=True)
