"""Static SSRF guard: core outbound httpx clients must inject a pinned transport."""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "syndicateclaw"

APPROVED_HTTPX_CLIENT_FILES = frozenset(
    {
        Path("connectors/discord/bot.py"),
        Path("connectors/slack/bot.py"),
        Path("connectors/telegram/bot.py"),
        Path("inference/adapters/ollama.py"),
        Path("inference/adapters/openai_compatible.py"),
        Path("inference/catalog_sync/fetch.py"),
    }
)


class _HttpxClientVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.httpx_aliases: set[str] = set()
        self.client_aliases: set[str] = set()
        self.violations: list[tuple[int, str]] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name == "httpx":
                self.httpx_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module == "httpx":
            for alias in node.names:
                if alias.name in {"AsyncClient", "Client"}:
                    self.client_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        client_name = self._httpx_client_call_name(node.func)
        if client_name is not None and not self._has_transport_keyword(node):
            self.violations.append((node.lineno, client_name))
        self.generic_visit(node)

    def _httpx_client_call_name(self, func: ast.expr) -> str | None:
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in self.httpx_aliases
            and func.attr in {"AsyncClient", "Client"}
        ):
            return f"{func.value.id}.{func.attr}"
        if isinstance(func, ast.Name) and func.id in self.client_aliases:
            return func.id
        return None

    @staticmethod
    def _has_transport_keyword(node: ast.Call) -> bool:
        return any(keyword.arg == "transport" for keyword in node.keywords)


def _find_unpinned_httpx_clients(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative in APPROVED_HTTPX_CLIENT_FILES:
            continue
        visitor = _HttpxClientVisitor()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for line, client_name in visitor.violations:
            violations.append(f"{relative}:{line}: {client_name} missing transport=")
    return violations


def test_core_httpx_clients_use_pinned_transport() -> None:
    assert _find_unpinned_httpx_clients(SRC_ROOT) == []


def test_static_gate_catches_synthetic_unpinned_client(tmp_path: Path) -> None:
    package = tmp_path / "syndicateclaw"
    package.mkdir()
    (package / "bad.py").write_text(
        "import httpx\n\nasync def fetch() -> None:\n    httpx.AsyncClient()\n",
        encoding="utf-8",
    )

    assert _find_unpinned_httpx_clients(package) == [
        "bad.py:4: httpx.AsyncClient missing transport="
    ]
