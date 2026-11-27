# OWUI Agent Bridge

A focused integration project exploring how an Open WebUI Pipe/Manifold can run ACP-based CLI agents through a dedicated Open Terminal host, independently of the Open Terminal machine selected as the chat workspace.

## Goal

Keep the user's normal Open Terminal machine selected in Open WebUI for workspace context, while routing a selected agent (initially Antigravity via `agy acp`) to a dedicated background Open Terminal instance.

The agent host and workspace host are separate concerns. This project must not imply that the agent CLI's filesystem or shell operations execute on the selected workspace machine unless that behavior is explicitly implemented and verified.

## Current status

- Architecture investigation documented in [`docs/architecture-findings.md`](docs/architecture-findings.md).
- No bridge implementation or end-to-end runtime test exists yet.
- The first planned experiment is a text-only ACP turn through a custom Manifold, targeting an explicitly configured dedicated Open Terminal endpoint.

## Architecture at a glance

Open WebUI currently owns the ACP chat adapter: it constructs ACP JSON-RPC requests, manages session prompts and options, translates text/tool/approval updates, and emits chat output. Open Terminal launches provider processes and transports their native JSONL protocol over its REST-created agent sessions and WebSocket transport.

The existing OWUI `MachineTransport` resolves the agent host from the selected machine context. A custom Pipe/Manifold could instead target a configured dedicated agent host, but must explicitly implement or adapt authentication, session state, streaming, cancellation, approvals, and cleanup.

## Documentation

- [Architecture findings and source map](docs/architecture-findings.md)

## Planned proof of concept

1. Add a Manifold model entry for one configured ACP provider/model.
2. Create a session on the dedicated Open Terminal host and connect to its agent WebSocket.
3. Send a minimal text-only ACP sequence and stream returned text to OWUI.
4. Keep the normal workspace machine selected and verify the selection remains unchanged.
5. Test authentication failures, cancellation, reconnect behavior, duplicate turns, session cleanup, and secret handling.
6. Separately determine where filesystem and shell operations execute; do not assume they target the selected workspace host.

## Design constraints

- Do not commit API keys, OAuth tokens, cookies, private URLs, or session transcripts containing sensitive data.
- Bind unauthenticated agent endpoints to loopback or a trusted private network; do not publish them to an untrusted LAN/Internet.
- Preserve Open Terminal session ownership and authentication checks.
- Keep the initial implementation small; defer workspace execution proxying until the ACP/provider behavior is understood.

## Development

This repository is documentation-first at present. There are no build or test commands yet. Add implementation-specific setup and automated tests with the first code contribution.
