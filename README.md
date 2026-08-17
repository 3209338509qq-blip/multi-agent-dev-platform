# Multi-Agent Dev Platform（多智能体软件研发系统）

> 输入一个软件需求，系统自动完成：需求分析 → 任务拆解 → 架构设计 → 编码 → 自动测试 → Code Review → 自动修复 → Git 管理 → 交付可运行项目。
> 一个从零自研、可现场演示的 Mini AI Software Engineering Platform。

## ✨ 核心能力

- **8 个专职 Agent**：PM（需求拆解）、Architect（架构设计）、Backend、Frontend、Test（真实执行测试）、Review（代码审查门控）、Debug（修复闭环）、Git（分支/提交/合并/回滚）
- **自研轻量 Orchestrator**：Task DAG 调度、状态机、并行执行、失败重试、超时与 Token 预算
- **真实闭环**：Test → Debug → Test 循环最多 3 轮；Review 不通过不 merge
- **共享 Workspace + 三层 Memory**：Agent 通过文件系统与记忆协作，不依赖聊天上下文
- **真实 Git 工作流**：每个 Agent 独立分支，commit 全程可追踪
- **Web Dashboard**：项目列表、任务/Agent 状态、WebSocket 实时日志、Token 用量、测试与 Review 结果
- **LLM Provider 抽象**：DeepSeek / MiMo / Qwen / OpenAI / Claude 一键切换（.env 配置）

## 🚀 快速开始（本地模式，无需 Docker）

```bash
cp .env.example .env        # 填入 LLM_API_KEY
make install                # 安装后端 venv + 前端依赖
make dev                    # 启动后端(8000) + 前端(5173)
```

打开 http://localhost:5173 ，输入需求（例如「创建一个大学生班费管理系统…」）即可观看完整 Agent 工作流。

## 🐳 Docker Compose 部署

```bash
docker compose up --build   # backend + frontend + postgres + redis
```

打开 http://localhost/（nginx 托管前端并反代后端 API/WebSocket）。

## 📚 文档

- [docs/architecture.md](docs/architecture.md) — 系统总体架构（15 个设计主题）
- [docs/agent-design.md](docs/agent-design.md) — Agent 设计（Phase 4 补全）
- [docs/api.md](docs/api.md) — REST/WebSocket API 说明（Phase 10 补全）
- [docs/security.md](docs/security.md) — 安全设计（Phase 8 补全）
- [docs/demo.md](docs/demo.md) — 班费管理系统 Demo 说明（Phase 11 补全）

## 🏗 开发状态

Phase 0 环境勘察 ✅ ｜ Phase 1 架构文档与骨架 ✅ ｜ Phase 2+ 进行中（见 docs/architecture.md 附录）

## 🧪 测试

```bash
cd backend && uv run pytest -v
```
