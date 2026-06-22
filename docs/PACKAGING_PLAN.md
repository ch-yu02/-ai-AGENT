# EDU-Mate Packaging Plan

This project is moving from a development-only workflow toward a directly
launchable classroom assistant. The frontend remains the only user-facing
source of start/end classroom actions; unfinished backend work continues in the
background after the user clicks end.

## Phase 1: Local App Entry

Implemented:

- `scripts/dev.sh llm-config` provides a first-run LLM provider wizard.
- `scripts/dev.sh app` checks LLM configuration, builds the frontend if needed,
  starts the backend without reload, and serves the built frontend with Vite
  preview.
- `scripts/dev.sh desktop-shortcut` installs/updates a desktop launcher that
  runs `scripts/launch_desktop_app.sh`.
- The desktop launcher starts app mode in a terminal and opens the browser to
  the local frontend automatically.
- `.env` remains supported for direct/manual configuration and takes precedence
  through exported environment variables.
- Provider templates are available for Kimi/Moonshot, DeepSeek, OpenAI,
  DashScope/Qwen, and local OpenAI-compatible services.

This phase is still a developer-friendly local runner, not a packaged binary.

## Phase 2: Desktop Shell

Planned:

- Add a desktop launcher that starts the backend and frontend server processes.
- Open the app window directly instead of requiring the user to open a browser.
- Surface startup, API configuration, camera, microphone, and background task
  status in the UI.
- Keep `.env` loading for advanced users while allowing the first-run wizard to
  write local configuration.

## Phase 3: Runtime Supervision

Planned:

- Add process supervision for backend, frontend, WhisperLive, and microphone
  capture.
- Add a small local status endpoint for readiness checks.
- Persist user-facing logs for startup failures, model/API failures, and device
  permission issues.
- Keep classroom end fast: save the session immediately, then finish summary,
  quiz, todo, graph, and index generation in background tasks.

## Phase 4: Distribution

Planned:

- Freeze backend dependencies and frontend build assets.
- Package the launcher and runtime assets for the target board.
- Add upgrade/migration handling for `.env`, session data, indexes, and logs.
- Add a factory-reset or reconfigure action for API credentials.
