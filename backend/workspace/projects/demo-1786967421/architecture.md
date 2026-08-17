# 大学生班费管理系统 - 技术架构文档

## 1. 项目概述
本项目旨在为大学班级提供一个简洁、易用的班费管理工具，实现缴费记录、支出申请、审批流程、余额查询等核心功能，确保班费使用的透明与规范。

## 2. 设计目标
- **简洁性**：前端采用单文件部署，降低使用门槛。
- **安全性**：基于JWT的身份认证，细粒度的角色权限控制。
- **可靠性**：数据库事务保障数据一致性。
- **可维护性**：后端代码严格遵循模块化与分层架构。
- **可扩展性**：API遵循RESTful规范，便于未来功能扩展或移动端接入。

## 3. 技术栈详情
- **后端**：
  - **框架**：FastAPI (异步、高性能、自动生成OpenAPI文档)
  - **ORM**：SQLAlchemy 2.0 (使用async session，支持SQLite和PostgreSQL)
  - **数据验证**：Pydantic v2 (与FastAPI深度集成)
  - **认证**：JWT (使用python-jose) + Passlib (密码哈希)
  - **服务器**：Uvicorn (ASGI)
- **前端**：
  - 一个`index.html`文件，内嵌JavaScript (使用现代ES6+语法) 和CSS。通过`fetch` API与后端通信。界面采用响应式设计，兼容PC和移动端。
- **数据库**：
  - **开发/测试**：SQLite (零配置，文件数据库)
  - **生产**：PostgreSQL 15+ (高性能、高可靠性、支持JSON等高级特性)
- **测试**：Pytest (用于API端点、数据库CRUD操作的单元与集成测试)

## 4. 核心架构模式
- **前后端分离**：前端为静态HTML，通过REST API与后端交互。
- **分层架构**：
  - **API层 (`app/api/`)**：定义路由和接口，处理HTTP请求/响应。
  - **业务/服务层 (`app/crud/`)**：封装核心业务逻辑和数据库操作（Create, Read, Update, Delete）。
  - **模型/数据层 (`app/models/`)**：SQLAlchemy ORM模型定义，映射数据库表结构。
  - **Schema层 (`app/schemas/`)**：Pydantic模型，定义请求和响应数据的格式与验证规则。
- **依赖注入**：利用FastAPI的`Depends`系统管理数据库会话、当前用户等依赖。

## 5. 数据库设计要点
- **核心实体**：用户(`users`)、班级成员(`members`)、缴费记录(`payments`)、支出记录(`expenses`)、审计日志(`audit_logs`)。
- **关系**：
  - 一个用户(`user`)可以关联一个班级成员(`member`)。
  - 一笔缴费(`payment`)关联一个成员和一个记录人(`recorded_by_user`)。
  - 一笔支出(`expense`)关联一个提交人(`submitter`)和一个审批人(`approver`)。
- **索引建议**：
  - `users.username` (唯一索引)
  - `members.student_id` (唯一索引)
  - `payments.member_id`, `payments.payment_date` (常用查询字段)
  - `expenses.status`, `expenses.submitter_id` (筛选和关联字段)
- **审计**：`audit_logs`表记录关键数据的变更历史，支持追溯。

## 6. API设计原则
- **RESTful**：资源导向（`/members`, `/payments`, `/expenses`），使用标准HTTP方法（GET, POST, PUT）。
- **版本控制**：API路径包含版本号（`/api/v1/`），便于未来平滑升级。
- **统一响应格式**：成功与失败响应结构保持一致。
- **认证**：除`/auth/login`外，所有API需在请求头`Authorization`中携带`Bearer <token>`。
- **幂等性**：PUT操作（如审批）设计为幂等。

## 7. 安全考虑
- **认证与授权**：
  - 用户登录后获取JWT，后续请求携带该令牌。
  - 使用`RBAC`：定义`student`（普通成员）、`treasurer`（班委，可记录收支）、`admin`（班长/系统管理员，可审批、管理成员）等角色。
  - 在API路由或依赖项中校验当前用户角色是否允许执行该操作。
- **输入验证**：所有API输入均由Pydantic Schema进行严格验证，防止SQL注入、XSS等攻击。
- **数据保护**：敏感配置（密钥、数据库URL）通过环境变量注入，不硬编码。
- **HTTPS**：生产环境强制使用HTTPS。

## 8. 部署方案
- **本地开发**：
  1. 创建Python虚拟环境。
  2. `pip install -r requirements.txt`。
  3. 配置`.env`文件（设置`DATABASE_URL=sqlite:///./app.db`等）。
  4. 运行`python run.py`启动Uvicorn服务器。
  5. 访问 `http://localhost:8000` 打开前端，或 `/docs` 查看API文档。
- **生产部署 (以PostgreSQL为例)**：
  1. 准备PostgreSQL数据库，创建数据库和用户。
  2. 修改`.env`中的`DATABASE_URL`指向生产数据库。
  3. 使用`gunicorn -k uvicorn.workers.UvicornWorker app.main:app`或类似命令部署。
  4. 前端`index.html`可由Nginx或Caddy等反向代理服务器提供静态文件服务。

## 9. 未来扩展考虑
- **数据导出**：提供导出为Excel/CSV的功能。
- **通知**：集成邮件或微信通知，在审批、缴费成功时提醒相关成员。
- **文件附件**：支持上传支出凭证图片，需引入对象存储（如MinIO）。
- **更复杂的前端**：如果交互需求复杂化，可将前端重构为基于React或Vue的单页应用（SPA）。