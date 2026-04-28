# Frontend Chat Test Page

## Overview
Developer-facing chat UI used to manually test chatbot flows against backend APIs.

## Key Files
- `templates/index.html` — static test UI, sends requests to `/chatbot/v2/message` and clear-session endpoint.

## How It Works
The script in `templates/index.html` defines constants for merchant/session context and sends only the latest user message while backend stores history in Redis.

## Gotchas / Decisions
- `SESSION_ID` is hardcoded for local testing and controls which Redis/Firebase conversation thread receives messages.

## 2026-04-28 - Session ID set to 2
- Updated `SESSION_ID` in `templates/index.html` from `"1"` to `"2"` so frontend messages use session 2.
