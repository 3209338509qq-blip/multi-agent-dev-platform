# Multi-Agent Dev Platform（多智能体软件研发系统）

> 多智能体软件研发原型。目标流程：需求分析 → 任务拆解 → 架构设计 → 编码 → 测试 → Code Review → 自动修复 → Git 交付。
> 当前已实现核心编排和代码生成；自动修复、完整 Git 工作流与隔离执行仍待补全，详见可靠性修补文档。

## ✨ 核心能力

- **8 个专职 Agent**：PM（需求拆解）、Architect（架构设计）、Backend、Frontend、Test（真实执行测试）、Review（代码审查门控）、Debug（修复闭环）、Git（分支/提交/合并/回滚）
- **自研轻量 Orchestrator**：Task DAG 调度、状态机、并行执行、失败重试与超时；Token 预算执行尚待完善
- **执行校验**：真实执行 pytest，结合退出码与 JUnit 报告判断成功；依赖图保证先测试、再审查、再提交。自动 Debug 修复循环尚待接入
- **共享 Workspace + 三层 Memory**：Agent 通过文件系统与记忆协作，不依赖聊天上下文
- **Git 产物提交**：当前支持初始化仓库与提交生成文件；独立分支、合并与回滚尚待实现
- **Web Dashboard**：项目列表、任务状态、WebSocket 实时事件日志；Token 用量与详细测试/审查结果面板尚待补全
- **LLM Provider 抽象**：当前注册 OpenAI 兼容接口，可通过 .env 配置地址与模型；Anthropic 原生接口尚未实现

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
- [docs/reliability-repairs.md](docs/reliability-repairs.md) — 可靠性修补、回归测试、按代码安排的学习路线与待补功能
- 后端运行后打开 `/docs` 查看 FastAPI 自动生成的 API 文档

## 🏗 开发状态

Phase 0 环境勘察 ✅ ｜ Phase 1 架构文档与骨架 ✅ ｜ Phase 2+ 进行中（见 docs/architecture.md 附录）

## 🧪 测试

```bash
cd backend && uv run pytest -v
```
