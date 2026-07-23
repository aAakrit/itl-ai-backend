from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from app.db import Base, engine

# Import models so SQLAlchemy registers them
from app.models.user import User
from app.models.session import AuthSession

# Routes
from app.routes.auth import router as auth_router
from app.routes.cms_page import router as cms_page_router
from app.routes.admin_user import router as admin_user
from app.routes.books import router as admin_books

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ITL AI Backend",
    version="1.0.0",
    default_response_class=ORJSONResponse,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
)


@app.get("/")
def root():
    return {
        "message": "ITL AI Backend Running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


app.include_router(auth_router)
app.include_router(cms_page_router)
app.include_router(admin_user)
app.include_router(admin_books)