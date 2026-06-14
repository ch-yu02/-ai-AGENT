#!/usr/bin/env bash

# EDU-Mate 本地开发脚本。
#
# 这个脚本把前后端常用启动、测试、构建命令收拢到一个入口里，避免
# 每次联调都重新查 AGENTS.md。所有命令默认在项目根目录执行。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
PIP_BIN="$ROOT_DIR/.venv/bin/pip"
UVICORN_BIN="$ROOT_DIR/.venv/bin/uvicorn"

usage() {
  cat <<EOF
EDU-Mate development helper

Usage:
  scripts/dev.sh <command>

Commands:
  backend          Start FastAPI backend with reload
  frontend         Start Vite frontend dev server
  dev              Start backend and frontend together
  test             Run backend tests and frontend tests
  backend-test     Run backend unittest suite
  frontend-test    Run frontend Vitest suite
  compile          Compile-check backend Python files
  build            Type-check and build frontend
  install-backend  Install backend Python dependencies
  mock             Send mock events to an existing frontend-created session
  llm-smoke        Manually test configured LLM provider with fixed classroom data
  rebuild-global-index
                   Rebuild data/indexes/global documents snapshot

Environment:
  BACKEND_HOST     Backend host, default 127.0.0.1
  BACKEND_PORT     Backend port, default 8000
  FRONTEND_HOST    Frontend host, default 127.0.0.1
  FRONTEND_PORT    Frontend port, default 5173

Examples:
  scripts/dev.sh dev
  scripts/dev.sh test
  scripts/dev.sh mock --session-id lec_xxx --no-end
  BACKEND_HOST=0.0.0.0 FRONTEND_HOST=0.0.0.0 scripts/dev.sh dev
EOF
}

require_backend_venv() {
  if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" ]]; then
    echo "Backend virtualenv is missing. Expected .venv/bin/python and .venv/bin/uvicorn." >&2
    echo "Create it and install dependencies first, or run: scripts/dev.sh install-backend" >&2
    exit 1
  fi
}

require_frontend_deps() {
  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "Frontend dependencies are missing. Run: cd frontend && npm install" >&2
    exit 1
  fi
}

run_backend() {
  require_backend_venv
  cd "$ROOT_DIR"
  exec "$UVICORN_BIN" backend.app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"
}

run_frontend() {
  require_frontend_deps
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
}

run_dev() {
  require_backend_venv
  require_frontend_deps

  echo "Backend:  http://$BACKEND_HOST:$BACKEND_PORT"
  echo "Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
  echo "Press Ctrl+C to stop both servers."

  cd "$ROOT_DIR"
  "$UVICORN_BIN" backend.app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
  backend_pid=$!

  cd "$ROOT_DIR/frontend"
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
  frontend_pid=$!

  # 任意一个服务退出时，清理另一个后台进程，避免端口被旧进程占住。
  cleanup() {
    kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
    wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM

  wait -n "$backend_pid" "$frontend_pid"
}

run_backend_test() {
  require_backend_venv
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m unittest discover -s backend/tests
}

run_frontend_test() {
  require_frontend_deps
  cd "$ROOT_DIR/frontend"
  npm test
}

run_compile() {
  require_backend_venv
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m py_compile \
    backend/app/main.py \
    backend/app/api/*.py \
    backend/app/core/*.py \
    backend/app/extraction/*.py \
    backend/app/llm/*.py \
    backend/app/models/*.py \
    backend/app/rag/*.py \
    backend/app/skills/*.py \
    backend/app/storage/*.py \
    backend/tests/*.py \
    backend/scripts/*.py
}

run_build() {
  require_frontend_deps
  cd "$ROOT_DIR/frontend"
  npm run build
}

run_install_backend() {
  if [[ ! -x "$PIP_BIN" ]]; then
    echo "Missing .venv/bin/pip. Create the virtualenv first:" >&2
    echo "  python -m venv .venv" >&2
    exit 1
  fi

  cd "$ROOT_DIR"
  "$PIP_BIN" install -r backend/requirements.txt
}

run_mock() {
  require_backend_venv
  cd "$ROOT_DIR"
  if [[ "$#" -eq 1 ]]; then
    echo "mock requires an existing frontend-created session_id." >&2
    echo "Start a classroom in the frontend first, then run:" >&2
    echo "  scripts/dev.sh mock --session-id REPLACE_WITH_SESSION_ID --no-end" >&2
    exit 1
  fi
  "$PYTHON_BIN" backend/scripts/mock_sender.py "${@:2}"
}

run_llm_smoke() {
  require_backend_venv
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m backend.scripts.llm_smoke
}

run_rebuild_global_index() {
  require_backend_venv
  cd "$ROOT_DIR"
  "$PYTHON_BIN" -m backend.scripts.rebuild_global_index "${@:2}"
}

command="${1:-help}"

case "$command" in
  backend)
    run_backend
    ;;
  frontend)
    run_frontend
    ;;
  dev)
    run_dev
    ;;
  test)
    run_backend_test
    run_frontend_test
    ;;
  backend-test)
    run_backend_test
    ;;
  frontend-test)
    run_frontend_test
    ;;
  compile)
    run_compile
    ;;
  build)
    run_build
    ;;
  install-backend)
    run_install_backend
    ;;
  mock)
    run_mock "$@"
    ;;
  llm-smoke)
    run_llm_smoke
    ;;
  rebuild-global-index)
    run_rebuild_global_index "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    echo >&2
    usage >&2
    exit 1
    ;;
esac
