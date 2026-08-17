# 大学生班费管理系统 - 技术架构文档

## 1. 系统概述
本系统旨在为大学生班级提供便捷的班费管理工具，支持费用记录、分摊计算、缴费跟踪和统计查询。系统采用前后端分离架构，后端提供RESTful API，前端为单页应用(SPA)。

## 2. 技术架构
### 2.1 整体架构
```
[浏览器 (单文件HTML/JS/CSS)] <-- HTTP/REST --> [FastAPI 应用服务器] <-- SQLAlchemy --> [SQLite/PostgreSQL 数据库]
```

### 2.2 技术栈详解
- **后端**:
  - **Python 3.12**: 运行环境。
  - **FastAPI**: 高性能异步Web框架，自动生成OpenAPI文档。
  - **SQLAlchemy 2.0**: ORM框架，支持异步操作，连接SQLite/PostgreSQL。
  - **Pydantic**: 数据验证和序列化，用于定义清晰的请求/响应模式。
  - **Alembic**: 数据库迁移工具，管理Schema变更。
  - **Passlib**: 密码哈希库。

- **前端**:
  - **单文件HTML**: 将HTML、CSS、JavaScript封装在一个文件中，简化部署。
  - **Alpine.js** (可选): 轻量级响应式框架，处理简单交互和状态管理。
  - **Tailwind CSS** (CDN): 实用优先的CSS框架，快速构建UI。

- **数据库**:
  - **SQLite**: 开发与测试环境，零配置。
  - **PostgreSQL**: 生产环境，提供更强的并发支持和数据可靠性。

## 3. 数据库设计
### 3.1 核心实体与关系
- **用户(User)**: 系统管理员或财务，拥有班级管理权限。
- **班级(Class)**: 核心业务单元，包含学生和财务记录。
- **学生(Student)**: 属于某个班级，是费用分摊和缴费的主体。
- **费用记录(Expense)**: 班级的每一笔收入或支出，关联一个类别。
- **缴费记录(Payment)**: 学生的缴费流水，关联学生和费用分摊记录。
- **费用类别(ExpenseCategory)**: 对费用进行分类（如班费、活动费）。
- **分摊记录(Split)**: 一次分摊计算的记录，包含总金额和每人金额。
- **分摊详情(SplitDetail)**: 分摊记录中每个学生的具体应缴和已缴金额。

### 3.2 索引策略
- `students` 表: 在 (`class_id`, `student_number`) 上建立复合索引。
- `expenses` 表: 在 (`class_id`, `date`) 上建立复合索引，加速按班级和日期查询。
- `payments` 表: 在 (`student_id`, `payment_date`) 上建立索引。
- `split_details` 表: 在 (`split_id`, `student_id`) 上建立唯一索引。

## 4. API 设计原则
- **RESTful**: 资源导向，使用标准HTTP方法（GET, POST, PUT, DELETE）。
- **版本控制**: 所有API路径前缀为 `/api/v1/`。
- **认证授权**: 除登录接口外，所有API需要JWT Bearer Token认证。通过角色（如`admin`）控制权限。
- **分页与筛选**: 列表接口支持 `limit`, `offset` 或 `page`, `size` 分页，以及基于日期、类别等字段的筛选。
- **一致性响应**: 所有响应使用统一的JSON结构，包含 `data`, `message`, `code` 字段。

## 5. 安全考虑
- **密码安全**: 使用 `bcrypt` 或 `argon2` 对密码进行哈希存储，绝不存储明文。
- **API安全**: 启用HTTPS，对请求参数进行严格验证，使用CORS白名单控制前端域名。
- **数据安全**: 对数据库文件进行定期备份。敏感信息（如联系方式）考虑加密存储。

## 6. 部署方案
### 开发环境
1. 使用 `venv` 创建虚拟环境。
2. `pip install -r requirements.txt`。
3. 运行 `alembic upgrade head` 初始化数据库。
4. 启动后端: `uvicorn app.main:app --reload`。
5. 直接浏览器打开 `frontend/index.html` 或用简单HTTP服务器托管。

### 生产环境 (Docker)
1. 使用 `Dockerfile` 构建后端镜像，包含Uvicorn。
2. 使用 `docker-compose.yml` 编排服务:
   - `api` 服务 (FastAPI应用)
   - `db` 服务 (PostgreSQL)
   - `nginx` 服务 (可选，用于反向代理和静态文件服务)
3. 使用环境变量管理数据库连接串和JWT密钥。
4. 数据库迁移在容器启动前通过 `entrypoint.sh` 执行。

## 7. 项目结构说明
- `app/api/v1/`: 按功能模块组织路由，清晰分离关注点。
- `app/crud/`: 封装所有数据库CRUD操作，业务逻辑不直接调用ORM。
- `app/services/`: 包含复杂业务逻辑（如分摊计算、统计），调用 `crud` 层。
- `app/schemas/`: 定义所有数据传输对象(DTO)，确保接口契约清晰。
- `frontend/`: 前端单文件应用，可独立部署为静态站点。

## 8. 未来扩展
- **通知功能**: 零成费用通过短信或邮件通知学生。
- **报表导出**: 支持将统计报表导出为Excel或PDF。
- **移动端适配**: 前端响应式设计，优化移动端体验。
- **多班级管理**: 允许一个用户管理多个班级。