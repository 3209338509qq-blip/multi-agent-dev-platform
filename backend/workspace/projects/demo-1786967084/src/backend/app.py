from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database import Base, get_db
from routes import members, transactions
import models

# 创建数据库表
SQLALCHEMY_DATABASE_URL = "sqlite:///./class_fund.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="大学生班费管理系统")

# 包含路由
app.include_router(members.router, prefix="/api", tags=["成员管理"])
app.include_router(transactions.router, prefix="/api", tags=["收支记录"])

@app.get("/")
def read_root():
    return {"message": "大学生班费管理系统 API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)