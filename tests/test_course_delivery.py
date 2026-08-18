from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from fastapi.testclient import TestClient
from PIL import Image

from course_media.course_delivery import EducatorReportRequest, LearnerSubmission, build_educator_report
from course_media.course_routes import app


def test_report_separates_late_missing_and_on_time_work() -> None:
    deadline = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    request = EducatorReportRequest(
        deadline=deadline,
        learners=[
            LearnerSubmission(
                learner_id=UUID("00000000-0000-0000-0000-000000000001"),
                submitted_at=datetime(2026, 9, 10, 15, 59, tzinfo=timezone.utc),
            ),
            LearnerSubmission(
                learner_id=UUID("00000000-0000-0000-0000-000000000002"),
                submitted_at=datetime(2026, 9, 10, 16, 1, tzinfo=timezone.utc),
            ),
            LearnerSubmission(learner_id=UUID("00000000-0000-0000-0000-000000000003")),
        ],
    )

    report = build_educator_report(
        request, now=datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)
    )

    assert report.model_dump() == {"on_time": 1, "due": 0, "overdue": 2}


def test_startup_creates_bucket_and_image_route_stores_both_objects(monkeypatch) -> None:
    calls: list[tuple] = []

    class FakeStorage:
        def __init__(self) -> None:
            calls.append(("init",))

        async def create_bucket(self, name: str) -> None:
            calls.append(("create_bucket", name))

        async def presign_put(
            self, bucket: str, key: str, content_type: str, max_bytes: int, request_id: str
        ) -> dict[str, str]:
            calls.append(("presign_put", bucket, key, content_type, max_bytes, request_id))
            return {"url": f"https://upload.invalid/{request_id}"}

        async def upload_signed(self, url: str, content: bytes, content_type: str) -> None:
            calls.append(("upload_signed", url, content, content_type))

        async def close(self) -> None:
            calls.append(("close",))

    monkeypatch.setattr("course_media.course_routes.InfraiStorage", FakeStorage)
    monkeypatch.setenv("COURSE_MEDIA_BUCKET", "test-course-media")
    image = BytesIO()
    Image.new("RGB", (800, 600), "red").save(image, format="JPEG")
    source = image.getvalue()

    with TestClient(app) as client:
        response = client.post(
            "/courses/image",
            data={
                "course_id": "65d764a8-833f-4baa-a6c1-ad4f89ce00ea",
                "title": "Lighting for interviews",
                "deadline": "2026-09-10T16:00:00Z",
            },
            files={"image": ("cover.jpg", source, "image/jpeg")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["original_key"].startswith(
        "courses/65d764a8-833f-4baa-a6c1-ad4f89ce00ea/original/"
    )
    assert body["thumbnail_key"].startswith(
        "courses/65d764a8-833f-4baa-a6c1-ad4f89ce00ea/thumbnail/"
    )
    assert body["thumbnail_width"] == 640
    assert body["thumbnail_height"] == 360
    assert body["deadline"] == "2026-09-10T16:00:00Z"
    assert calls[1] == ("create_bucket", "test-course-media")
    assert [call[0] for call in calls].count("presign_put") == 2
    uploads = [call for call in calls if call[0] == "upload_signed"]
    assert uploads[0][2] == source
    with Image.open(BytesIO(uploads[1][2])) as thumbnail:
        assert thumbnail.size == (640, 360)
    assert calls[-1] == ("close",)
