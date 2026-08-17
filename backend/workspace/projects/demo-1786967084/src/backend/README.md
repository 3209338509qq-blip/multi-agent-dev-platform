# 大学生班费管理系统

这是一个基于FastAPI的后端API，用于管理大学生班级的班费收支。

## 功能特性

1. **成员管理**
   - 创建班级成员
   - 查询单个成员信息
   - 获取所有成员列表

2. **收支记录管理**
   - 记录收入和支出
   - 按多种条件筛选记录
   - 获取账户概览（总余额、总收入、总支出）

3. **自动计算**
   - 实时计算当前余额
   - 动态汇总收支统计

## 技术栈

- Python 3.8+
- FastAPI - 现代、快速的Web框架
- SQLAlchemy - Python SQL工具包和ORM
- Pydantic v2 - 数据验证和设置管理
- SQLite - 轻量级数据库（可轻松切换为其他数据库）

## 安装与运行

1. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```

2. 运行服务器
   ```bash
   python app.py
   ```
   或者直接使用uvicorn:
   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

3. 访问API文档
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

## API端点

### 成员管理
- `POST /api/members/` - 创建新成员
- `GET /api/members/` - 获取所有成员
- `GET /api/members/{member_id}` - 获取指定成员

### 收支记录
- `POST /api/transactions/` - 创建收支记录
- `GET /api/transactions/` - 获取收支记录（支持筛选）
- `GET /api/transactions/{transaction_id}` - 获取指定记录
- `GET /api/account/summary` - 获取账户概览

### 筛选参数
- `type_filter`: 按类型筛选 (income/expense)
- `member_id`: 按成员ID筛选
- `start_date`: 开始日期
- `end_date`: 结束日期

## 测试

运行测试:
```bash
pytest tests/ -v
```

## 数据库

默认使用SQLite数据库文件 `class_fund.db`。如需切换到其他数据库（如PostgreSQL），修改 `database.py` 和 `app.py` 中的连接字符串即可。

## 项目结构

```
class-fund-backend/
├── app.py              # 主应用入口
├── database.py         # 数据库配置
├── models.py           # SQLAlchemy模型
├── schemas.py          # Pydantic数据模式
├── routes/             # 路由模块
│   ├── __init__.py
│   ├── members.py      # 成员相关路由
│   └── transactions.py # 收支记录路由
├── tests/              # 测试代码
│   └── test_api.py
├── requirements.txt    # 依赖列表
└── README.md           # 项目说明
```

## 使用示例

### 创建成员
```bash
curl -X POST "http://localhost:8000/api/members/" \
  -H "Content-Type: application/json" \
  -d '{"name": "张三", "student_id": "2023001"}'
```

### 创建收入记录
```bash
curl -X POST "http://localhost:8000/api/transactions/" \
  -H "Content-Type: application/json" \
  -d '{"amount": 500.0, "description": "班费收入", "type": "income", "member_id": 1}'
```

### 获取账户概览
```bash
curl -X GET "http://localhost:8000/api/account/summary"
```

## 注意事项

1. 首次运行时会自动创建数据库和表
2. 所有金额使用浮点数，请注意精度问题
3. 生产环境建议更换为PostgreSQL等更强大的数据库
4. 可通过FastAPI自动生成的文档进行API测试