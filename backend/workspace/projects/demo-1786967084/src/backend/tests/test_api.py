import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app
from database import Base, get_db

# 使用测试数据库
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# 覆盖数据库依赖
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    # 创建测试表
    Base.metadata.create_all(bind=engine)
    yield
    # 测试后清理
    Base.metadata.drop_all(bind=engine)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "大学生班费管理系统 API"}


def test_create_member():
    # 测试创建成员
    member_data = {
        "name": "张三",
        "student_id": "2023001"
    }
    response = client.post("/api/members/", json=member_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == member_data["name"]
    assert data["student_id"] == member_data["student_id"]
    assert "id" in data
    
    # 测试重复学号
    response2 = client.post("/api/members/", json=member_data)
    assert response2.status_code == 400
    assert response2.json()["detail"] == "学号已存在"


def test_create_transaction():
    # 先创建一个成员
    member_data = {"name": "李四", "student_id": "2023002"}
    member_response = client.post("/api/members/", json=member_data)
    member_id = member_response.json()["id"]
    
    # 创建收入记录
    income_data = {
        "amount": 500.0,
        "description": "班费收入",
        "type": "income",
        "member_id": member_id
    }
    response = client.post("/api/transactions/", json=income_data)
    assert response.status_code == 200
    data = response.json()
    assert data["amount"] == 500.0
    assert data["type"] == "income"
    assert data["member_id"] == member_id
    assert data["member_name"] == "李四"
    
    # 创建支出记录
    expense_data = {
        "amount": 120.5,
        "description": "购买活动用品",
        "type": "expense",
        "member_id": member_id
    }
    response2 = client.post("/api/transactions/", json=expense_data)
    assert response2.status_code == 200
    assert response2.json()["type"] == "expense"


def test_account_summary():
    # 创建成员和记录
    member_data = {"name": "王五", "student_id": "2023003"}
    member_response = client.post("/api/members/", json=member_data)
    member_id = member_response.json()["id"]
    
    # 创建一些收支记录
    transactions = [
        {"amount": 1000.0, "description": "班费收入", "type": "income", "member_id": member_id},
        {"amount": 200.0, "description": "打印资料", "type": "expense", "member_id": member_id},
        {"amount": 150.0, "description": "购买文具", "type": "expense", "member_id": member_id}
    ]
    
    for trans in transactions:
        client.post("/api/transactions/", json=trans)
    
    # 获取账户概览
    response = client.get("/api/account/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_income"] == 1000.0
    assert data["total_expense"] == 350.0  # 200 + 150
    assert data["balance"] == 650.0  # 1000 - 350
    assert len(data["recent_transactions"]) == 3  # 应该有3条记录
    
    # 验证最近记录是按时间倒序
    timestamps = [trans["timestamp"] for trans in data["recent_transactions"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_filter_transactions():
    # 创建成员
    member_data = {"name": "赵六", "student_id": "2023004"}
    member_response = client.post("/api/members/", json=member_data)
    member_id = member_response.json()["id"]
    
    # 创建不同类型记录
    client.post("/api/transactions/", json={
        "amount": 300.0, "description": "班费收入", "type": "income", "member_id": member_id
    })
    client.post("/api/transactions/", json={
        "amount": 50.0, "description": "购买零食", "type": "expense", "member_id": member_id
    })
    
    # 按类型筛选
    response = client.get("/api/transactions/?type_filter=income")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "income"
    
    # 按成员ID筛选
    response2 = client.get(f"/api/transactions/?member_id={member_id}")
    assert response2.status_code == 200
    assert len(response2.json()) == 2


def test_validation_errors():
    # 测试无效的成员创建请求
    invalid_member = {"name": "", "student_id": ""}
    response = client.post("/api/members/", json=invalid_member)
    # Pydantic验证应该捕获错误
    assert response.status_code == 422
    
    # 测试无效的收支记录（成员不存在）
    invalid_transaction = {
        "amount": 100.0,
        "description": "测试",
        "type": "income",
        "member_id": 9999  # 不存在的ID
    }
    response2 = client.post("/api/transactions/", json=invalid_transaction)
    assert response2.status_code == 404
    assert response2.json()["detail"] == "成员未找到"


def test_get_member():
    # 创建成员
    member_data = {"name": "测试成员", "student_id": "2023005"}
    create_response = client.post("/api/members/", json=member_data)
    member_id = create_response.json()["id"]
    
    # 获取单个成员
    response = client.get(f"/api/members/{member_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "测试成员"
    
    # 获取不存在的成员
    response2 = client.get("/api/members/9999")
    assert response2.status_code == 404


def test_get_members_list():
    # 创建几个成员
    for i in range(3):
        client.post("/api/members/", json={"name": f"成员{i}", "student_id": f"202300{i+10}"})
    
    # 获取成员列表
    response = client.get("/api/members/")
    assert response.status_code == 200
    assert len(response.json()) >= 3
    
    # 测试分页
    response2 = client.get("/api/members/?skip=1&limit=2")
    assert response2.status_code == 200
    assert len(response2.json()) <= 2