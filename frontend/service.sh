#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
SERVICE_NAME="surveillance-system"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
  cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  start       Build (if needed) and start the service
  stop        Stop the service
  restart     Rebuild and restart the service
  status      Show service status
  logs        Tail service logs (Ctrl+C to exit)
  build       Build/rebuild the Docker image only

EOF
  exit 1
}

require_docker() {
  if ! command -v docker &>/dev/null; then
    log_err "Docker is not installed or not in PATH."
    exit 1
  fi
}

do_start() {
  log_info "Starting $SERVICE_NAME ..."
  docker compose -f "$COMPOSE_FILE" up -d --build
  log_ok "$SERVICE_NAME is running on port 8080"
}

do_stop() {
  log_info "Stopping $SERVICE_NAME ..."
  docker compose -f "$COMPOSE_FILE" down
  log_ok "$SERVICE_NAME stopped."
}

do_restart() {
  log_info "Restarting $SERVICE_NAME ..."
  docker compose -f "$COMPOSE_FILE" down
  docker compose -f "$COMPOSE_FILE" up -d --build
  log_ok "$SERVICE_NAME restarted on port 8080"
}

do_status() {
  docker compose -f "$COMPOSE_FILE" ps
}

do_logs() {
  docker compose -f "$COMPOSE_FILE" logs -f --tail=100
}

do_build() {
  log_info "Building $SERVICE_NAME image ..."
  docker compose -f "$COMPOSE_FILE" build
  log_ok "Build complete."
}

# --- Main ---
require_docker

case "${1:-}" in
  start)   do_start   ;;
  stop)    do_stop    ;;
  restart) do_restart ;;
  status)  do_status  ;;
  logs)    do_logs    ;;
  build)   do_build   ;;
  *)       usage      ;;
esac
