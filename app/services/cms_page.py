from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.cms_page import CmsPage
from app.schemas.cms_page import CmsPageCreate, CmsPageUpdate


def get_pages(db: Session):
    return db.query(CmsPage).order_by(CmsPage.title).all()


def get_page(db: Session, route: str):
    page = db.query(CmsPage).filter(CmsPage.route == route).first()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    return {
        "id": page.id,
        "route": page.route,
        "title": page.title,
        "content": page.content,
        "status": page.status,
    }


def create_page(db: Session, page: CmsPageCreate):
    existing = db.query(CmsPage).filter(CmsPage.route == page.route).first()

    if existing:
        raise HTTPException(status_code=400, detail="Page already exists")

    new_page = CmsPage(
        route=page.route,
        title=page.title,
        content=page.content,
    )

    db.add(new_page)
    db.commit()
    db.refresh(new_page)

    return new_page


def update_page(db: Session, route: str, page: CmsPageUpdate):
    existing = db.query(CmsPage).filter(CmsPage.route == route).first()

    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")

    existing.title = page.title
    existing.content = page.content

    db.commit()
    db.refresh(existing)

    return existing


def delete_page(db: Session, route: str):
    page = db.query(CmsPage).filter(CmsPage.route == route).first()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    db.delete(page)
    db.commit()

    return {"message": "Page deleted successfully"}