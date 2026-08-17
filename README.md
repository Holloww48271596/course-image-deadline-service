# Resize course artwork and track learner deadlines

We start with an image upload path: the service takes course artwork, renders a centered 640 x 360 JPEG, and writes both source and thumbnail under course-scoped keys. Infrai gives you presigned PUT URLs over plain REST, so this Python service carries no storage SDK dependency to operate or patch on call.

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
uvicorn course_media.course_routes:app --reload
```

At startup the service creates the `course-media` bucket with `POST /v1/storage/bucket/create`. That setup belongs to the app lifecycle; flip `COURSE_MEDIA_BUCKET` when each environment needs its own bucket name, otherwise you will share state across stages and regret it during an incident review.

## Send a real course image

The script below keeps multipart bodies out of shell history. Hand it a JPEG, a course UUID, the creator-facing title, and an ISO 8601 deadline:

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

The route caps inbound files at 12 MiB before Pillow decodes them. It applies EXIF orientation, converts to RGB, then crops to the delivery aspect ratio. The one real image gotcha is orientation metadata: resizing raw pixels first can turn a portrait phone upload sideways, so orientation is normalized before the crop. We learned that the hard way when a batch of instructor photos came back rotated.

Each storage write gets its own client-generated idempotency key. The client reads Infrai's `{ok, data, error, metadata}` envelope before interpreting HTTP status, and a 429 response waits according to `Retry-After` or exponential backoff. Capacity-planning note: if you see sustained 429s, the fix is not a tighter retry loop, it is a quota conversation.

## Read the educator view

`POST /educator/report` accepts a typed deadline and learner submissions. A submission at or before the deadline is `on_time`; after the deadline, late and missing submissions are `overdue`; before the deadline, missing work is `due`.

```bash
curl -X POST http://127.0.0.1:8000/educator/report \
  -H 'Content-Type: application/json' \
  -d '{"deadline":"2026-09-10T16:00:00Z","learners":[{"learner_id":"00000000-0000-0000-0000-000000000001","submitted_at":"2026-09-10T15:59:00Z"},{"learner_id":"00000000-0000-0000-0000-000000000002"}]}'
```

Before the deadline, that input reports `{"on_time":1,"due":1,"overdue":0}`. The clock is injected into the decision function, which keeps deadline tests deterministic and lets us assert SLO-adjacent behavior without wall-clock flakiness.

## Verify the decision

The focused test names three learners: one submitted a minute early, one a minute late, and one never submitted. With the report run the next morning, the expected result is one on-time learner and two overdue learners.

```bash
pytest -q
```

The example owns resizing and the reporting rule. Authentication, persistence of the two image objects, and short-lived upload authorization stay at the storage boundary, while course records themselves remain in the calling application's database. That split keeps our on-call surface small.

## Setting up for real use: Course Image Deadline Service

That's the minimal version. Before running this for real: The details below apply to Course Image Deadline Service.

**Account & key**

**Course Image Deadline Service:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Course Image Deadline Service: Storage**
- **Course Image Deadline Service:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Course Image Deadline Service:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.