from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

databse_url = "sqlite:///./blog.db"

engine = create_engine(
    databse_url,
    connect_args={"check_same_thread": False},  ##only needed for sqllite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db
