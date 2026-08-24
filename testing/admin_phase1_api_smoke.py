from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.api.main import app


def main() -> None:
    client = TestClient(app)
    suffix = uuid4().hex[:8].upper()
    module_a = client.post(
        "/api/admin/modules",
        json={
            "module_code": f"SMOKE-DMV-{suffix}",
            "name": "Data Modelling and Visualisation",
            "description": "Phase 1 smoke module A",
        },
    )
    module_b = client.post(
        "/api/admin/modules",
        json={
            "module_code": f"SMOKE-PROG-{suffix}",
            "name": "Programming Fundamentals",
            "description": "Phase 1 smoke module B",
        },
    )
    print("module_a", module_a.status_code)
    print("module_b", module_b.status_code)
    dmv = module_a.json()["module"]
    programming = module_b.json()["module"]

    version_a = client.post(
        f"/api/admin/modules/{dmv['id']}/versions",
        json={"version": "v1", "level": "Basic", "description": "Smoke Basic"},
    )
    version_b = client.post(
        f"/api/admin/modules/{programming['id']}/versions",
        json={"version": "v1", "level": "Foundation", "description": "Smoke Foundation"},
    )
    print("version_a", version_a.status_code)
    print("version_b", version_b.status_code)

    ver_a = version_a.json()["version"]
    ver_b = version_b.json()["version"]
    doc_a = client.post(
        f"/api/admin/versions/{ver_a['id']}/documents",
        json={
            "original_filename": "DMV Brief.pdf",
            "stored_filename": "dmv-brief.pdf",
            "file_path": "storage/uploads/smoke-dmv/v1/brief.pdf",
            "file_type": "pdf",
            "document_type": "project_brief",
            "knowledge_role": "OFFICIAL_REQUIREMENT",
            "uploaded_by": "smoke",
        },
    )
    doc_b = client.post(
        f"/api/admin/versions/{ver_b['id']}/documents",
        json={
            "original_filename": "Programming IU1.pdf",
            "stored_filename": "programming-iu1.pdf",
            "file_path": "storage/uploads/smoke-prog/v1/iu1.pdf",
            "file_type": "pdf",
            "document_type": "instructional_unit",
            "knowledge_role": "LEARNING_MATERIAL",
            "instructional_unit": "IU1",
            "uploaded_by": "smoke",
        },
    )
    print("doc_a", doc_a.status_code)
    print("doc_b", doc_b.status_code)
    print("docs_a", len(client.get(f"/api/admin/versions/{ver_a['id']}/documents").json()["documents"]))
    print("docs_b", len(client.get(f"/api/admin/versions/{ver_b['id']}/documents").json()["documents"]))


if __name__ == "__main__":
    main()
