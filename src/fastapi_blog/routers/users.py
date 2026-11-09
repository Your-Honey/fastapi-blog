from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_blog import modals
from fastapi_blog.database import get_db
from fastapi_blog.schemas import (
    PostResponse,
    Token,
    UserCreate,
    UserPrivateResponse,
    UserPublicResponse,
    UserUpdate,
)

from ..auth import (
    create_access_token,
    hash_password,
    oauth2_scheme,
    verify_access_token,
    verify_password,
)
from ..config import settings

router = APIRouter()


@router.get("/{user_id}/posts", response_model=list[PostResponse])
async def get_user_post(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    result = await db.execute(
        select(modals.Post)
        .options(selectinload(modals.Post.author))
        .where(modals.Post.user_id == user_id)
    )
    posts = result.scalars().all()
    return posts


@router.post(
    "", response_model=UserPrivateResponse, status_code=status.HTTP_201_CREATED
)
async def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(modals.User).where(
            func.lower(modals.User.username) == user.username.lower()
        )
    )
    existing_user_name = result.scalars().first()
    if existing_user_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="UserName already exists"
        )

    result = await db.execute(
        select(modals.User).where(func.lower(modals.User.email) == user.email.lower())
    )
    existing_user_email = result.scalars().first()
    if existing_user_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )

    new_user = modals.User(
        username=user.username,
        email=user.email.lower(),
        password_hash=hash_password(user.password),
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(modals.User).where(
            func.lower(modals.User.email) == form_data.username.lower()
        )
    )
    user = result.scalars().first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expire = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expire
    )
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserPrivateResponse)
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user_id = verify_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id_int = int(user_id)
    except TypeError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = await db.execute(select(modals.User).where(modals.User.id == user_id_int))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("/{user_id}", response_model=UserPublicResponse)
async def get_user(user_id, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if user:
        return user

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.patch("/{user_id}", response_model=UserPrivateResponse)
async def user_update(
    user_id: int, user_body: UserUpdate, db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user_body.username is not None and user_body.username.lower() != user.username:
        result = await db.execute(
            select(modals.User).where(
                func.lower(modals.User.username) == user_body.username.lower()
            )
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="User Name already exists"
            )

    if user_body.email is not None and user_body.email.lower() != user.email:
        result = await db.execute(
            select(modals.User).where(
                func.lower(modals.User.email) == user_body.email.lower()
            )
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
            )

    update_user = user_body.model_dump(exclude_unset=True)

    for key, value in update_user.items():
        setattr(user, key, value.lower())

    await db.commit()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def user_delete(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    await db.delete(user)
    await db.commit()
