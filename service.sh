#!/usr/bin/env bash
# ============================================================
#  CV Attendance System — Local Dev Runner
#  Usage:  ./service.sh {start|stop|logs|status}
#
#  Runs backend (uvicorn) + frontend (npm run dev) locally.
#  DB & Redis assumed already running (e.g. system service).
# ============================================================

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Resolve project root ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── PID / log file locations ────────────────────────────────
PID_DIR="$SCRIPT_DIR/.pids"
LOG_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

# ── Helper ──────────────────────────────────────────────────
info()  { echo -e "${CYAN}▶ $*${NC}"; }
ok()    { echo -e "${GREEN}✔ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
err()   { echo -e "${RED}✗ $*${NC}"; }

is_running() {
    local pidfile="$PID_DIR/$1.pid"
    [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

stop_proc() {
    local name="$1"
    local pidfile="$PID_DIR/$name.pid"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            for _ in $(seq 1 10); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.5
            done
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
            ok  "Stopped $name (PID $pid)"
        else
            warn "$name (PID $pid) was not running"
        fi
        rm -f "$pidfile"
    fi
}

# ── Start backend (uvicorn) ─────────────────────────────────
start_backend() {
    if is_running backend; then
        warn "Backend already running (PID $(cat "$PID_DIR/backend.pid"))"
        return
    fi
    info "Starting backend (uvicorn) …"

    local venv="$SCRIPT_DIR/backend/venv/bin/activate"
    if [[ ! -f "$venv" ]]; then
        err "Backend venv not found at $venv"
        exit 1
    fi

    (
        cd "$SCRIPT_DIR/backend"
        source "$venv"
        set -a; source "$SCRIPT_DIR/.env"; set +a
        nohup uvicorn app.main:app \
            --host 0.0.0.0 --port 8000 --reload \
            > "$LOG_DIR/backend.log" 2>&1 &
        echo $! > "$PID_DIR/backend.pid"
    )
    ok "Backend → http://localhost:8000  (PID $(cat "$PID_DIR/backend.pid"))"
}

# ── Start frontend (Vite dev server) ────────────────────────
start_frontend() {
    if is_running frontend; then
        warn "Frontend already running (PID $(cat "$PID_DIR/frontend.pid"))"
        return
    fi
    info "Starting frontend (npm run dev) …"

    (
        cd "$SCRIPT_DIR/frontend"
        nohup npm run dev \
            > "$LOG_DIR/frontend.log" 2>&1 &
        echo $! > "$PID_DIR/frontend.pid"
    )
    ok "Frontend → http://localhost:5173  (PID $(cat "$PID_DIR/frontend.pid"))"
}

# ── Commands ────────────────────────────────────────────────
cmd_start() {
    start_backend
    start_frontend
    echo ""
    ok "All services are running!"
    cmd_status
}

cmd_stop() {
    info "Stopping services …"
    stop_proc frontend
    stop_proc backend
    ok "All services stopped."
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_logs() {
    local svc="${1:-}"
    if [[ -n "$svc" ]]; then
        local logfile="$LOG_DIR/$svc.log"
        if [[ -f "$logfile" ]]; then
            info "Tailing logs for: $svc (Ctrl+C to stop)"
            tail -f "$logfile"
        else
            err "No log file for '$svc'. Available: backend, frontend"
        fi
    else
        info "Tailing all logs (Ctrl+C to stop)"
        tail -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log" 2>/dev/null
    fi
}

cmd_status() {
    for svc in backend frontend; do
        if is_running "$svc"; then
            ok "$svc is running (PID $(cat "$PID_DIR/$svc.pid"))"
        else
            err "$svc is stopped"
        fi
    done
}

# ── Usage ───────────────────────────────────────────────────
usage() {
    cat <<EOF
${CYAN}CV Attendance System — Local Dev Runner${NC}

Usage:  ./service.sh <command> [options]

Commands:
  ${GREEN}start${NC}          Start backend + frontend
  ${GREEN}stop${NC}           Stop all
  ${GREEN}restart${NC}        Stop + start
  ${GREEN}logs${NC} [service]  Tail logs (backend | frontend | all)
  ${GREEN}status${NC}         Show running status

Examples:
  ./service.sh start
  ./service.sh logs backend
  ./service.sh stop
EOF
}

# ── Entrypoint ──────────────────────────────────────────────
case "${1:-}" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    logs)    cmd_logs "${2:-}" ;;
    status)  cmd_status  ;;
    *)       usage       ;;
esac
