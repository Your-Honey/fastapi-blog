from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from datetime import date

from .schemas import PostCreate, PostResponse

app = FastAPI()

posts: list[dict] = [
    {
        "id": 1,
        "author": "Corey Schafer",
        "title": "FastAPI is Awesome",
        "content": "This framework is really easy to use and super fast.",
        "date_posted": "April 20, 2025",
    },
    {
        "id": 2,
        "author": "Jane Doe",
        "title": "Python is Great for Web Development",
        "content": "Python is a great language for web development, and FastAPI makes it even better.",
        "date_posted": "April 21, 2025",
    },
]


@app.get("/")
def home():
    return {"message": "Hello world"}


@app.get("/api/posts", response_model=list[PostResponse])
def get_posts():
    return posts


@app.get("/api/posts/{post_id}", response_model=PostResponse)
def get_post(post_id: int):
    post = next((post for post in posts if post["id"] == post_id), None)
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.post(
    "/api/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED
)
def create_post(post: PostCreate):
    new_id = max(p["id"] for p in posts) + 1 if posts else 1
    new_post: PostResponse = {
        "id": new_id,
        "title": post.title,
        "content": post.content,
        "author": post.author,
        "date_posted": str(date.today()),
    }
    posts.append(new_post)
    return new_post


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
