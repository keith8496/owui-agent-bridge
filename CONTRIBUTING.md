# Contributing

Keep changes narrow and verify behavior at the boundary they affect. Document protocol assumptions and distinguish source inspection from runtime-tested behavior.

## Pull requests

- Use a focused branch and submit changes to `main` through a pull request.
- Explain the user-visible behavior and security implications.
- Include reproducible verification steps; add tests as implementation is introduced.
- Never include credentials, tokens, cookies, or sensitive chat/session captures.

## Design review checklist

- Does agent-host selection remain independent of workspace selection?
- Are endpoint authentication and Open Terminal ownership enforced?
- Are cancellation, disconnect/reconnect, and cleanup handled?
- Are filesystem and shell execution locations stated accurately?
