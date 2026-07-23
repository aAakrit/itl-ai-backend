from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.schemas.cms_page import (
    CmsPageCreate,
    CmsPageList,
    CmsPageUpdate,
    CmsPageResponse,
)
from app.services import cms_page

router = APIRouter(
    prefix="/cms",
    tags=["CMS"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/pages", response_model=list[CmsPageList])
def list_pages(db: Session = Depends(get_db)):
    return cms_page.get_pages(db)

@router.get("/pages/{route}", response_model=CmsPageResponse)
def get_page(route: str, db: Session = Depends(get_db)):
    return cms_page.get_page(db, route)

@router.post("/pages", response_model=CmsPageResponse)
def create_page(
    page: CmsPageCreate,
    db: Session = Depends(get_db),
):
    return cms_page.create_page(db, page)

@router.put("/pages/{route}", response_model=CmsPageResponse)
def update_page(
    route: str,
    page: CmsPageUpdate,
    db: Session = Depends(get_db),
):
    return cms_page.update_page(db, route, page)

@router.delete("/pages/{route}")
def delete_page(
    route: str,
    db: Session = Depends(get_db),
):
    return cms_page.delete_page(db, route)