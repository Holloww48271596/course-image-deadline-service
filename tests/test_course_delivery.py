from datetime import datetime, timezone
from uuid import UUID

from course_media.course_delivery import EducatorReportRequest, LearnerSubmission, build_educator_report


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
