from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Member
from schemas import MemberCreate, MemberResponse

router = APIRouter()


@router.post("/members/", response_model=MemberResponse)
def create_member(member: MemberCreate, db: Session = Depends(get_db)):
    # 检查学号是否已存在
    db_member = db.query(Member).filter(Member.student_id == member.student_id).first()
    if db_member:
        raise HTTPException(status_code=400, detail="学号已存在")
    
    new_member = Member(name=member.name, student_id=member.student_id)
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    return new_member


@router.get("/members/", response_model=List[MemberResponse])
def read_members(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    members = db.query(Member).offset(skip).limit(limit).all()
    return members


@router.get("/members/{member_id}", response_model=MemberResponse)
def read_member(member_id: int, db: Session = Depends(get_db)):
    db_member = db.query(Member).filter(Member.id == member_id).first()
    if db_member is None:
        raise HTTPException(status_code=404, detail="成员未找到")
    return db_member