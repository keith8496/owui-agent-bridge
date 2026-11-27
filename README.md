# OWUI Agent Bridge

A single-file Open WebUI Pipe Manifold that exposes ACP agents running on a dedicated Open Terminal host as selectable models in regular Open WebUI chat.

## Goal

Keep the user's normal Open Terminal machine selected in Open WebUI while the Manifold routes agent conversations to a separate, configured Open Terminal agent host. The Pipe replaces the selected-machine attachment at OWUI's agent transport boundary; it does not replace the normal chat UI or require a separate bridge service.

The initial provider is Antigravity through `agy` ACP. ACP requests and responses should use Open WebUI's existing agent implementation wherever practical. The Manifold should be a thin adapter that imports and calls OWUI internals; copied code should be kept to the minimum required to bridge transport/configuration differences.

## Requirements

- Final deliverable: one installable Python Pipe/Manifold file.
- Target Open WebUI version: 0.13.5.
- The Manifold exposes agent models in the regular OWUI model picker.
- Agent host URL and API key are configured through Pipe Valves. A user ID Valve may be provided when required, defaulting to `user`.
- The Manifold discovers available models from the agent host and returns them through its dynamic model list (`pipes()`). Discovery must retain the provider's base model name and represent effort separately; do not synthesize picker IDs such as `gemini-3-high`.
- Chat behavior should match the existing OWUI ACP implementation, reusing its supported prompt handling, streaming, session behavior, attachments, events, cancellation, and cleanup rather than defining a parallel protocol contract.
- Agent-host routing is independent of the currently selected workspace machine.

## Delivery phases

1. **Conversation proof and discovery:** expose discovered agent models and complete a basic chat turn through the dedicated host.
2. **Streaming and resume:** stream output and continue/resume chat sessions consistently with OWUI's existing ACP path.
3. **Attachments and images:** pass supported file attachments and image content through the existing OWUI/ACP pipeline, including base64 image data where the protocol path requires it.

These are implementation milestones, not a reduced final feature contract. The target is feature parity with the existing OWUI ACP agent path, verified against version 0.13.5 and the Open Terminal endpoint.

## Important execution boundary

Routing an ACP conversation to the dedicated host does not automatically make the CLI's filesystem or shell operations run on the selected workspace machine. The CLI executes on the agent host. Do not claim workspace execution or file access unless it is separately implemented and verified.

## Documentation

- [Architecture findings, implementation direction, and verification plan](docs/architecture-findings.md)

## Development status

Documentation and source investigation only; no Manifold implementation or runtime test exists yet. Before coding, inspect the exact Open WebUI 0.13.5 ACP call signatures and model-discovery path, then implement the smallest adapter that redirects the existing ACP transport to the configured Open Terminal host.
