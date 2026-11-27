# OWUI + Open Terminal Agent Bridge Investigation

Status: initial architecture findings; no implementation changes made.

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

## Proposed proof of concept

1. Add a Manifold entry for the chosen agent/model, configured with the dedicated Open Terminal base URL and credentials using a safe server-side mechanism (never embed secrets in the function source or chat-visible model metadata).
2. From the pipe, create an agent session on the dedicated host and connect to its WebSocket.
3. Implement the minimum ACP sequence for one text-only turn: initialize, session/new, model selection if required, session/prompt, consume session/update, return streamed text to OWUI, then clean up.
4. Keep the foreground machine selected and confirm it remains the workspace context.
5. Test lifecycle and safety: auth failures, disconnect/reconnect, cancellation, duplicate turns, session cleanup, and no accidental exposure of agent-host credentials.
6. Separately test where CLI filesystem and shell operations actually execute before claiming workspace sharing.

Possible implementation choice: copy the small required ACP/transport subset into the pipe for a first POC, or import OWUI internals behind a thin adapter. Direct imports reduce duplication but couple the pipe to private APIs and `Output` semantics. Decide after the simplest text-streaming experiment.

## Open questions / risks

- How should pipe-specific credentials and endpoint configuration be stored/rotated in this deployment?
- Should a pipe own provider/model discovery, or use a statically configured model catalog for the POC?
- Which ACP operations/options are required for Antigravity specifically?
- What exact tool operations does `agy acp` execute locally versus delegate to ACP client capabilities?
- Should sessions persist across chat turns, and how will the pipe persist/validate provider session IDs?
- How should approval events and user interaction map to pipe event calls?
- The agent API has session ownership and authentication constraints; preserve them and avoid exposing its port publicly.

## Verification status

- Source code inspected locally in both repositories.
- No files in either repository were modified for this investigation.
- No agent API runtime calls or end-to-end tests were run during this investigation.
- The current note is a working design record, not implementation documentation.
