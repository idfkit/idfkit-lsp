"""Tests for the typed reader of the repository's capability declaration.

Every state rule is pinned from the failing side: a declaration that breaks one must stop at load,
because a server that advertises an answer nobody can give is the failure this record exists to
prevent.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from idfkit_lsp.capabilities import CapabilityState, DeclarationError, load

if TYPE_CHECKING:
    from pathlib import Path


def _declaration() -> dict[str, Any]:
    """A minimal declaration that breaks no rule, for a test to break in exactly one way."""
    return {
        "version": 1,
        "servers": [
            {
                "id": "source",
                "runtime": "the first language",
                "documents": [{"language_id": "python", "extensions": [".py"]}],
                "capabilities": [
                    {"request": "textDocument/completion", "state": "present"},
                ],
            },
            {
                "id": "model",
                "runtime": "the second language",
                "documents": [{"language_id": "idf", "extensions": [".idf"]}],
                "capabilities": [
                    {
                        "request": "textDocument/hover",
                        "state": "absent_temporary",
                        "tracked": "the language service",
                    },
                ],
            },
        ],
    }


def _write(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    """Write a declaration under its own name, so no two cases share a cached path."""
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _capability(data: dict[str, Any], server_id: str) -> dict[str, Any]:
    server = next(s for s in data["servers"] if s["id"] == server_id)
    first: dict[str, Any] = server["capabilities"][0]
    return first


class TestValidDeclaration:
    def test_loads(self, tmp_path: Path) -> None:
        declaration = load(_write(tmp_path, "valid", _declaration()))
        assert declaration.version == 1
        assert declaration.source.id == "source"
        assert declaration.model.id == "model"

    def test_request_sets(self, tmp_path: Path) -> None:
        declaration = load(_write(tmp_path, "sets", _declaration()))
        assert declaration.source.present_requests == frozenset({"textDocument/completion"})
        assert declaration.source.absent_requests == frozenset()
        assert declaration.model.absent_requests == frozenset({"textDocument/hover"})

    def test_capability_lookup_returns_none_when_unstated(self, tmp_path: Path) -> None:
        declaration = load(_write(tmp_path, "lookup", _declaration()))
        assert declaration.source.capability("textDocument/definition") is None

    def test_editor_specific_defaults_to_false(self, tmp_path: Path) -> None:
        declaration = load(_write(tmp_path, "editor-default", _declaration()))
        found = declaration.source.capability("textDocument/completion")
        assert found is not None
        assert found.editor_specific is False

    def test_cached_on_resolved_path(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "cached", _declaration())
        assert load(path) is load(path)


class TestStateRules:
    def test_absent_permanent_without_reason(self, tmp_path: Path) -> None:
        data = _declaration()
        _capability(data, "model").update(
            {"state": "absent_permanent", "instead": "the other server", "tracked": None}
        )
        with pytest.raises(DeclarationError, match="absent_permanent states a reason"):
            load(_write(tmp_path, "no-reason", data))

    def test_absent_permanent_without_instead(self, tmp_path: Path) -> None:
        data = _declaration()
        _capability(data, "model").update(
            {"state": "absent_permanent", "reason": "model text is not source", "tracked": None}
        )
        with pytest.raises(DeclarationError, match="names what to use instead"):
            load(_write(tmp_path, "no-instead", data))

    def test_absent_temporary_without_tracked(self, tmp_path: Path) -> None:
        data = _declaration()
        _capability(data, "model").update({"state": "absent_temporary", "tracked": None})
        with pytest.raises(DeclarationError, match="names the tracked item"):
            load(_write(tmp_path, "no-tracked", data))

    @pytest.mark.parametrize("field", ["reason", "instead", "tracked"])
    def test_present_carrying_an_absence_field(self, tmp_path: Path, field: str) -> None:
        data = _declaration()
        _capability(data, "source")[field] = "something"
        with pytest.raises(DeclarationError, match="present carries no reason"):
            load(_write(tmp_path, f"present-{field}", data))

    def test_unknown_state(self, tmp_path: Path) -> None:
        data = _declaration()
        _capability(data, "source")["state"] = "maybe"
        with pytest.raises(DeclarationError, match="state is one of"):
            load(_write(tmp_path, "unknown-state", data))

    def test_error_names_server_and_request(self, tmp_path: Path) -> None:
        data = _declaration()
        _capability(data, "model").update({"state": "absent_temporary", "tracked": None})
        with pytest.raises(DeclarationError) as raised:
            load(_write(tmp_path, "named", data))
        message = str(raised.value)
        assert "'model'" in message
        assert "textDocument/hover" in message


class TestDocumentOwnership:
    def test_two_servers_claiming_one_language_id(self, tmp_path: Path) -> None:
        data = _declaration()
        data["servers"][1]["documents"][0]["language_id"] = "python"
        with pytest.raises(DeclarationError, match="one server per language id"):
            load(_write(tmp_path, "same-language", data))

    def test_two_servers_claiming_one_extension(self, tmp_path: Path) -> None:
        data = _declaration()
        data["servers"][1]["documents"][0]["extensions"] = [".py"]
        with pytest.raises(DeclarationError, match="one server per extension"):
            load(_write(tmp_path, "same-extension", data))


class TestServerSet:
    def test_duplicate_request_within_one_server(self, tmp_path: Path) -> None:
        data = _declaration()
        server = data["servers"][0]
        server["capabilities"].append({"request": "textDocument/completion", "state": "present"})
        with pytest.raises(DeclarationError, match="a request appears once per server"):
            load(_write(tmp_path, "duplicate-request", data))

    def test_fewer_than_two_servers(self, tmp_path: Path) -> None:
        data = _declaration()
        data["servers"] = data["servers"][:1]
        with pytest.raises(DeclarationError, match="two servers are declared"):
            load(_write(tmp_path, "one-server", data))

    def test_unknown_server_id(self, tmp_path: Path) -> None:
        data = _declaration()
        data["servers"][1]["id"] = "sidecar"
        with pytest.raises(DeclarationError, match="a server id is one of"):
            load(_write(tmp_path, "unknown-id", data))

    def test_unknown_server_id_requested(self, tmp_path: Path) -> None:
        declaration = load(_write(tmp_path, "lookup-unknown", _declaration()))
        with pytest.raises(DeclarationError, match="a server id is declared"):
            declaration.server("sidecar")


class TestRepositoryDeclaration:
    def test_root_declaration_loads(self) -> None:
        declaration = load()
        assert {server.id for server in declaration.servers} == {"source", "model"}

    def test_source_server_advertises_completion(self) -> None:
        found = load().source.capability("textDocument/completion")
        assert found is not None
        assert found.state is CapabilityState.PRESENT

    def test_source_server_states_semantic_tokens_permanently_absent(self) -> None:
        found = load().source.capability("textDocument/semanticTokens/full")
        assert found is not None
        assert found.state is CapabilityState.ABSENT_PERMANENT
        assert found.reason
        assert found.instead
