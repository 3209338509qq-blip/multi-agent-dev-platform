from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime

from database import get_db
from models import Transaction, TransactionType, Member
from schemas import TransactionCreate, TransactionResponse, AccountSummary

router = APIRouter()


@router.post("/transactions/", response_model=TransactionResponse)
def create_transaction(transaction: TransactionCreate, db: Session = Depends(get_db)):
    # 验证成员是否存在
    member = db.query(Member).filter(Member.id == transaction.member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="成员未找到")
    
    new_transaction = Transaction(
        amount=transaction.amount,
        description=transaction.description,
        type=transaction.type,
        member_id=transaction.member_id
    )
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    # 构建响应，包含成员名
    response = TransactionResponse(
        id=new_transaction.id,
        amount=new_transaction.amount,
        description=new_transaction.description,
        type=new_transaction.type,
        timestamp=new_transaction.timestamp,
        member_id=new_transaction.member_id,
        member_name=member.name
    )
    return response


@router.get("/transactions/", response_model=List[TransactionResponse])
def read_transactions(
    skip: int = 0, 
    limit: int = 100, 
    type_filter: Optional[TransactionType] = Query(None, description="按类型筛选: income 或 expense"),
    member_id: Optional[int] = Query(None, description="按成员ID筛选"),
    start_date: Optional[datetime] = Query(None, description="开始日期(ISO格式)"),
    end_date: Optional[datetime] = Query(None, description="结束日期(ISO格式)"),
    db: Session = Depends(get_db)
):
    query = db.query(Transaction)
    
    # 应用筛选条件
    if type_filter:
        query = query.filter(Transaction.type == type_filter)
    if member_id:
        query = query.filter(Transaction.member_id == member_id)
    if start_date:
        query = query.filter(Transaction.timestamp >= start_date)
    if end_date:
        query = query.filter(Transaction.timestamp <= end_date)
    
    # 按时间降序排序
    transactions = query.order_by(desc(Transaction.timestamp)).offset(skip).limit(limit).all()
    
    # 为了响应添加成员名，需要查询成员信息
    result = []
    for t in transactions:
        member = db.query(Member).filter(Member.id == t.member_id).first()
        response = TransactionResponse(
            id=t.id,
            amount=t.amount,
            description=t.description,
            type=t.type,
            timestamp=t.timestamp,
            member_id=t.member_id,
            member_name=member.name if member else "未知成员"
        )
        result.append(response)
    
    return result


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def read_transaction(transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="记录未找到")
    
    member = db.query(Member).filter(Member.id == transaction.member_id).first()
    response = TransactionResponse(
        id=transaction.id,
        amount=transaction.amount,
        description=transaction.description,
        type=transaction.type,
        timestamp=transaction.timestamp,
        member_id=transaction.member_id,
        member_name=member.name if member else "未知成员"
    )
    return response


@router.get("/account/summary", response_model=AccountSummary)
def get_account_summary(db: Session = Depends(get_db)):
    # 计算总收入
    total_income = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == TransactionType.INCOME
    ).scalar() or 0.0
    
    # 计算总支出
    total_expense = db.query(func.sum(Transaction.amount)).filter(
        Transaction.type == TransactionType.EXPENSE
    ).scalar() or 0.0
    
    # 计算余额
    balance = total_income - total_expense
    
    # 获取最近10条记录
    recent_transactions_raw = db.query(Transaction).order_by(
        desc(Transaction.timestamp)
    ).limit(10).all()
    
    recent_transactions = []
    for t in recent_transactions_raw:
        member = db.query(Member).filter(Member.id == t.member_id).first()
        recent_transactions.append(TransactionResponse(
            id=t.id,
            amount=t.amount,
            description=t.description,
            type=t.type,
            timestamp=t.timestamp,
            member_id=t.member_id,
            member_name=member.name if member else "未知成员"
        ))
    
    return AccountSummary(
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        recent_transactions=recent_transactions
    )