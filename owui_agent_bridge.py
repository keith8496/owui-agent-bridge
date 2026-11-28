"""Open WebUI Manifold for Antigravity ACP on a dedicated Open Terminal host.

Targeted at Open WebUI 0.13.5. This initial phase supports discovery and basic
text turns; streaming/session resume and attachment/image parity remain TODO.
"""

import logging
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class Pipe:
    class Valves(BaseModel):
        agent_host_url: str = Field(
            default="http://open-terminal:8000",
            description="Dedicated Open Terminal agent host base URL",
        )
        agent_host_api_key: str = Field(
            default="", description="Open Terminal API key (if configured)"
        )
        user_id: str = Field(default="user", description="Open Terminal owner ID")
        cwd: str = Field(default="/data/workspace", description="Agent-host working directory")
        request_timeout: int = Field(default=60, ge=5, le=600)

    def __init__(self):
        self.valves = self.Valves()

    @staticmethod
    def _base_url(value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Agent host URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Agent host URL must not include credentials, query, or fragment")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    def _headers(self, chat_id: str) -> dict:
        headers = {"X-User-Id": self.valves.user_id or "user", "X-Session-Id": chat_id}
        if self.valves.agent_host_api_key:
            headers["Authorization"] = f"Bearer {self.valves.agent_host_api_key}"
        return headers

    async def _request(self, method: str, path: str, *, chat_id="discovery", **kwargs):
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.valves.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.request(
                method,
                self._base_url(self.valves.agent_host_url) + path,
                headers=self._headers(chat_id),
                **kwargs,
            ) as response:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    data = {}
                if response.status >= 400:
                    detail = data.get("detail") if isinstance(data, dict) else None
                    raise ValueError(detail or f"Agent host returned HTTP {response.status}")
                return data

    async def pipes(self):
        try:
            catalog = await self._request(
                "GET", "/agents", params={"provider": "antigravity", "cwd": self.valves.cwd}
            )
            if catalog.get("protocol_version") != 1:
                return []
            agent = next(
                (item for item in catalog.get("agents", []) if item.get("id") == "antigravity" and item.get("available")),
                None,
            )
            if not agent:
                return []
            result = []
            for model in agent.get("models", []):
                model_id = model.get("id")
                if not isinstance(model_id, str) or not model_id:
                    continue
                result.append(
                    {
                        "id": model_id,
                        "name": f"Antigravity / {model.get('name') or model_id}",
                    }
                )
            return result
        except Exception:
            log.exception("Antigravity model discovery failed")
            return []

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __metadata__: Optional[dict] = None,
        __request__=None,
        __event_emitter__=None,
        __event_call__=None,
    ):
        """Run one ACP turn on the configured host; phase one returns a final message."""
        from open_webui.utils.agents import acp
        from open_webui.models.chats import Chats
        from open_webui.utils.auth import decode_token
        from open_webui.utils.agents.output import Output
        from open_webui.utils.agents.transport import MachineTransport

        body = body or {}
        metadata = dict(__metadata__ or {})
        user = __user__ or {}
        chat_id = metadata.get("chat_id") or metadata.get("session_id")
        message_id = metadata.get("message_id")
        if not chat_id or not message_id:
            raise ValueError("Save this chat before using the Antigravity manifold")
        owui_user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
        owui_user_role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
        if not isinstance(owui_user_id, (str, int)) or not str(owui_user_id).strip():
            raise ValueError("An authenticated Open WebUI user is required")
        if not isinstance(owui_user_role, str) or not owui_user_role.strip():
            raise ValueError("An authenticated Open WebUI user role is required")
        owui_user_id = str(owui_user_id)
        acp_user = type("PipeUser", (), {"id": owui_user_id, "role": owui_user_role})()
        chat = await Chats.get_accessible_chat_by_id(str(chat_id), acp_user, permission="write")
        if chat is None:
            raise ValueError("Chat reply access denied")

        model_id = str(body.get("model", "")).rsplit(".", 1)[-1]
        if not model_id:
            raise ValueError("A base model ID is required")
        allowed = {item["id"] for item in await self.pipes()}
        if model_id not in allowed:
            raise ValueError("The selected Antigravity model is not available on the configured host")

        messages = body.get("messages") or []
        prompt = "\n\n".join(
            f"{str(item.get('role', 'user')).upper()}: {item.get('content', '')}"
            for item in messages
            if isinstance(item, dict) and item.get("content") is not None
        )
        if not prompt.strip():
            raise ValueError("The chat has no text prompt")

        host_url = self._base_url(self.valves.agent_host_url)
        # Reuse OWUI's reconnecting sequenced carrier, overriding only its REST endpoint call.
        pipe = self

        class DirectHostTransport(MachineTransport):
            async def request(self, method, path, body=None):
                return await pipe._request(
                    method, path, chat_id=str(chat_id), **({"json": body} if body is not None else {})
                )
        transport = DirectHostTransport(
            {"url": host_url, "service": "open_terminal"},
            self._headers(str(chat_id)),
            {},
            self.valves.user_id or "user",
        )
        user_message = metadata.get("user_message") or {}
        parent_id = user_message.get("parentId") or metadata.get("user_message_id")
        previous = None
        try:
            messages_by_id = await Chats.get_messages_map_by_chat_id(str(chat_id)) or {}
            visited = set()
            current_id = parent_id
            while current_id and current_id not in visited:
                visited.add(current_id)
                saved = messages_by_id.get(current_id)
                if not saved:
                    break
                token = (saved.get("meta") or {}).get("agent")
                try:
                    state = decode_token(token) if isinstance(token, str) else None
                except Exception:
                    state = None
                if state:
                    if (
                        state.get("typ") == "agent_session"
                        and state.get("chat") == str(chat_id)
                        and state.get("user") == owui_user_id
                        and state.get("instance_user_id") == (self.valves.user_id or "user")
                        and state.get("provider") == "antigravity"
                        and state.get("model") == model_id
                        and state.get("cwd") == self.valves.cwd
                        and isinstance(state.get("session_id"), str)
                        and state["session_id"]
                    ):
                        previous = state
                    break
                current_id = saved.get("parentId")
        except Exception:
            previous = None

        output_metadata = {
            **metadata,
            "chat_id": str(chat_id),
            "message_id": str(message_id),
            "task_id": metadata.get("task_id"),
        }
        output = Output(output_metadata, acp_user, transport.raise_if_failed, body)
        output.state = {
            "provider": "antigravity",
            "model": model_id,
            "cwd": self.valves.cwd,
            "user": owui_user_id,
            "instance_user_id": self.valves.user_id or "user",
            "chat": str(chat_id),
            **({key: previous[key] for key in ("session_id", "model_config") if key in previous} if previous else {}),
        }
        params = body.get("params") or {}
        custom_params = params.get("custom_params") or {}
        reasoning_effort = params.get("reasoningEffort") or params.get("reasoning_effort")
        reasoning_effort = reasoning_effort or custom_params.get("reasoningEffort") or custom_params.get("reasoning_effort")
        if reasoning_effort:
            # Fetch discovery metadata to validate effort against the selected base model.
            catalog = await self._request(
                "GET", "/agents", params={"provider": "antigravity", "cwd": self.valves.cwd}
            )
            discovered = next(
                (agent for agent in catalog.get("agents", []) if agent.get("id") == "antigravity"), {}
            )
            selected = next(
                (item for item in discovered.get("models", []) if item.get("id") == model_id), {}
            )
            supported = {
                item.get("reasoningEffort") for item in selected.get("supportedReasoningEfforts", [])
            }
            if reasoning_effort not in supported:
                raise ValueError("The selected reasoning effort is not supported by this model")
            # Match OWUI's helper: custom params are overlaid on top-level params.
            params = {**params, **custom_params}
            params["reasoning_effort"] = reasoning_effort.strip() if isinstance(reasoning_effort, str) else reasoning_effort

        options = {
            "request_id": str(message_id),
            "cwd": self.valves.cwd,
            "model": model_id,
            "resume": (previous or {}).get("session_id"),
            "instructions": "",
            "approval_mode": "ask",
            "resume_state": previous or {},
            "params": params,
        }
        succeeded = False
        try:
            await transport.start("antigravity", options)
            await acp.run(transport, output, prompt, [], {**options, "resume_state": previous or {}})
            succeeded = True
            return output.content
        finally:
            await transport.close()
            for item in output.items:
                if item.get("status") in {"pending", "in_progress"}:
                    item["status"] = "completed" if succeeded else "incomplete"
            await output.flush(done=True, force=True)


# Keep this module importable in a minimal test environment without OWUI internals.
def _safe_model_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:/-]+", value))
