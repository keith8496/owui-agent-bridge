"""Focused unit tests for the Antigravity Manifold boundary."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "owui_agent_bridge.py"
SPEC = importlib.util.spec_from_file_location("owui_agent_bridge", MODULE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class DummyTransport:
    instances = []

    def __init__(self, connection, headers, cookies, user_id):
        self.connection = connection
        self.headers = headers
        self.user_id = user_id
        self.started = None
        self.closed = False
        self.raise_if_failed = lambda: None
        self.__class__.instances.append(self)

    async def start(self, provider, options):
        self.started = (provider, options)

    async def close(self):
        self.closed = True


class DummyOutput:
    def __init__(self, metadata, user, check_connection, form_data):
        self.metadata = metadata
        self.user = user
        self.content = "assistant reply"
        self.state = {}


@pytest.fixture
def owui_stubs(monkeypatch):
    DummyTransport.instances = []
    calls = []

    async def acp_run(transport, output, prompt, images, options):
        calls.append((transport, output, prompt, images, options))

    agents = types.ModuleType("open_webui.utils.agents")
    agents.acp = types.SimpleNamespace(run=acp_run)
    output_module = types.ModuleType("open_webui.utils.agents.output")
    output_module.Output = DummyOutput
    transport_module = types.ModuleType("open_webui.utils.agents.transport")
    transport_module.MachineTransport = DummyTransport

    modules = {
        "open_webui": types.ModuleType("open_webui"),
        "open_webui.utils": types.ModuleType("open_webui.utils"),
        "open_webui.utils.agents": agents,
        "open_webui.utils.agents.output": output_module,
        "open_webui.utils.agents.transport": transport_module,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def catalog(*, protocol=1, available=True, models=None):
    return {
        "protocol_version": protocol,
        "agents": [
            {"id": "antigravity", "available": available, "models": models or []}
        ],
    }


def test_headers_use_configured_multi_user_id():
    pipe = bridge.Pipe()
    pipe.valves.user_id = "agent47"
    pipe.valves.agent_host_api_key = "test-token"

    assert pipe._headers("chat-123") == {
        "X-User-Id": "agent47",
        "X-Session-Id": "chat-123",
        "Authorization": "Bearer test-token",
    }


def test_headers_omit_optional_authorization():
    assert bridge.Pipe()._headers("chat-123") == {
        "X-User-Id": "user",
        "X-Session-Id": "chat-123",
    }


def test_base_url_accepts_http_and_removes_trailing_slash():
    assert bridge.Pipe._base_url(" https://agent.example:8443/acp/ ") == (
        "https://agent.example:8443/acp"
    )


@pytest.mark.parametrize(
    "url", ["agent.example", "ftp://agent.example", "http://user:pass@agent.example", "http://agent.example/?x=1"]
)
def test_base_url_rejects_invalid_or_credential_bearing_urls(url):
    with pytest.raises(ValueError):
        bridge.Pipe._base_url(url)


def test_discovery_returns_base_models_without_effort_variants(monkeypatch):
    pipe = bridge.Pipe()
    requested = []

    async def request(method, path, **kwargs):
        requested.append((method, path, kwargs))
        return catalog(
            models=[
                {
                    "id": "gemini-4-hydrogen",
                    "name": "Hydrogen",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "low"},
                        {"reasoningEffort": "high"},
                    ],
                },
                {"id": "gemini-4-pro", "name": "Pro"},
                {"id": "", "name": "Invalid"},
                {"name": "Missing ID"},
            ]
        )

    monkeypatch.setattr(pipe, "_request", request)

    assert asyncio.run(pipe.pipes()) == [
        {"id": "gemini-4-hydrogen", "name": "Antigravity / Hydrogen"},
        {"id": "gemini-4-pro", "name": "Antigravity / Pro"},
    ]
    assert requested == [
        (
            "GET",
            "/agents",
            {"params": {"provider": "antigravity", "cwd": "/data/workspace"}},
        )
    ]


@pytest.mark.parametrize("response", [catalog(protocol=2), catalog(available=False), {"protocol_version": 1, "agents": []}])
def test_discovery_returns_empty_when_protocol_or_agent_is_unavailable(monkeypatch, response):
    pipe = bridge.Pipe()

    async def request(*args, **kwargs):
        return response

    monkeypatch.setattr(pipe, "_request", request)
    assert asyncio.run(pipe.pipes()) == []


def test_discovery_returns_empty_on_host_failure(monkeypatch):
    pipe = bridge.Pipe()

    async def request(*args, **kwargs):
        raise OSError("host unavailable")

    monkeypatch.setattr(pipe, "_request", request)
    assert asyncio.run(pipe.pipes()) == []


def prepare_pipe(monkeypatch, pipe, models=None):
    async def discovered_models():
        return models or [{"id": "gemini-4-hydrogen", "name": "Antigravity / Hydrogen"}]

    monkeypatch.setattr(pipe, "pipes", discovered_models)


def test_empty_instructions_and_basic_text_turn(owui_stubs, monkeypatch):
    pipe = bridge.Pipe()
    pipe.valves.user_id = "agent47"
    pipe.valves.agent_host_url = "http://agent-host:8000"
    pipe.valves.cwd = "/srv/workspace"
    prepare_pipe(monkeypatch, pipe)

    result = asyncio.run(
        pipe.pipe(
            {
                "model": "antigravity.gemini-4-hydrogen",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            __user__={"id": "owui-user"},
            __metadata__={"chat_id": "chat-123", "message_id": "message-456"},
        )
    )

    transport, output, prompt, images, options = owui_stubs[0]
    assert result == "assistant reply"
    assert transport.connection["url"] == "http://agent-host:8000"
    assert transport.headers["X-User-Id"] == "agent47"
    assert transport.headers["X-Session-Id"] == "chat-123"
    assert transport.user_id == "agent47"
    assert transport.started == ("antigravity", options)
    assert options["request_id"] == "message-456"
    assert options["cwd"] == "/srv/workspace"
    assert options["model"] == "gemini-4-hydrogen"
    assert isinstance(options["instructions"], str) and options["instructions"] == ""
    assert prompt == "USER: Hello"
    assert images == []
    assert transport.closed


def test_unsaved_chat_rejected_before_transport_start(owui_stubs):
    pipe = bridge.Pipe()
    with pytest.raises(ValueError, match="Save this chat"):
        asyncio.run(
            pipe.pipe(
                {"model": "antigravity.model", "messages": [{"role": "user", "content": "Hello"}]},
                __metadata__={"message_id": "message-1"},
            )
        )
    assert owui_stubs == []
    assert DummyTransport.instances == []


def test_unavailable_model_rejected_before_transport_start(owui_stubs, monkeypatch):
    pipe = bridge.Pipe()
    prepare_pipe(monkeypatch, pipe)
    with pytest.raises(ValueError, match="not available"):
        asyncio.run(
            pipe.pipe(
                {"model": "antigravity.unknown", "messages": [{"role": "user", "content": "Hello"}]},
                __metadata__={"chat_id": "chat-1", "message_id": "message-1"},
            )
        )
    assert DummyTransport.instances == []


def test_empty_prompt_rejected_before_transport_start(owui_stubs, monkeypatch):
    pipe = bridge.Pipe()
    prepare_pipe(monkeypatch, pipe)
    with pytest.raises(ValueError, match="no text prompt"):
        asyncio.run(
            pipe.pipe(
                {"model": "antigravity.gemini-4-hydrogen", "messages": []},
                __metadata__={"chat_id": "chat-1", "message_id": "message-1"},
            )
        )
    assert DummyTransport.instances == []


def test_transport_closes_when_acp_turn_raises(owui_stubs, monkeypatch):
    pipe = bridge.Pipe()
    prepare_pipe(monkeypatch, pipe)

    async def failing_acp(*args, **kwargs):
        raise RuntimeError("ACP failed")

    sys.modules["open_webui.utils.agents"].acp.run = failing_acp
    with pytest.raises(RuntimeError, match="ACP failed"):
        asyncio.run(
            pipe.pipe(
                {
                    "model": "antigravity.gemini-4-hydrogen",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                __metadata__={"chat_id": "chat-1", "message_id": "message-1"},
            )
        )
    assert DummyTransport.instances[-1].closed
