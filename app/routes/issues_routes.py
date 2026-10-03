from urllib.parse import urlparse

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request, Query, status
from typing import Optional, List

from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_

from app.database import AsyncSessionLocal
from app.deps.admin import require_admin
from app.models.issue import Issue, IssueType, IssueStatus
from app.schemas.issue_schemas import IssueOut, IssueStatusUpdate
from app.s3 import upload_to_s3, delete_from_s3

# If you want to rate-limit, uncomment the next 2 lines and decorate the endpoint
# from app.limiter import limiter
# from slowapi.util import get_remote_address

router = APIRouter(prefix="/issues", tags=["issues"])

# Your usual DB dep pattern
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

def _upload_screenshot(file: UploadFile) -> str:
    """
    Uses your helper: upload_to_s3(fileobj, filename, content_type, folder=..., subfolder=...)
    Returns the public URL your helper produces.
    """
    return upload_to_s3(
        file.file,
        file.filename or "screenshot.png",
        file.content_type or "image/png",
        folder="issues",
        subfolder="screenshots",   # 👈 now stored under issues/screenshots/
    )


def _extract_s3_key(url: str) -> Optional[str]:
    try:
        p = urlparse(url)
        key = p.path.lstrip("/")
        return key or None
    except Exception:
        return None
# Anyone can report — no auth dependency here
@router.post("/report", response_model=IssueOut, status_code=201)
# @limiter.limit("15/minute")  # optional
async def report_issue(
    request: Request,
    db: AsyncSession = Depends(get_db),
    type: str = Form(...),
    title: str = Form(..., max_length=200),
    description: str = Form(...),
    page_url: Optional[str] = Form(None),
    email: Optional[EmailStr] = Form(None),
    screenshot: Optional[UploadFile] = File(None),
):
    # Validate enum
    try:
        issue_type = IssueType(type)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid issue type")

    screenshot_url: Optional[str] = None
    if screenshot is not None:
        try:
            screenshot_url = _upload_screenshot(screenshot)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Screenshot upload failed: {e}")

    user_agent = request.headers.get("user-agent")

    issue = Issue(
        type=issue_type,
        title=title.strip(),
        description=description.strip(),
        page_url=(page_url or "").strip() or None,
        email=str(email) if email else None,
        screenshot_url=screenshot_url,
        user_id=None,  # always anonymous
        user_agent=user_agent[:512] if user_agent else None,
    )

    db.add(issue)
    await db.commit()
    await db.refresh(issue)
    return issue

# Optional: simple list endpoint (no auth), for internal checks or admin UI later.
# If you prefer admin-only, add your existing auth dep and guard here.
# ---- Public: list (with filters)
@router.get("", response_model=List[IssueOut])
async def list_issues(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
    q: Optional[str] = Query(None, description="Search in title/description"),
    type: Optional[str] = Query(None, description="BUG|FEATURE|CONTENT|OTHER"),
    status: Optional[str] = Query(None, description="OPEN|IN_PROGRESS|FIXED|WONT_FIX"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    stmt = select(Issue)

    if type:
        try:
            stmt = stmt.where(Issue.type == IssueType(type))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid issue type")

    if status:
        try:
            stmt = stmt.where(Issue.status == IssueStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid issue status")

    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Issue.title.ilike(like), Issue.description.ilike(like)))

    stmt = stmt.order_by(desc(Issue.created_at)).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return rows



# ---- Admin: set status / notes
@router.patch("/{issue_id}/status", response_model=IssueOut)
async def update_issue_status(
    issue_id: int,
    payload: IssueStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    issue = (await db.execute(select(Issue).where(Issue.id == issue_id))).scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue.status = IssueStatus(payload.status) if isinstance(payload.status, str) else payload.status
    issue.admin_notes = payload.admin_notes

    await db.commit()
    await db.refresh(issue)
    return issue


# ---- Admin: delete (also delete S3 screenshot if present)
@router.delete("/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    issue = (await db.execute(select(Issue).where(Issue.id == issue_id))).scalars().first()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Remove screenshot (works for both old path 'issues/covers/...' and new 'issues/screenshots/...')
    if issue.screenshot_url:
        key = _extract_s3_key(issue.screenshot_url)
        if key:
            try:
                delete_from_s3(key)
            except Exception as e:
                print(f"[issues] Warning: failed to delete S3 object {key}: {e}")

    await db.delete(issue)
    await db.commit()
    return
