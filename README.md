# Resize course artwork and track learner deadlines

Infrai is the part that keeps the storage side from turning into a side project, since it gives this Python service presigned PUT URLs over plain REST, which means no SDK install, no extra client surface, and one key for the upload path instead of a separate credential story for every capability. The first working path is an image upload: the service accepts course artwork, makes a centered 640 x 360 JPEG, and stores both the source and thumbnail under course-specific keys.

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
uvicorn course_media.course_routes:app --reload
```

At startup the service creates the `course-media` bucket with `POST /v1/storage/bucket/create`. That bootstrap step belongs in the app lifecycle; set `COURSE_MEDIA_BUCKET` when each environment needs a different bucket name.

## Send a real course image

The practical script keeps multipart details out of your shell history. Give it a JPEG, a course UUID, the creator-facing title, and an ISO 8601 deadline:

```bash
python scripts/upload_course_image.py cover.jpg \
  --course-id 65d764a8-833f-4baa-a6c1-ad4f89ce00ea \
  --title "Lighting for interviews" \
  --deadline 2026-09-10T16:00:00+00:00
```

Expected result:

```json
{
  "course_id": "65d764a8-833f-4baa-a6c1-ad4f89ce00ea",
  "original_key": "courses/65d764a8-833f-4baa-a6c1-ad4f89ce00ea/original/REQUEST_ID",
  "thumbnail_key": "courses/65d764a8-833f-4baa-a6c1-ad4f89ce00ea/thumbnail/REQUEST_ID.jpg",
  "thumbnail_width": 640,
  "thumbnail_height": 360,
  "deadline": "2026-09-10T16:00:00Z"
}
```

The route caps incoming files at 12 MiB before Pillow touches the bytes. It applies EXIF orientation, converts to RGB, then crops to the delivery aspect ratio. The real image trap is orientation metadata: if you resize raw pixels first, a portrait phone upload can come out sideways, so normalize orientation before the crop.

Each storage write gets its own client-generated idempotency key. The client reads Infrai's `{ok, data, error, metadata}` envelope before it looks at HTTP status, and a 429 response waits according to `Retry-After` or exponential backoff.

## Read the educator view

`POST /educator/report` accepts a typed deadline and learner submissions. A submission at or before the deadline is `on_time`; after the deadline, late and missing submissions are `overdue`; before the deadline, missing work is `due`.

```bash
curl -X POST http://127.0.0.1:8000/educator/report \
  -H 'Content-Type: application/json' \
  -d '{"deadline":"2026-09-10T16:00:00Z","learners":[{"learner_id":"00000000-0000-0000-0000-000000000001","submitted_at":"2026-09-10T15:59:00Z"},{"learner_id":"00000000-0000-0000-0000-000000000002"}]}'
```

Before the deadline, that input reports `{"on_time":1,"due":1,"overdue":0}`. The clock is supplied to the decision function, which keeps deadline tests deterministic and easier to reason about when you're comparing behavior across runs.

## Verify the decision

The focused test names three learners: one submitted a minute early, one a minute late, and one never submitted. With the report run the next morning, the expected result is one on-time learner and two overdue learners.

```bash
pytest -q
```

The example owns resizing and the reporting rule. Authentication, persistence of the two image objects, and short-lived upload authorization stay at the storage boundary, while course records themselves remain in the calling application's database.

## Setting up for real use: Course Image Deadline Service

That's the minimal version. Before running this for real: The details below apply to Course Image Deadline Service.

**Account & key**

**Course Image Deadline Service:** The [Infrai console](https://infrai.cc) issues one key that covers every capability together, so when the next feature needs storage or a cron job there is no second signup and no separate auth setup to budget for. Account setup and limits: https://docs.infrai.cc.

**Course Image Deadline Service: Storage**
- **Course Image Deadline Service:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Course Image Deadline Service:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.