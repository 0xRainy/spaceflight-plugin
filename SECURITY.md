# Security

## What must never be published

| Item | Location | Why |
|------|----------|-----|
| `ntfy_topic` | `~/.config/spaceflight/config.toml` | Anyone with the topic can read your phone alerts |
| `ntfy_token` | same / env `SPACEFLIGHT_NTFY_TOKEN` | Access-control secret for private topics |
| Env overrides | `SPACEFLIGHT_NTFY_*` | Same secrets in the shell environment |

These paths are **outside the git tree** by design. The repo only ships `config.example.toml` with empty placeholders.

## Reporting

If you accidentally commit a topic or token:

1. Rotate the topic immediately (new random name in the ntfy app + `spaceflight setup`).
2. Revoke any access token on your ntfy server.
3. Treat the old topic as public forever (assume it was scraped).

## Data sources

Spaceflight talks to public APIs only (Launch Library 2, RocketLaunch.Live, SpaceX CMS). No AI keys, no SpaceX account, no payment credentials.
