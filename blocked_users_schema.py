#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
جدول المستخدمين المحظورين في قاعدة البيانات - مصحح
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()

class BlockedUser(Base):
    """جدول المستخدمين المحظورين"""
    __tablename__ = 'blocked_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, unique=True, index=True)  # معرف المستخدم المحظور (BigInteger)
    blocked_by = Column(BigInteger, nullable=False)  # معرف المدير الذي حظره (BigInteger)
    blocked_at = Column(DateTime, default=func.now(), nullable=False)  # تاريخ الحظر
    reason = Column(Text, default="غير محدد")  # سبب الحظر
    is_active = Column(Boolean, default=True, nullable=False)  # هل الحظر نشط
    unblocked_by = Column(BigInteger, nullable=True)  # معرف المدير الذي ألغى الحظر (BigInteger)
    unblocked_at = Column(DateTime, nullable=True)  # تاريخ إلغاء الحظر
    notes = Column(Text, nullable=True)  # ملاحظات إضافية
    
    def __repr__(self):
        return f"<BlockedUser(user_id={self.user_id}, blocked_by={self.blocked_by}, reason='{self.reason}')>"

def create_blocked_users_table(engine):
    """إنشاء جدول المستخدمين المحظورين"""
    try:
        Base.metadata.create_all(engine)
        print("✅ تم إنشاء جدول المستخدمين المحظورين بنجاح")
        return True
    except Exception as e:
        print(f"❌ خطأ في إنشاء جدول المستخدمين المحظورين: {e}")
        return False

# دوال إدارة المستخدمين المحظورين
def block_user_in_db(session, user_id: int, blocked_by: int, reason: str = "غير محدد"):
    """حظر مستخدم في قاعدة البيانات"""
    try:
        # التحقق من وجود المستخدم محظور بالفعل
        existing = session.query(BlockedUser).filter(
            BlockedUser.user_id == user_id,
            BlockedUser.is_active == True
        ).first()
        
        if existing:
            return False, "المستخدم محظور بالفعل"
        
        # إنشاء سجل حظر جديد
        blocked_user = BlockedUser(
            user_id=user_id,
            blocked_by=blocked_by,
            reason=reason,
            is_active=True
        )
        
        session.add(blocked_user)
        session.commit()
        
        return True, "تم حظر المستخدم بنجاح"
        
    except Exception as e:
        session.rollback()
        return False, f"خطأ في حظر المستخدم: {e}"

def unblock_user_in_db(session, user_id: int, unblocked_by: int):
    """إلغاء حظر مستخدم في قاعدة البيانات"""
    try:
        # البحث عن المستخدم المحظور
        blocked_user = session.query(BlockedUser).filter(
            BlockedUser.user_id == user_id,
            BlockedUser.is_active == True
        ).first()
        
        if not blocked_user:
            return False, "المستخدم غير محظور"
        
        # إلغاء الحظر
        blocked_user.is_active = False
        blocked_user.unblocked_by = unblocked_by
        blocked_user.unblocked_at = datetime.now()
        
        session.commit()
        
        return True, "تم إلغاء حظر المستخدم بنجاح"
        
    except Exception as e:
        session.rollback()
        return False, f"خطأ في إلغاء حظر المستخدم: {e}"

def is_user_blocked_in_db(session, user_id: int):
    """التحقق من حظر المستخدم في قاعدة البيانات"""
    try:
        blocked_user = session.query(BlockedUser).filter(
            BlockedUser.user_id == user_id,
            BlockedUser.is_active == True
        ).first()
        
        return blocked_user is not None
        
    except Exception as e:
        print(f"خطأ في التحقق من حظر المستخدم: {e}")
        return False

def get_blocked_users_list_from_db(session, limit: int = 50):
    """الحصول على قائمة المستخدمين المحظورين من قاعدة البيانات"""
    try:
        blocked_users = session.query(BlockedUser).filter(
            BlockedUser.is_active == True
        ).order_by(BlockedUser.blocked_at.desc()).limit(limit).all()
        
        result = []
        for user in blocked_users:
            result.append({
                'user_id': user.user_id,
                'blocked_by': user.blocked_by,
                'blocked_at': user.blocked_at.isoformat() if user.blocked_at else None,
                'reason': user.reason or "غير محدد"
            })
        
        return result
        
    except Exception as e:
        print(f"خطأ في الحصول على قائمة المحظورين: {e}")
        return []

def get_blocked_user_info_from_db(session, user_id: int):
    """الحصول على معلومات المستخدم المحظور"""
    try:
        blocked_user = session.query(BlockedUser).filter(
            BlockedUser.user_id == user_id,
            BlockedUser.is_active == True
        ).first()
        
        if blocked_user:
            return {
                'user_id': blocked_user.user_id,
                'blocked_by': blocked_user.blocked_by,
                'blocked_at': blocked_user.blocked_at.isoformat() if blocked_user.blocked_at else None,
                'reason': blocked_user.reason or "غير محدد"
            }
        
        return None
        
    except Exception as e:
        print(f"خطأ في الحصول على معلومات المستخدم المحظور: {e}")
        return None

