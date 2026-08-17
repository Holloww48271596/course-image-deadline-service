from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from io import BytesIO
from uuid import UUID

from PIL import Image, ImageOps
from pydantic import BaseModel, Field


class LearnerState(StrEnum):
    ON_TIME = "on_time"
    DUE = "due"
    OVERDUE = "overdue"


class CourseUploadRequest(BaseModel):
    course_id: UUID
    title: str = Field(min_length=1, max_length=120)
    deadline: datetime


class LearnerSubmission(BaseModel):
    learner_id: UUID
    submitted_at: datetime | None = None


class EducatorReportRequest(BaseModel):
    deadline: datetime
    learners: list[LearnerSubmission]


class EducatorReport(BaseModel):
    on_time: int
    due: int
    overdue: int


def resize_course_image(source: bytes, size: tuple[int, int] = (640, 360)) -> bytes:
    with Image.open(BytesIO(source)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=86, optimize=True)
        return output.getvalue()


def build_educator_report(request: EducatorReportRequest, now: datetime) -> EducatorReport:
    deadline = _utc(request.deadline)
    current = _utc(now)
    counts = {state: 0 for state in LearnerState}
    for learner in request.learners:
        if learner.submitted_at is not None and _utc(learner.submitted_at) <= deadline:
            state = LearnerState.ON_TIME
        elif current > deadline:
            state = LearnerState.OVERDUE
        else:
            state = LearnerState.DUE
        counts[state] += 1
    return EducatorReport(
        on_time=counts[LearnerState.ON_TIME],
        due=counts[LearnerState.DUE],
        overdue=counts[LearnerState.OVERDUE],
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
