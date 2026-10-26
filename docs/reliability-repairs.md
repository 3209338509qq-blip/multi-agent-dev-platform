# 可靠性修补与学习路线

本次先修复执行链路的正确性。验证使用真实 SQLite、真实 pytest 子进程，以及确定性的模型替身；不代表已经验证真实模型生成任意软件的质量。

## 修复了什么

| 问题 | 修复后的行为 | 回归测试 |
| --- | --- | --- |
| 已有测试时 `tests_dir` 未定义 | 提前确定测试目录，支持递归发现测试 | `tests/test_test_agent.py` |
| 只数终端输出中的 FAILED，命令错误、导入错误可能误报成功 | 同时检查 pytest 退出码和 JUnit XML；没有执行通过的测试时判失败 | `tests/test_test_agent.py` |
| 冒烟测试没有真正检查源码语法 | 使用 `ast.parse` 检查 Python 源码，报告 `smoke_only`，区分基础检查和业务验收 | `tests/test_test_agent.py` |
| 安装依赖失败后继续测试 | 明确返回依赖安装失败，停止后续测试 | `tests/test_test_agent.py` |
| 同步子进程阻塞异步调度 | 使用异步子进程，超时或取消时回收直接子进程 | `tests/test_test_agent.py` |
| 开发 Agent 只拿到任务描述，未拿到架构 JSON | 读取依赖任务的输出；架构师接收 PM 产物，前后端接收架构产物，保留原始需求和所有直接上游输出 | `tests/test_orchestrator.py`、`tests/test_pm_agent.py` |
| PM 示例中的依赖占位符与程序期望不一致 | 统一使用角色名，并校验必需角色、角色唯一性、依赖存在性、无环以及测试/审查门控 | `tests/test_pm_agent.py` |
| 调度器静默忽略不存在的依赖，环形依赖只能等待超时 | 构建任务图时拒绝无效依赖和环；已有无效图立即使项目失败 | `tests/test_scheduler.py`、`tests/test_orchestrator.py` |
| RUNNING 只在内存里更新，页面查数据库看不到 | 执行前持久化 RUNNING 和开始时间 | `tests/test_orchestrator.py` |
| 超时失败被最终汇总覆盖成 completed | 记录项目级失败原因，最终状态保留 failed | `tests/test_orchestrator.py` |

当前计划用角色名识别依赖，因此每种角色只支持一个任务。若要让多个 Backend Agent 分别实现不同模块，应先把计划升级为独立 task_id，再支持同角色多任务；不能直接删除唯一性校验。

## 先学什么

这个项目包含两套代码：平台本身（`backend/app`、`frontend/src`），以及平台生成的应用（`workspace/projects/<id>/src`）。先读平台本身。

1. **Python 工程基础**：函数、类、字典/列表、异常、模块导入、路径、虚拟环境。先读 `app/agents/__init__.py`，能解释 `AgentContext → run → AgentResult`。
2. **HTTP 与 FastAPI**：浏览器如何发 JSON，路由如何校验输入、返回状态码。读 `app/api/projects.py` 与 `app/schemas/__init__.py`，追踪“创建项目”如何产生第一个 PM 任务。
3. **SQL 与持久化**：项目、任务、一次执行分别是什么；主键、外键、查询、事务。读 `app/models/__init__.py`，理解 `Project → Task → AgentRun`，以及 `TaskDependency`。
4. **模型调用与结构化输出**：Prompt、API 请求、JSON 解析、字段校验、重试、Token。读 `app/llm/openai_compat.py` 和 `app/agents/pm.py`。同一模型可以通过不同 Prompt 承担不同角色；不是必须训练八个模型。
5. **任务图与状态机**：为什么前后端能并行、测试必须等待二者、审查失败为何不能提交。读 `scheduler.py`、`state_machine.py`、`task_plan.py`，手画 PM → Architect → (Backend/Frontend) → Test → Review → Git。
6. **异步编程**：`async/await`、任务队列、Worker、Future、超时和取消。最后读 `orchestrator.py`，理解 `await` 允许其他工作推进；在 async 函数里调用同步阻塞命令仍会阻塞事件循环。
7. **测试与调试**：退出码、断言、正常路径、异常路径、集成测试和模型替身。先运行 `tests/test_test_agent.py`，解释为什么“未发现 FAILED 字样”不能证明成功。
8. **前端与实时事件**：TypeScript 类型、React state/effect、fetch、WebSocket。读 `frontend/src/api.ts` 和 `pages/ProjectDetail.tsx`，追踪任务状态如何显示到页面。

Git、Docker、部署在读懂以上链路之后再加深。当前无需先学模型训练、微调或复杂 Agent 框架。

## 建议亲手完成的练习

- 给项目创建接口增加一个非空字段，连通前端、请求 schema、数据库和测试。
- 在不调用真实模型的情况下，运行 PM → Architect → Backend/Frontend 集成测试；修改架构 API 路径，确认前后端 Prompt 都收到同一个路径。
- 故意制造一次语法错误、一次测试导入错误、一个环形依赖，观察平台为什么拒绝它们。
- 再实现“成果文件列表 → 代码预览 → ZIP 下载”，把读文件、API、前端状态和路径边界检查连成一个功能。

## 验证

```bash
cd backend
uv sync --frozen
uv run pytest -q
```

真实模型连通性测试依赖原项目环境，本次未调用真实模型或消耗模型额度。

## 后续仍需完成

- 自动 Test → Debug → Test 修复循环尚未接入编排器，当前是任务失败重试。
- Git Agent 当前只初始化仓库和提交文件，尚未实现每个 Agent 独立分支、合并和回滚。
- 取消 API 尚未接入运行中的 Orchestrator 实例；任务恢复、重复启动保护还需完善。
- 当前执行生成代码及安装依赖仍属于本地模式，依赖可安装到当前 Python 环境；还需要独立环境、完整进程树清理和真正隔离的执行后端。
- 完整 JSON Schema 校验、所有文件写入路径的边界检查，以及真实模型输出的端到端验收仍需补全。
- 成果预览与打包下载尚未实现。
