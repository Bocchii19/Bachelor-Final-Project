"""Classes API — CRUD for class management."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.class_ import Class
from app.models.user import User
from app.schemas.class_ import ClassCreate, ClassRead, ClassUpdate

router = APIRouter()


@router.get("/", response_model=List[ClassRead])
async def list_classes(
    teacher_id: Optional[uuid.UUID] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """List all classes, optionally filter by teacher."""
    stmt = select(Class)
    if teacher_id:
        stmt = stmt.where(Class.teacher_id == teacher_id)
    stmt = stmt.order_by(Class.name).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=ClassRead, status_code=status.HTTP_201_CREATED)
async def create_class(
    body: ClassCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Create a new class."""
    cls = Class(**body.model_dump())
    db.add(cls)
    await db.flush()
    await db.refresh(cls)
    return cls


@router.get("/{class_id}", response_model=ClassRead)
async def get_class(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get a single class by ID."""
    result = await db.execute(select(Class).where(Class.id == class_id))
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    return cls


@router.patch("/{class_id}", response_model=ClassRead)
async def update_class(
    class_id: uuid.UUID,
    body: ClassUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Update a class."""
    result = await db.execute(select(Class).where(Class.id == class_id))
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(cls, key, value)

    await db.flush()
    await db.refresh(cls)
    return cls


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Delete a class."""
    result = await db.execute(select(Class).where(Class.id == class_id))
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")
    await db.delete(cls)
