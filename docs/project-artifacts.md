# 成果文件列表、文本预览与 ZIP 下载

此切片基于 main（f4aefd4），独立于未合并的 PR1，不包含 PR1 的执行链路修复。

## 数据来源与接口

创建接口把项目写入 `Settings.workspace_root/projects/<project_id>`，数据库保存 `Project.workspace_path`。开发 Agent 在该目录的 `src/backend`、`src/frontend` 写入文件。默认配置为仓库根目录的 `workspace`；仓库已有的 `backend/workspace` 示例不会被自动当作其他项目的成果。

复用项目路由及数据库查询，不新增数据库表：

| GET 接口 | 返回 |
| --- | --- |
| `/api/projects/{id}/artifacts` | `{files: [{path, size}]}`，相对路径、字节数 |
| `/api/projects/{id}/artifacts/file?path=src/backend/app.py` | `{path, size, content}`，UTF-8 文本 |
| `/api/projects/{id}/artifacts/download` | `application/zip` 附件，保留相对目录 |

前端详情页增加成果面板：进入时加载列表，手动刷新、选择文件、显示代码或错误、下载 ZIP。快速切换文件会丢弃过时的预览响应。文本通过 React 转义显示，不渲染 HTML、不执行代码。Vite 开发代理保留 `/api`，与 FastAPI 路由一致。

## 边界与限制

- 先查项目存在性（404），再核对数据库路径必须等于配置根目录下 `projects/<id>`；不信任数据库提供的任意宿主机路径。
- ID 仅允许字母、数字、下划线及连字符；拒绝绝对路径、空路径段、点目录、反斜线、NUL 与越界路径（403）。
- 从可信配置根目录逐级打开项目目录，目录及文件使用 `O_NOFOLLOW`、基于文件描述符读取；拒绝目录/文件符号链接和非普通文件（Linux/POSIX 后端）。
- 列表和 ZIP 排除隐藏文件/目录（含 `.agent`、`.git`、`.env`）、`node_modules`、`__pycache__`、`venv`、`dist`、`build` 以及 `.pem`、`.key`、`.pyc`；预览不能直接绕过这些过滤。
- 最多 1000 文件、单文件 8 MiB、总量 32 MiB、目录深度 32；超过返回 413，整个列表/打包失败，不静默截断。ZIP 在内存中构建，放到线程池执行，读取时再次限制大小。
- 单文件预览上限 256 KiB（413），非 UTF-8 或含 NUL 内容返回 415；二进制仍可打包下载。
- 存在但为空的项目返回空列表/有效空 ZIP；前端空列表时禁用下载。不存在的工作区返回 404。
- 运行中也可读取，显示当前磁盘内容；并非一致性快照或质量验收结果。并发改写/删除可能使本次请求失败，用户可刷新重试。
- 沿用平台现有访问控制；本次未新增用户认证与项目所有权系统。过滤不等于完整密钥识别：普通源码内的秘密仍可能随成果导出。

## 修改文件

- `backend/app/api/projects.py`：三个 GET 路由、项目查找、线程池调用。
- `backend/app/services/artifacts.py`：统一路径约束、过滤、文件读取和 ZIP。
- `backend/tests/test_artifacts.py`：真实 SQLite/HTTP/文件系统集成测试。
- `frontend/src/api.ts`：成果类型、错误处理、预览与 Blob 下载。
- `frontend/src/pages/ProjectArtifacts.tsx`：成果列表、刷新、预览、下载及状态。
- `frontend/src/pages/ProjectDetail.tsx`：面板入口。
- `frontend/vite.config.ts`：修正开发代理路径。
- `docs/project-artifacts.md`：接口、验证与范围说明。

## 验收

```bash
cd backend
uv sync --frozen
.venv/bin/python -m pytest -q tests/test_artifacts.py
.venv/bin/python -m pytest -q
cd ../frontend
npm ci
npm run build
cd ..
git diff --check
```

自动测试覆盖中文文件名、文本内容、二进制预览拒绝、ZIP 内容与附件头、空目录、文件/项目不存在、非法路径、DB 路径篡改、符号链接目录和文件、FIFO、过滤一致性以及大小/数量限制。全套测试不调用真实模型；模型连通性测试在缺少原环境时跳过。

手动联调：在 backend 运行 `.venv/bin/uvicorn app.main:app --port 8000`，frontend 运行 `npm run dev`；创建项目，在返回的 workspace_path 内加入 `src/demo.py`，打开详情，刷新列表，点击文件并下载 ZIP。检查中文内容及目录结构；加入二进制文件确认预览报错；不要使用真实密钥作测试数据。

## 仍不属于本次范围

自动 Test→Debug→Test 循环、完整 Git 分支/合并/回滚流程、运行中取消与进程树回收、Docker/独立依赖环境及隔离执行、Agent 写入路径全面加固、任务恢复与重复启动保护、真实模型端到端生成验收均未实现。此处的读取边界不能代替生成代码的执行隔离。

本次实际结果：后端全套 `63 passed, 1 skipped`；前端生产构建通过；真实 HTTP 经 Vite 代理完成创建、列表、中文预览、ZIP 内容核对。浏览器交互验收未完成：环境缺少浏览器，Playwright 浏览器下载包无效；上述手动页面验收仍需执行，不能把构建通过视为 UI 端到端通过。
