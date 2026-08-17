from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class MemberCreate(BaseModel):
    name: str
    student_id: str


class MemberResponse(BaseModel):
    id: int
    name: str
    student_id: str

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    amount: float
    description: str
    type: TransactionType
    member_id: int


class TransactionResponse(BaseModel):
    id: int
    amount: float
    description: str
    type: TransactionType
    timestamp: datetime
    member_id: int
    member_name: Optional[str] = None  # 可选，用于展示成员名

    class Config:
        from_attributes = True


class AccountSummary(BaseModel):
    total_income: float
    total_expense: float
    balance: float
    recent_transactions: list[TransactionResponse]