from __future__ import annotations

import argparse
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload course artwork to the local service")
    parser.add_argument("image", type=Path)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--deadline", required=True, help="ISO 8601 timestamp")
    parser.add_argument("--service", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    with args.image.open("rb") as image_file:
        response = httpx.request(
            method="POST",
            url=f"{args.service}/courses/image",
            data={"course_id": args.course_id, "title": args.title, "deadline": args.deadline},
            files={"image": (args.image.name, image_file, "image/jpeg")},
            timeout=60.0,
        )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
