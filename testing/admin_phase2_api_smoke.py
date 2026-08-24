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
    module_a = client.post(
        "/api/admin/modules",
        json={"module_code": f"PH2-DMV-{suffix}", "name": "Data Modelling and Visualisation"},
    ).json()["module"]
    module_b = client.post(
        "/api/admin/modules",
        json={"module_code": f"PH2-PROG-{suffix}", "name": "Programming Fundamentals"},
    ).json()["module"]
    version_a = client.post(
        f"/api/admin/modules/{module_a['id']}/versions",
        json={"version": "v1", "level": "Basic"},
    ).json()["version"]
    version_b = client.post(
        f"/api/admin/modules/{module_b['id']}/versions",
        json={"version": "v1", "level": "Foundation"},
    ).json()["version"]

    upload_a = _upload_pdf(
        client,
        version_a["id"],
        "dmv-brief.pdf",
        "project_brief",
        "OFFICIAL_REQUIREMENT",
        "DMV Brief\nTask 1: Prepare Data\nYou are required to:\nLoad data.\nClean data.",
    )
    upload_b = _upload_pdf(
        client,
        version_b["id"],
        "programming-iu1.pdf",
        "instructional_unit",
        "LEARNING_MATERIAL",
        "Programming IU1\nVariables\nA variable stores a value.\nFunctions\nA function groups reusable logic.",
        instructional_unit="IU1",
    )
    print("upload_a", upload_a.status_code)
    print("upload_b", upload_b.status_code)
    prepare_a = client.post(f"/api/admin/versions/{version_a['id']}/prepare", params={"created_by": "smoke"})
    prepare_b = client.post(f"/api/admin/versions/{version_b['id']}/prepare", params={"created_by": "smoke"})
    print("prepare_a", prepare_a.status_code, prepare_a.json()["job"]["status"], prepare_a.json()["job"]["chunk_count"])
    print("prepare_b", prepare_b.status_code, prepare_b.json()["job"]["status"], prepare_b.json()["job"]["chunk_count"])
    job_a = prepare_a.json()["job"]
    chunks_a = client.get(f"/api/admin/preparation-jobs/{job_a['id']}/chunks")
    warnings_a = client.get(f"/api/admin/preparation-jobs/{job_a['id']}/warnings")
    print("chunks_a", chunks_a.status_code, len(chunks_a.json()["chunks"]))
    print("warnings_a", warnings_a.status_code, len(warnings_a.json()["warnings"]))


def _upload_pdf(
    client: TestClient,
    version_id: str,
    filename: str,
    document_type: str,
    knowledge_role: str,
    text: str,
    instructional_unit: str | None = None,
):
    data = {
        "document_type": document_type,
        "knowledge_role": knowledge_role,
        "uploaded_by": "smoke",
    }
    if instructional_unit:
        data["instructional_unit"] = instructional_unit
    return client.post(
        f"/api/admin/versions/{version_id}/documents/upload",
        data=data,
        files={"file": (filename, _pdf_bytes(text), "application/pdf")},
    )


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    main()

