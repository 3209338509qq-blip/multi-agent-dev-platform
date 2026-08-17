#!/usr/bin/env bash
# 本地开发：同时启动后端(8000)与前端(5173)，Ctrl+C 一并退出
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() {
  echo "[dev] 停止服务..."
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ ! -f .env ]; then
  echo "[dev] 提示：未检测到 .env，使用默认配置（LLM 需在 .env 中配置 API Key）"
fi

echo "[dev] 后端 http://localhost:8000 （API 文档 http://localhost:8000/docs）"
(cd backend && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload) &

echo "[dev] 前端 http://localhost:5173"
(cd frontend && exec npm run dev -- --host 0.0.0.0) &

wait
