from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_swagger_ui_theme import setup_swagger_ui_theme
from sqlalchemy import select
from sqlalchemy.orm import Session
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

Base.metadata.create_all(bind=engine)

# 1. Disable the default documentation URL add dark theme
app = FastAPI(docs_url=None)
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
def get_posts(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.Post))
    posts = result.scalars().all()
    return posts


@app.get("/api/posts/{post_id}", response_model=PostResponse)
def get_post(post_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.Post).where(modals.Post.id == post_id))
    post = result.scalars().first()
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.post(
    "/api/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED
)
def create_post(post: PostCreate, db: Annotated[Session, Depends(get_db)]):
    new_post = modals.Post(title=post.title, content=post.content, user_id=post.user_id)
    db.add(new_post)
    db.commit()
    return new_post


@app.patch("/api/posts/{post_id}", response_model=PostResponse)
def post_update(
    post_id: int, post_body: PostUpdate, db: Annotated[Session, Depends(get_db)]
):
    result = db.execute(select(modals.Post).where(modals.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = post_body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(post, key, value)

    db.commit()
    return post


@app.delete("/api/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def post_delete(post_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.Post).where(modals.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    db.delete(post)
    db.commit()


@app.get("/api/users/{user_id}/posts", response_model=list[PostResponse])
def get_user_post(user_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    result = db.execute(select(modals.Post).where(modals.Post.user_id == user_id))
    posts = result.scalars().all()
    return posts


@app.post(
    "/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def create_user(user: UserCreate, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(modals.User).where(modals.User.username == user.username.lower())
    )
    existing_user_name = result.scalars().first()
    if existing_user_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="UserName already exists"
        )

    result = db.execute(
        select(modals.User).where(modals.User.email == user.email.lower())
    )
    existing_user_email = result.scalars().first()
    if existing_user_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
        )

    new_user = modals.User(username=user.username.lower(), email=user.email.lower())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.get("/api/users/{user_id}", response_model=UserResponse)
def get_user(user_id, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if user:
        return user

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@app.patch("/api/users/{user_id}", response_model=UserResponse)
def user_update(
    user_id: int, user_body: UserUpdate, db: Annotated[Session, Depends(get_db)]
):
    result = db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user_body.username is not None and user_body.username.lower() != user.username:
        result = db.execute(
            select(modals.User).where(
                modals.User.username == user_body.username.lower()
            )
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="User Name already exists"
            )

    if user_body.email is not None and user_body.email.lower() != user.email:
        result = db.execute(
            select(modals.User).where(modals.User.email == user_body.email.lower())
        )
        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
            )

    update_user = user_body.model_dump(exclude_unset=True)

    for key, value in update_user.items():
        setattr(user, key, value.lower())

    db.commit()
    return user


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def user_delete(user_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(modals.User).where(modals.User.id == user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    db.delete(user)
    db.commit()


## RequestValidationError Handler
@app.exception_handler(RequestValidationError)
def validation_execption_handler(request: Request, exception: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"details": exception.errors()},
    )


## StarlettHttpException Handler 	Developer manually using raise HTTPException(...) or broken URLs.
@app.exception_handler(StarletteHTTPException)
def general_HTTP_exception_handler(request: Request, exception: StarletteHTTPException):
    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )
    return JSONResponse(status_code=exception.status_code, content={"details": message})
