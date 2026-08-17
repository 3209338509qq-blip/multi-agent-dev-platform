SHELL := /bin/bash
.PHONY: help install backend-install frontend-install dev test test-backend test-frontend build compose-config compose-up down demo clean

help: ## 列出所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: backend-install frontend-install ## 安装后端 venv 与前端依赖

backend-install: ## uv 同步后端依赖
	cd backend && uv sync

frontend-install: ## npm 安装前端依赖
	cd frontend && npm install

dev: ## 同时启动后端(8000)与前端(5173)
	./scripts/dev.sh

test: test-backend ## 运行全部测试（前端测试 Phase 10 接入）

test-backend: ## 后端 pytest
	cd backend && uv run pytest -v

test-frontend: ## 前端 vitest
	cd frontend && npm test -- --run

build: ## 前端生产构建
	cd frontend && npm run build

compose-config: ## 校验 compose 文件（无需 daemon）
	docker compose config 2>/dev/null || docker-compose config

compose-up: ## 一键启动 backend+frontend+postgres+redis
	docker compose up --build -d 2>/dev/null || docker-compose up --build -d

down: ## 停止 compose 服务
	docker compose down 2>/dev/null || docker-compose down

demo: ## 运行班费管理系统 Demo（Phase 11 实现）
	./scripts/demo.sh

clean: ## 清理构建产物（保留 workspace 与源码）
	rm -rf backend/.venv frontend/node_modules frontend/dist backend/.pytest_cache backend/data
