from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

from .course_delivery import (
    CourseUploadRequest,
    EducatorReport,
    EducatorReportRequest,
    build_educator_report,
    resize_course_image,
)
from .infrai_storage import InfraiStorage

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
THUMBNAIL_SIZE = (640, 360)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = InfraiStorage()
    app.state.storage = storage
    app.state.course_media_bucket = os.environ.get("COURSE_MEDIA_BUCKET", "course-media")
    try:
        await storage.create_bucket(app.state.course_media_bucket)
        yield
    finally:
        await storage.close()


app = FastAPI(title="Course image and deadline service", lifespan=lifespan)


@app.post("/courses/image")
async def upload_course_image(
    http_request: Request,
    course_id: Annotated[UUID, Form()],
    title: Annotated[str, Form(min_length=1, max_length=120)],
    deadline: Annotated[datetime, Form()],
    image: Annotated[UploadFile, File()],
) -> dict[str, str | int]:
    request = CourseUploadRequest(course_id=course_id, title=title, deadline=deadline)
    content = await image.read(MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image must be between 1 byte and 12 MiB")
    try:
        thumbnail = resize_course_image(content)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Upload a readable image") from exc

    storage: InfraiStorage = http_request.app.state.storage
    bucket: str = http_request.app.state.course_media_bucket
    request_id = str(uuid4())
    base_key = f"courses/{request.course_id}"
    original_key = f"{base_key}/original/{request_id}"
    thumbnail_key = f"{base_key}/thumbnail/{request_id}.jpg"
    source_content_type = image.content_type or "application/octet-stream"

    original_upload = await storage.presign_put(
        bucket, original_key, source_content_type, len(content), f"{request_id}-original"
    )
    thumbnail_upload = await storage.presign_put(
        bucket, thumbnail_key, "image/jpeg", len(thumbnail), f"{request_id}-thumbnail"
    )
    await storage.upload_signed(original_upload["url"], content, source_content_type)
    await storage.upload_signed(thumbnail_upload["url"], thumbnail, "image/jpeg")

    return {
        "course_id": str(request.course_id),
        "original_key": original_key,
        "thumbnail_key": thumbnail_key,
        "thumbnail_width": THUMBNAIL_SIZE[0],
        "thumbnail_height": THUMBNAIL_SIZE[1],
        "deadline": request.deadline.isoformat().replace("+00:00", "Z"),
    }


@app.post("/educator/report", response_model=EducatorReport)
async def educator_report(request: EducatorReportRequest) -> EducatorReport:
    return build_educator_report(request, datetime.now(timezone.utc))
