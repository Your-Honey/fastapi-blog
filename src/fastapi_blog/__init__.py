from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi_swagger_ui_theme import setup_swagger_ui_theme
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi_blog import modals

from .database import Base, engine, get_db
from .schemas import (
    PostCreate,
    PostResponse,
    PostUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )  # create databse table if they dont exist.
    yield
    # Shutdown
    await engine.dispose()


# 1. Disable the default documentation URL add dark theme
app = FastAPI(lifespan=lifespan, docs_url=None)
setup_swagger_ui_theme(app, docs_path="/docs")

app.mount(
    "/media",
    StaticFiles(directory=Path(__file__).parent / "media"),
    name="media",
)


@app.get("/")
def home():
    return {"message": "Hello world"}


@app.get("/api/posts", response_model=list[PostResponse])
async def get_posts(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(modals.Post).options(selectinload(modals.Post.author))
    )
    posts = result.scalars().all()
    return posts


@app.get("/api/posts/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(modals.Post)
        .options(selectinload(modals.Post.author))
        .where(modals.Post.id == post_id)
    )
    post = result.scalars().first()
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.post(
    "/api/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED
)
async def create_post(post: PostCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    new_post = modals.Post(title=post.title, content=post.content, user_id=post.user_id)
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post, attribute_names=["auther"])
    return new_post


@app.patch("/api/posts/{post_id}", response_model=PostResponse)
async def post_update(
    post_id: int, post_body: PostUpdate, db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await db.execute(select(modals.Post).where(modals.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = post_body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(post, key, value)

    await db.commit()
    await db.refresh(post, attribute_names=["author"])
    return post


@app.delete("/api/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def post_delete(post_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.Post).where(modals.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await db.delete(post)
    await db.commit()


@app.get("/api/users/{user_id}/posts", response_model=list[PostResponse])
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


@app.post(
    "/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(modals.User).where(modals.User.username == user.username.lower())
    )
    existing_user_name = result.scalars().first()
    if existing_user_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="UserName already exists"
        )

    result = await db.execute(
        select(modals.User).where(modals.User.email == user.email.lower())
    )
    existing_user_email = result.scalars().first()
    if existing_user_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )

    new_user = modals.User(username=user.username.lower(), email=user.email.lower())
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@app.get("/api/users/{user_id}", response_model=UserResponse)
async def get_user(user_id, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if user:
        return user

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@app.patch("/api/users/{user_id}", response_model=UserResponse)
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
                modals.User.username == user_body.username.lower()
            )
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="User Name already exists"
            )

    if user_body.email is not None and user_body.email.lower() != user.email:
        result = await db.execute(
            select(modals.User).where(modals.User.email == user_body.email.lower())
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


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def user_delete(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    await db.delete(user)
    await db.commit()


## RequestValidationError Handler
@app.exception_handler(RequestValidationError)
async def validation_execption_handler(request: Request, exception: RequestValidationError):
    return await request_validation_exception_handler(request, exception)


## StarlettHttpException Handler 	Developer manually using raise HTTPException(...) or broken URLs.
@app.exception_handler(StarletteHTTPException)
async def general_HTTP_exception_handler(request: Request, exception: StarletteHTTPException):
    return await http_exception_handler(request, exception)
