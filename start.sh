#!/usr/bin/env sh
# OpenBIM-Deflect: API(redis·worker 포함) + 선택적으로 프론트(Vite)를 Docker Compose로 기동합니다.
#
#   ./start.sh                 # api + frontend
#   ./start.sh --dev           # 소스 마운트 + uvicorn --reload
#   ./start.sh --api-only      # API(+redis+worker) 만
#   ./start.sh -d              # 백그라운드 (compose 에 넘길 추가 인자)
#   ./start.sh --dev --api-only -d
#
# 필요: Docker Engine, docker compose(v2) 또는 docker-compose

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' "start.sh: docker 가 없습니다. Docker Desktop 등을 설치한 뒤 다시 실행하세요." >&2
  exit 1
fi

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    if ! command -v docker-compose >/dev/null 2>&1; then
      printf '%s\n' "start.sh: 'docker compose' 또는 docker-compose 를 찾을 수 없습니다." >&2
      exit 1
    fi
    docker-compose "$@"
  fi
}

DEV=0
API_ONLY=0
while [ "${1-}" = "--dev" ] || [ "${1-}" = "--api-only" ]; do
  case "$1" in
    --dev) DEV=1 ;;
    --api-only) API_ONLY=1 ;;
  esac
  shift
done

echo "OpenBIM-Deflect 기동 (저장소: $ROOT)"
echo "  · API (Swagger): http://localhost:8000/docs"
if [ "$API_ONLY" -eq 0 ]; then
  echo "  · 프론트(Vite): http://localhost:5173"
fi
echo ""

if [ "$DEV" -eq 1 ]; then
  if [ "$API_ONLY" -eq 1 ]; then
    compose -f docker-compose.yml -f docker-compose.dev.yml up --build api "$@"
  else
    compose -f docker-compose.yml -f docker-compose.dev.yml up --build api frontend "$@"
  fi
else
  if [ "$API_ONLY" -eq 1 ]; then
    compose -f docker-compose.yml up --build api "$@"
  else
    compose -f docker-compose.yml up --build api frontend "$@"
  fi
fi
