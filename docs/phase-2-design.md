# Phase Two: Streaming and Session Resume

Status: implementation and mocked regression tests are in place. The full automated suite passes (36 tests). Live acceptance against the deployed Open WebUI 0.13.5 and Open Terminal host is still required; see [Acceptance checklist](#acceptance-checklist).

## Scope and boundaries

Phase two adapts Open WebUI's existing ACP path for Antigravity while routing the carrier to the configured Open Terminal agent host. It adds streamed `Output` events and provider-session continuation. It does not implement a second ACP client or transport protocol. Reasoning-effort selection/validation is inherited from phase one and remains covered by regression tests; it is not a new phase-two feature.

Explicitly out of scope for this phase:

- File attachments, image extraction/base64 conversion, and upload to the agent host. The Pipe currently sends a text prompt and an empty image list.
- Redirecting the agent host's filesystem or shell to the selected workspace machine. The ACP process executes in the configured agent host environment; selecting another workspace machine does not change that.
- A verified guarantee that Stop kills the remote ACP child process. The Pipe closes its OWUI transport and finalizes its output on cancellation, but this code path does not send a separate Open Terminal session DELETE/kill request.

## Design decisions and rationale

- **Reuse OWUI `Output`, `acp.run`, and `MachineTransport`.** This keeps ACP framing, update handling, stream events, session operations, and transport replay/reconnect behavior aligned with OWUI 0.13.5 instead of maintaining a fork. The cost is reliance on private, version-sensitive OWUI internals, so an OWUI upgrade requires rechecking signatures and behavior.
- **Override the transport's REST request to target the configured host.** `MachineTransport.resolve()` is coupled to selected-machine context. Direct construction plus a request override preserves its carrier implementation while removing that machine-resolution dependency. No global monkey-patching is used, avoiding cross-request routing races.
- **Use the OWUI message/request ID for `request_id`; persist only the provider ACP `session_id`.** The request ID identifies a turn; the provider session ID identifies resumable conversation state. Open Terminal carrier sessions are ephemeral transport plumbing, not the provider conversation, so their IDs are not saved for future turns.
- **Authenticate and authorize before transport creation.** Require the actual OWUI user ID and role and check write access to the exact chat. This avoids starting an agent session for missing identity or an inaccessible chat.
- **Keep the two user identities distinct in signed state.** `user` binds saved state to the OWUI principal; `instance_user_id` binds it to the configured Open Terminal owner. On continuation both identities, token type, chat, provider, model, cwd, and a nonempty `session_id` must match. This prevents reusing a signed session across users, chats, hosts, providers, models, or workspaces.
- **Resume only from the authenticated token on the active message ancestry.** Walk parent messages from the current user message and decode OWUI's signed `meta.agent` token. Invalid, missing, or out-of-scope state starts a fresh provider session rather than trusting client-supplied state. Provider resume failure is not automatically retried as a fresh prompt: retrying could execute the same user request twice.
- **Preserve phase-one reasoning-effort handling separately from model IDs.** The picker exposes one entry per base model. Requested effort is accepted from OWUI's supported snake_case/camelCase and nested `custom_params` shapes, checked against the selected model's advertised values, then passed as an ACP parameter. Unsupported values fail before a turn is started. This behavior predates phase two; the tests ensure the streaming/resume changes do not regress it.
- **Finalize success, errors, and cancellation uniformly.** After the ACP call returns successfully, unfinished output items become `completed`; otherwise they become `incomplete`. The `finally` block closes the transport and force-flushes `done=True` so the response lifecycle terminates even on failure/cancellation. Exceptions, including cancellation, continue propagating after cleanup. This mirrors OWUI runner finalization; it is not proof that transport close terminates the remote process.
- **Keep workspace execution semantics explicit.** The Pipe routes ACP traffic to the configured agent host, not to the selected workspace machine. This separation is intentional and prevents claiming remote filesystem/shell behavior that the adapter does not provide.

## Current implementation

`owui_agent_bridge.py` retains a single-file installable Pipe. The phase-two behavior uses OWUI's `Output` for incremental message/reasoning events and signed state, discovers the preceding valid session token, passes the provider session ID in `resume`/`resume_state`, and performs finalization in `finally`.

## Automated test coverage

The mocked tests currently cover:

- Multiple streamed text chunks, accumulated final content, and success finalization.
- Signed-state round trip and resume using a matching user/host/chat/model/provider/workspace scope.
- Fresh-session fallback for invalid tokens and out-of-scope/mismatched identity or state claims.
- Authenticated user/role requirements and rejection when write access to the chat is denied.
- Existing model discovery, dedicated-host routing, text-only prompt construction, and phase-one reasoning-effort input/validation behavior (regression coverage, not newly implemented in phase two).
- ACP exception and cancellation cleanup: transport close, incomplete output status, forced `done=True` flush, and cancellation propagation.

These are unit tests with OWUI and transport stubs. They verify the Pipe's orchestration decisions, not the deployed OWUI event UI, Open Terminal's real reconnect behavior, Antigravity's provider-side persistence, or remote process termination. They also do not cover attachment/image parity.

## Acceptance checklist

Before treating phase two as live-accepted, test in the deployed OWUI/Open Terminal environment:

1. **Incremental rendering:** send a prompt that yields several chunks; confirm chunks appear before the turn completes and the final answer is not duplicated or lost.
2. **Same-chat continuation:** ask a follow-up in the same chat; confirm it resumes the prior Antigravity provider session and retains context.
3. **Isolation:** start another chat and, if available, another OWUI user; confirm neither reuses the first chat's provider session.
4. **Stop behavior:** stop a long-running turn; confirm OWUI marks the response stopped/incomplete and the UI remains usable. Separately inspect Open Terminal for the session/process after Stop. Do not assume Pipe transport close killed it. If the process survives and Stop must terminate it, implement and test an explicit authenticated session-delete/kill path.
5. **Routing invariants:** keep a different workspace machine selected; confirm the Pipe still targets only the configured agent host and does not mutate selected-machine state.
6. **Reasoning-effort regression check:** change effort in OWUI and confirm the supported choice still reaches Antigravity for the selected base model (phase-one behavior).

Phase two can proceed to a controlled live smoke test after deployment, but it is not yet fully accepted. Given the unverified Stop/process boundary and private OWUI API dependency, monitor the first run and inspect the Open Terminal session lifecycle.

## Verification record

- `python -m pytest -q`: 36 passed.
- `python -m py_compile owui_agent_bridge.py tests/test_owui_agent_bridge.py`: passed.
- `git diff --check`: passed.
- Live phase-two acceptance: pending; see checklist above.
