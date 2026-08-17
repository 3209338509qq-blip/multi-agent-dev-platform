from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database import Base


class TransactionType(str, enum.Enum):
    INCOME = "income"  # 收入
    EXPENSE = "expense"  # 支出


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    student_id = Column(String, unique=True, index=True)

    # 与收支记录的关系
    transactions = relationship("Transaction", back_populates="member")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    type = Column(Enum(TransactionType), nullable=False)
    timestamp = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # 外键关联成员
    member_id = Column(Integer, ForeignKey("members.id"))
    
    # 与成员的关系
    member = relationship("Member", back_populates="transactions")