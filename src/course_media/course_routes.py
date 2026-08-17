from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .course_delivery import (
    CourseUploadRequest,
    EducatorReport,
    EducatorReportRequest,
    build_educator_report,
    resize_course_image,
)
from .infrai_storage import InfraiError, InfraiStorage

BUCKET = os.environ.get("COURSE_MEDIA_BUCKET", "course-media")
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


class CourseImageResult(BaseModel):
    course_id: UUID
    original_key: str
    thumbnail_key: str
    thumbnail_width: int = 640
    thumbnail_height: int = 360
    deadline: datetime


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = InfraiStorage()
    await storage.create_bucket(BUCKET)
    app.state.storage = storage
    yield
    await storage.close()


app = FastAPI(title="Course image and deadline service", lifespan=lifespan)


@app.post("/courses/image", response_model=CourseImageResult)
async def upload_course_image(
    course_id: Annotated[UUID, Form()],
    title: Annotated[str, Form(min_length=1, max_length=120)],
    deadline: Annotated[datetime, Form()],
    image: Annotated[UploadFile, File()],
) -> CourseImageResult:
    request = CourseUploadRequest(course_id=course_id, title=title, deadline=deadline)
    content = await image.read(MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image must be between 1 byte and 12 MiB")
    try:
        thumbnail = resize_course_image(content)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Upload a readable image") from exc

    request_id = str(uuid4())
    original_key = f"courses/{request.course_id}/original/{request_id}"
    thumbnail_key = f"courses/{request.course_id}/thumbnail/{request_id}.jpg"
    storage: InfraiStorage = app.state.storage
    try:
        original = await storage.presign_put(
            BUCKET, original_key, image.content_type or "application/octet-stream", len(content), request_id + "-original"
        )
        thumb = await storage.presign_put(
            BUCKET, thumbnail_key, "image/jpeg", len(thumbnail), request_id + "-thumbnail"
        )
        await storage.upload_signed(original["url"], content, image.content_type or "application/octet-stream")
        await storage.upload_signed(thumb["url"], thumbnail, "image/jpeg")
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    return CourseImageResult(
        course_id=request.course_id,
        original_key=original_key,
        thumbnail_key=thumbnail_key,
        deadline=request.deadline,
    )


@app.post("/educator/report", response_model=EducatorReport)
async def educator_report(request: EducatorReportRequest) -> EducatorReport:
    return build_educator_report(request, datetime.now(timezone.utc))
