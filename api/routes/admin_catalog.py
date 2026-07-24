from fastapi import APIRouter, Query

from api.models import (
    CatalogAllResponse,
    CatalogAllItem,
    CatalogModifyRequest,
    CatalogModifyResponse,
    CatalogModifyResult,
)
from services.catalog_service import get_catalog_all, validate_book_for_catalog
from services.db import catalog_add, catalog_remove

router = APIRouter(prefix="/api/v1/admin/catalog", tags=["admin-catalog"])


@router.get("/all", response_model=CatalogAllResponse)
def list_all(q: str = Query(default="", description="搜索关键词")):
    items = get_catalog_all(book_id_filter=q if q else None)
    return CatalogAllResponse(books=[CatalogAllItem(**it) for it in items])


@router.post("/add", response_model=CatalogModifyResponse)
def add(req: CatalogModifyRequest):
    results = []
    for bid in req.book_ids:
        ready, err = validate_book_for_catalog(bid)
        if not ready:
            results.append(CatalogModifyResult(book_id=bid, status="rejected", error=err))
            continue
        inserted = catalog_add([bid])
        if inserted:
            results.append(CatalogModifyResult(book_id=bid, status="added"))
        else:
            results.append(CatalogModifyResult(book_id=bid, status="skipped", error="已在目录中"))
    added = sum(1 for r in results if r.status == "added")
    rejected = sum(1 for r in results if r.status == "rejected")
    skipped = sum(1 for r in results if r.status == "skipped")
    return CatalogModifyResponse(
        results=results,
        summary={"total": len(req.book_ids), "added": added, "rejected": rejected, "skipped": skipped},
    )


@router.post("/remove", response_model=CatalogModifyResponse)
def remove(req: CatalogModifyRequest):
    removed = catalog_remove(req.book_ids)
    results = []
    for bid in req.book_ids:
        if bid in removed:
            results.append(CatalogModifyResult(book_id=bid, status="removed"))
        else:
            results.append(CatalogModifyResult(book_id=bid, status="skipped", error="不在目录中"))
    return CatalogModifyResponse(
        results=results,
        summary={"total": len(req.book_ids), "removed": len(removed), "skipped": len(req.book_ids) - len(removed)},
    )
