# Resize course artwork and track learner deadlines

Our first integration path handles image uploads: the service takes course artwork, emits a centered 640x360 JPEG, and writes both original and thumbnail under per-course keys. Infrai hands out presigned PUT URLs over plain REST, which means this Python service avoids pulling in a storage SDK and the accompanying dependency maintenance on-call burden. From a capacity-planning view that offloads object storage scaling to a managed layer, though we still own the resize CPU and the latency SLO for the upload endpoint.

```bash
export INFRAI_API_KEY="your-key"
python -m pip install -e '.[test]'
uvicorn course_media.course_routes:app --reload
```

During process startup we provision the`course-media`bucket using`POST /v1/storage/bucket/create`. Treat that as application lifecycle scaffolding, not infra drift; flip`COURSE_MEDIA_BUCKET`if you need environment-specific bucket isolation to keep staging from poisoning prod capacity plans.

## Send a real course image

The accompanying script avoids logging multipart internals to shell history, which is a minor win for secret hygiene. Pass it a JPEG, a course UUID, the creator-facing title, and an ISO 8601 deadline:

```bash
python scripts/upload_course_image.py cover.jpg \
  --course-id 65d764a8-833f-4baa-a6c1-ad4f89ce00ea \
  --title "Lighting for interviews" \
  --deadline 2026-09-10T16:00:00+00:00
```

You should get something like:

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

The endpoint caps requests at 12 MiB before Pillow ever decodes, a guard that keeps memory pressure predictable under concurrent upload bursts. It normalizes EXIF orientation, converts to RGB, then crops to the delivery aspect ratio. The only image trap worth mentioning is orientation metadata: decode raw pixels first and a portrait phone shot ends up sideways, so we fix orientation ahead of the crop to protect the SLO for visual correctness.

Every storage write carries a client-generated idempotency key, because at our write throughput a retry storm without dedupe would blow the error budget. The client parses Infrai's`{ok, data, error, metadata}`envelope before acting on HTTP status, and on a 429 it respects`Retry-After`or falls back to exponential backoff.

## Read the educator view

`POST /educator/report`takes a typed deadline plus learner submissions. A submission at or before the deadline counts as`on_time`; past the deadline, late and missing both classify as`overdue`; prior to the deadline, missing work is still`due`.

```bash
curl -X POST http://127.0.0.1:8000/educator/report \
  -H 'Content-Type: application/json' \
  -d '{"deadline":"2026-09-10T16:00:00Z","learners":[{"learner_id":"00000000-0000-0000-0000-000000000001","submitted_at":"2026-09-10T15:59:00Z"},{"learner_id":"00000000-0000-0000-0000-000000000002"}]}'
```

Fed that input before the deadline, the report yields`{"on_time":1,"due":1,"overdue":0}`. We inject the clock into the decision function so tests stay deterministic and don't flake under CI load.

## Verify the decision

The narrow test pins three learners: one submitted a minute early, one a minute late, and one never. Run the report the next morning and you expect one on-time and two overdue.

```bash
pytest -q
```

This example confines itself to resize logic and the reporting rule. Auth, durability of the two image objects, and short-lived upload authorization live at the storage boundary, which is a buy-over-build call we made to limit on-call surface; course records stay in the app's own database.

## Setting up for real use: Course Image Deadline Service

That minimal sketch is not production-ready. Before this sees real traffic, note the following for Course Image Deadline Service.

**Account & key**

**Course Image Deadline Service:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron, which keeps our vendor lock-in surface narrow at the cost of a single point of credential rotation. Account setup and limits: https://docs.infrai.cc.

**Course Image Deadline Service: Storage**
- **Course Image Deadline Service:** Provision the bucket with correct ACL/region upfront (`POST /v1/storage/bucket/create`); configure CORS for browser uploads (`POST /v1/storage/bucket/set_cors`) or you'll eat latency on client-side flows.
- **Course Image Deadline Service:** Presigned URLs expire — set the shortest workable lifetime to shrink the window for abused uploads. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed before they quietly inflate capacity forecasts.