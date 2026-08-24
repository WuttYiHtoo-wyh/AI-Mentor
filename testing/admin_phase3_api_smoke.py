from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.main import app


def main() -> None:
    client = TestClient(app)
    suffix = uuid4().hex[:8].upper()
    module = client.post(
        "/api/admin/modules",
        json={"module_code": f"PH3-SMOKE-{suffix}", "name": "Programming Fundamentals"},
    ).json()["module"]
    version = client.post(
        f"/api/admin/modules/{module['id']}/versions",
        json={"version": "v1", "level": "Foundation"},
    ).json()["version"]
    upload = client.post(
        f"/api/admin/versions/{version['id']}/documents/upload",
        data={
            "document_type": "instructional_unit",
            "knowledge_role": "LEARNING_MATERIAL",
            "instructional_unit": "IU1",
            "uploaded_by": "smoke",
        },
        files={"file": ("iu1.pdf", _pdf_bytes(), "application/pdf")},
    )
    print("upload", upload.status_code)
    prepare = client.post(f"/api/admin/versions/{version['id']}/prepare", params={"created_by": "smoke"})
    print("prepare", prepare.status_code, prepare.json()["job"]["status"])
    job = prepare.json()["job"]
    chunks = client.get(f"/api/admin/preparation-jobs/{job['id']}/chunks").json()["chunks"]
    print("chunks", len(chunks))
    for chunk in chunks:
        response = client.post(
            f"/api/admin/chunks/{chunk['id']}/approve",
            json={"reviewer": "smoke", "comment": "Approved for smoke test"},
        )
        print("approve_chunk", response.status_code)
    summary = client.get(f"/api/admin/versions/{version['id']}/review-summary")
    print("summary", summary.status_code, summary.json()["summary"]["eligible_for_approval"])
    approval = client.post(
        f"/api/admin/versions/{version['id']}/approve",
        json={"approved_by": "smoke", "comment": "Ready for Phase 4 smoke"},
    )
    print("approve_version", approval.status_code, approval.json().get("version", {}).get("status"))
    events = client.get("/api/admin/review-events", params={"entity_type": "module_version", "entity_id": version["id"]})
    print("events", events.status_code, len(events.json()["events"]))


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Programming Fundamentals\n"
        "Variables\n"
        "A variable stores a value in a program. This document contains enough words to create a complete chunk for review. "
        "The chunk can be approved without any module-specific parsing or retrieval behavior.",
        fontsize=11,
    )
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    main()

