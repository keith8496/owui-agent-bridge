# OWUI + Open Terminal Agent Bridge

Status: Phase one is implemented and user-smoke-tested: dynamic model discovery, basic text turns, and chat-selected reasoning effort routed to the configured host. Automated tests cover effort input formats and validation. Streaming/resume and attachment/image parity remain future milestones.

## Agreed implementation requirements

- Ship the final deliverable as one installable Python Open WebUI Pipe/Manifold file.
- Target Open WebUI 0.13.5.
- Expose ACP agent models in the regular OWUI model picker and route their requests to a configured dedicated Open Terminal agent host, regardless of which workspace machine remains selected in the chat UI.
- Use a thin adapter around OWUI's existing ACP implementation. Prefer importing/calling its existing logic; keep copied code to the minimum needed to bridge the Pipe to the dedicated host. Expect private internal APIs to be version-sensitive; the phase-one implementation was checked against OWUI 0.13.5 signatures.
- Configure the agent-host URL and API key using Pipe Valves. Include a user ID Valve only if the host/API requires it; default it to `user`.
- Discover models from the agent host and expose them through the Manifold's dynamic model list (`pipes()`). Keep base model IDs separate from reasoning effort; do not create picker IDs by concatenating effort, for example `gemini-3-high`. OWUI-selected effort is read from request params and passed to ACP config-option handling.
- Follow the existing OWUI ACP implementation for supported chat behavior, session semantics, authentication/ownership expectations, event handling, cancellation, and cleanup. The desired end state is feature-to-feature parity, not a permanently text-only replacement.

### Delivery milestones

1. **Conversation proof and model discovery:** discover agent models and complete a basic turn through the dedicated host.
2. **Streaming and chat resume:** match the existing ACP stream and resume behavior.
3. **Attachments and images:** match the existing attachment/image path, including base64 image content where applicable.

These milestones sequence implementation and verification; they do not reduce the final parity goal. Verify the actual Pipe and ACP integration against OWUI 0.13.5 and the deployed Open Terminal agent API.

### Execution boundary

The Pipe redirects the ACP agent transport, not the workspace machine's shell or filesystem. The CLI process and its native filesystem/shell operations run on the dedicated agent host unless a separate, explicit remote-workspace mechanism is added and verified. Keeping the normal workspace machine selected does not imply that the agent operates inside it.

## Goal

Use an agent CLI (initially Antigravity/`agy`) running in a dedicated background Open Terminal instance while keeping the user's normal foreground Open Terminal machine selected in Open WebUI for the chat workspace.

Desired separation:

- Agent host: owns CLI installation, credentials, process, and agent session.
- Workspace machine: remains the selected Open WebUI machine for files, shell, and terminal UI.

This note records the current code-trace findings and a proposed next experiment. It is not a claim that the desired behavior has been runtime-tested.

## Key conclusion

The ACP conversation adapter is primarily in Open WebUI, not Open Terminal. OWUI constructs ACP JSON-RPC requests and interprets ACP responses. Open Terminal launches the CLI process and transports its native JSONL protocol over its agent session API.

No OpenAI-compatible chat-completions endpoint was found in the inspected Open Terminal source/docs. Its agent interface is custom REST plus JSON-over-WebSocket transport.

## End-to-end flow

```text
Open WebUI chat request
  -> backend/open_webui/utils/agents/runner.py
     chooses provider adapter and prepares prompt/options
  -> backend/open_webui/utils/agents/acp.py
     ACP initialize/session/prompt; handles updates, permissions, cancellation
  -> backend/open_webui/utils/agents/transport.py
     POST /agents/{provider}/sessions
     WS /agents/sessions/{id}/connect
  -> Open Terminal open_terminal/agents/router.py
     starts CLI, forwards JSONL input to stdin and stdout as output frames
  -> CLI (e.g. `agy acp`)
```

Responses and session updates travel back through the same path, where OWUI maps them to chat output/events.

## Evidence by repository

### Open WebUI

Repository inspected: `/home/u7de088ca/Repos/open-webui`.

- `backend/open_webui/utils/agents/runner.py`
  - Provider dispatch maps Antigravity and several other providers to `acp.run`; Codex and Claude Code have provider-specific adapters.
  - `run(...)` prepares prompt, attachments, options and state, resolves `MachineTransport`, starts it, then invokes the provider adapter.
- `backend/open_webui/utils/agents/acp.py`
  - `Client` serializes JSON-RPC messages as newline-delimited JSON over an abstract transport.
  - `run(...)` performs ACP `initialize`, starts/resumes/loads a session, selects model/reasoning configuration, and sends `session/prompt`.
  - Handles `session/update` message/reasoning chunks, tool-call updates and plans; responds to permission and elicitation requests; sends cancellation when requested.
- `backend/open_webui/utils/agents/transport.py`
  - `MachineTransport.resolve(...)` resolves the machine using request/user/chat metadata. This is the current machine coupling point.
  - Creates the agent session by REST and maintains the WebSocket bridge, sequencing, acknowledgements, replay/reconnect, and cleanup.
- `backend/open_webui/functions.py`
  - Pipe/Manifold functions can receive selected injected context by declaring parameters (including metadata, request, user, and event helpers where available).
  - Pipe route supports streamed return values. A pipe must implement its own agent endpoint authentication, session lifecycle, and protocol client; generic machine-agent endpoint discovery/credential forwarding is not implied.

### Open Terminal

Repository inspected: `/home/u7de088ca/Repos/open-terminal`.

- `open_terminal/agents/router.py`
  - REST routes create, inspect, and delete agent sessions.
  - WebSocket `/agents/sessions/{sid}/connect` accepts authenticated `auth`, sequenced `input`, `ack`, and `eof` frames; sends sequenced `output` and exit information.
  - Incoming protocol text is validated as JSONL and written to the child process stdin.
- `open_terminal/agents/sessions.py`
  - Selects provider adapters and starts native CLI child processes with stdin/stdout pipes.
- `open_terminal/agents/acp.py`
  - ACP model discovery implementation. This is distinct from OWUI's ACP chat-turn adapter.
- Provider adapters vary: some use ACP; Codex, Claude Code, and Pi have native protocol handling.
- Agent routes are intentionally not exposed in generated API schema in the inspected router.
- Source/docs search found no OpenAI-compatible `/v1/chat/completions` implementation in Open Terminal. This is a source search result, not proof about external proxies or uninspected deployment components.

## Why the current selection constrains this

OWUI's `MachineTransport.resolve(...)` resolves the machine for the current request, and the agent model discovery/request validation path associates agent availability with that machine. Thus, two configured Open Terminal connections do not by themselves provide independent agent-host and workspace-machine routing.

A custom pipe can potentially avoid this coupling by explicitly targeting the dedicated agent host, while the chat remains associated with the foreground workspace machine. This still needs a proof of concept; availability of the pipe interface does not automatically make it an ACP or Open Terminal agent client.

## Workspace semantics and limitation

Separating agent-host routing from the selected workspace is not the same as making the CLI operate on the foreground machine's filesystem/shell.

- The CLI process runs on the dedicated agent host.
- OWUI's ACP `initialize` advertises its filesystem and terminal client capabilities as false in the inspected implementation.
- Therefore, do not assume Antigravity's native filesystem/terminal operations are remotely redirected to the foreground Open Terminal.
- Shared mounts can share files but commands still execute in the agent host environment.
- Routing workspace operations remotely would be a separate integration, dependent on actual provider behavior and ACP tool semantics.

## Verified source signatures and adapter boundary

Open WebUI source was verified in `/home/u7de088ca/Repos/open-webui` at tag `v0.13.5`, commit `926f826eaef6179c092a936eede6c7363e425975`.

- `backend/open_webui/utils/agents/acp.py`: `Client(transport, handle)` consumes `transport.write(str)` and `transport.read_messages()` (an async iterator of decoded JSON-RPC dictionaries). `async run(transport, output, prompt, images, options, *, auth_method=None)` implements ACP initialization, sessions, model/reasoning selection, prompt updates, approvals, elicitation, and cancellation.
- `backend/open_webui/utils/agents/transport.py`: `MachineTransport(connection, headers, cookies, user_id)` is directly constructible; `start(provider, options)`, `write(data)`, `read_messages()`, `close()`, and `end_input()` form its useful carrier API. `resolve(request, user, metadata)` is machine-bound and unsuitable for the configured-host route.
- `backend/open_webui/utils/agents/output.py`: `Output(metadata, user, check_connection, form_data)` persists output cards and agent session state, emits chat completion events, and supplies ACP approval/elicitation interactions. Its use from a Pipe is version-sensitive and must be exercised in OWUI.
- `backend/open_webui/utils/agents/runner.py`: `async run(request, form_data, user, metadata, model)` is not a transport-injection seam. It resolves the selected machine, obtains its cwd, uploads files to it, builds transcript/resume state, and orchestrates output/cleanup. Calling the runner would retain workspace coupling even if the ACP transport were independently redirected.
- `backend/open_webui/utils/agents/discovery.py`: `async get_models(request, user, metadata, *, provider=None, cwd=None)` requires machine metadata and therefore is not usable for independent host discovery.
- `backend/open_webui/functions.py`: manifold `pipes()` may be synchronous or async and yields child IDs/names; Pipe invocation receives selected context keys including `body`, `__user__`, `__metadata__`, `__request__`, `__event_emitter__`, `__event_call__`, `__files__`, and chat/session/message IDs.

The narrowest suitable reuse boundary is constructing a `MachineTransport` instance against an explicit connection/configuration, then using OWUI `Output` and `acp.run` directly. Do not monkey-patch global runner or transport functions: concurrent requests could cross-route. A Pipe-owned orchestration path is needed for chat/session setup, because `runner.run` also couples cwd and attachments to the selected workspace machine. Keep phase one deliberately small and state its limitations; later phases must add compatible saved-chat resume, streaming, and attachment/image behavior before claiming parity.

## Verified Open Terminal API

Local source is at `/home/u7de088ca/Repos/open-terminal`; no runtime API request was made.

- `GET /agents?provider=antigravity&cwd=...` returns `protocol_version: 1` and agents with `id`, `name`, `available`, `models`, and optional errors. Model objects include base `id`, display `name`, and `supportedReasoningEfforts`; effort must remain an option and must not be concatenated into picker IDs.
- Discovery launches the provider CLI and performs ACP `initialize` plus `session/new`; it is not a separate ACP-specific HTTP endpoint.
- `POST /agents/antigravity/sessions` accepts a `Start` body with required `request_id`, plus `cwd`, `model`, `resume`, `resume_at`, `fork`, `instructions`, and `approval_mode`. It returns session ID and lifecycle metadata.
- REST endpoints use bearer authentication when configured. Creation requires `X-Session-Id`; ownership is keyed by `X-User-Id` (default `single`) and session ID. WebSocket authentication is an initial JSON frame containing `type=auth`, token, and cursor.
- WebSocket frames carry sequenced JSONL in `input` and `output`, with acknowledgements, EOF, and exit frames. The OWUI `MachineTransport` already implements replay, reconnect, sequencing, and cleanup; it should be reused rather than duplicated where its configuration permits.

## Implementation investigation and plan

The intended interception point is the boundary where OWUI's ACP adapter sends protocol traffic through `MachineTransport`. The Manifold should preserve OWUI's prompt/session/update behavior and replace only the transport resolution/connection so ACP frames go to the configured dedicated Open Terminal host rather than the selected machine.

Before coding, inspect the exact Open WebUI 0.13.5 implementations and signatures for:

- `backend/open_webui/utils/agents/acp.py`: ACP client, initialization, prompt, updates, approvals/elicitation, cancellation, and session continuation.
- `backend/open_webui/utils/agents/runner.py`: provider/model dispatch and preparation of prompt, options, attachments, and state.
- `backend/open_webui/utils/agents/transport.py`: session creation, authenticated WebSocket connection, sequencing, acknowledgements, reconnect, and cleanup; identify the smallest substitutable transport seam.
- Manifold `pipes()` and Pipe invocation context on OWUI 0.13.5, including Valve configuration and how dynamic model IDs/options are passed to a request.
- Open Terminal's provider model-discovery and session endpoints, confirming their behavior for `agy` ACP.

Prefer calling/importing OWUI code behind the Pipe adapter. If a private function depends on machine-specific request state or cannot accept a substituted transport, copy only the smallest necessary portion and document its upstream source/version. Do not reimplement ACP parsing or event semantics wholesale.

Implement and verify in the agreed phases:

1. Dynamic model discovery plus a basic conversation turn.
2. Incremental streaming and chat resume/session continuation.
3. File attachments and image pipeline/base64 handling.

At each phase confirm the foreground workspace selection is unchanged, requests reach only the configured agent host, ACP model and effort remain separate, cancellation/cleanup remain consistent with OWUI, and failures do not leak credentials. Final acceptance is feature parity with the supported existing ACP path, not merely the phase-one proof.

## Remaining implementation checks

- Exercise effort changes live in OWUI chat settings and confirm the selected value reaches the agent's `thought_level` config option across model changes.
- Implement streaming and saved-session resume parity; the current phase-one Pipe returns the final response and starts a fresh agent session for each turn.
- Add attachment and image support, including base64 payloads where required by the ACP path.
- In the live deployment, confirm cancellation/cleanup and verify filesystem/shell execution location; do not infer remote workspace access from routing or shared files.

## Verification status

- Open WebUI source signatures were inspected against tag `v0.13.5`; Open Terminal protocol details were checked in the local source.
- The single-file phase-one implementation is `owui_agent_bridge.py`; it dynamically discovers available Antigravity base models, uses Valve-configured host/key/user ID, and calls OWUI's ACP runner and reconnectable carrier.
- `tests/test_owui_agent_bridge.py` covers discovery, config/routing, session payload, basic text turn, input rejection, cleanup, and reasoning-effort snake_case/camelCase plus nested `custom_params` handling. Unit tests pass; the user also reports a successful smoke test in their OWUI/Open Terminal instance.
- Phase one does not yet provide streaming/resume parity or file/image attachment support. Do not treat it as full feature parity.
