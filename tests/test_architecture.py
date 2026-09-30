"""Enforces the Clean Architecture dependency rule by inspecting imports.

Allowed direction: api -> agents -> application -> domain <- infrastructure.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# Third-party packages the domain may never depend on (it may use the standard library only).
_FRAMEWORKS = {"fastapi", "pydantic", "pydantic_settings", "langgraph", "langchain_core", "groq", "pandas", "pypdf", "tenacity"}


def _imported_modules(path: Path, src: Path) -> list[str]:
    """All absolute module names imported by *path* (relative imports resolved inside src)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = ".".join(path.relative_to(src.parent).with_suffix("").parts[:-1])
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                modules.append(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                modules.append(node.module)
    return modules


def _violations(layer: str, forbidden_prefixes: tuple[str, ...], src: Path = SRC) -> list[str]:
    found = []
    for path in sorted((src / layer).rglob("*.py")):
        for module in _imported_modules(path, src):
            if module.startswith(forbidden_prefixes) or module.split(".")[0] in forbidden_prefixes:
                found.append(f"{path.relative_to(src.parent)} imports {module}")
    return found


def test_domain_depends_on_nothing_outside_domain() -> None:
    forbidden = ("src.application", "src.agents", "src.infrastructure", "src.api", *_FRAMEWORKS)
    assert _violations("domain", forbidden) == []


def test_application_depends_only_on_domain() -> None:
    forbidden = ("src.agents", "src.infrastructure", "src.api", *_FRAMEWORKS)
    assert _violations("application", forbidden) == []


def test_agents_do_not_depend_on_infrastructure_or_api() -> None:
    assert _violations("agents", ("src.infrastructure", "src.api", "groq", "fastapi")) == []


def test_infrastructure_does_not_depend_on_outer_layers() -> None:
    assert _violations("infrastructure", ("src.application", "src.agents", "src.api")) == []


def test_checker_detects_violations(tmp_path: Path) -> None:
    """Guard against a checker that silently passes everything (absolute and relative imports)."""
    fake_src = tmp_path / "src"
    (fake_src / "application").mkdir(parents=True)
    (fake_src / "application" / "bad.py").write_text(
        "from src.infrastructure.llm.client import GroqClient\nfrom ..agents import graph\n"
    )
    found = _violations("application", ("src.infrastructure", "src.agents"), src=fake_src)
    assert len(found) == 2
