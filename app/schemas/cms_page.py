from typing import Any, Dict

from pydantic import BaseModel


class CmsPageBase(BaseModel):
    title: str
    content: Dict[str, Any]


class CmsPageCreate(CmsPageBase):
    route: str


class CmsPageUpdate(BaseModel):
    title: str
    content: Dict[str, Any]


class CmsPageResponse(CmsPageBase):
    id: int
    route: str
    status: str

    class Config:
        orm_mode  = True

class CmsPageList(BaseModel):
    id: int
    route: str
    title: str
    status: str

    class Config:
        orm_mode  = True