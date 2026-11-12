from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from PIL import UnidentifiedImageError
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from fastapi_blog import modals
from fastapi_blog.database import get_db
from fastapi_blog.image_utils import delete_profile_image, process_profile_image
from fastapi_blog.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    PostResponse,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserPrivateResponse,
    UserPublicResponse,
    UserUpdate,
)

from ..auth import (
    CurrentUser,
    create_access_token,
    generate_reset_token,
    hash_password,
    hash_reset_password,
    verify_password,
)
from ..config import settings
from ..email_utils import send_password_reset_mail

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


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(modals.User).where(
            func.lower(modals.User.email) == request_data.email.lower()
        )
    )
    user = result.scalars().first()

    if user:
        await db.execute(
            sql_delete(modals.PasswordResetToken).where(
                modals.PasswordResetToken.user_id == user.id
            )
        )
        token = generate_reset_token()
        hashed_token = hash_reset_password(token)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.reset_token_expire_minutes
        )
        reset_token = modals.PasswordResetToken(
            hashed_token=hashed_token, user_id=user.id, expires_at=expires_at
        )
        db.add(reset_token)
        await db.commit()

        background_tasks.add_task(
            send_password_reset_mail,
            to_email=user.email,
            username=user.username,
            token=token,
        )

        return {
            "message": "If an account exists with this email, you will receive password reset instructions."
        }


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    request_body: ResetPasswordRequest, db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(
        select(modals.PasswordResetToken).where(
            modals.PasswordResetToken.hashed_token
            == hash_reset_password(request_body.token)
        )
    )
    reset_token = result.scalars().first()
    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    if reset_token.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    result = await db.execute(
        select(modals.User).where(modals.User.id == reset_token.user_id)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    await db.execute(
        sql_delete(modals.PasswordResetToken).where(
            modals.PasswordResetToken.user_id == user.id
        )
    )

    user.password_hash = hash_password(request_body.new_password)
    await db.commit()
    return {
        "message": "Password reset successfully. You can now log in with your new password."
    }


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    request_body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not verify_password(request_body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(request_body.new_password)

    await db.execute(
        sql_delete(modals.PasswordResetToken).where(
            modals.PasswordResetToken.user_id == current_user.id,
        ),
    )

    await db.commit()
    return {"message": "Password changed successfully"}


@router.get("/me", response_model=UserPrivateResponse)
async def get_current_user(
    current_user: CurrentUser,
):
    return current_user


@router.get("/{user_id}", response_model=UserPublicResponse)
async def get_user(user_id, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if user:
        return user

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.patch("/{user_id}", response_model=UserPrivateResponse)
async def user_update(
    user_id: int,
    user_body: UserUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user",
        )
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
async def user_delete(
    user_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user",
        )
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    profile_image_file = user.image_file

    await db.delete(user)
    await db.commit()

    if profile_image_file is not None:
        delete_profile_image(profile_image_file)


@router.patch("/{user_id}/profile", response_model=UserPrivateResponse)
async def upload_profile_picture(
    user_id: int,
    file: UploadFile,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's picture",
        )

    content = await file.read()

    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.max_upload_size_bytes // (1024 * 1024)}MB",
        )

    try:
        new_filename = await run_in_threadpool(process_profile_image, content)
    except UnidentifiedImageError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file. Please upload a valid image (JPEG, PNG, GIF, WebP).",
        ) from err

    old_profile_file = current_user.image_file

    current_user.image_file = new_filename
    await db.commit()
    await db.refresh(current_user)

    if old_profile_file:
        delete_profile_image(old_profile_file)

    return current_user


@router.delete("/{user_id}/delete", response_model=UserPrivateResponse)
async def delete_profile_pic(
    user_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's picture",
        )
    old_profile_file = current_user.image_file
    if old_profile_file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profile picture to delete",
        )

    current_user.image_file = None

    await db.commit()
    await db.refresh(current_user)

    delete_profile_image(old_profile_file)

    return current_user
