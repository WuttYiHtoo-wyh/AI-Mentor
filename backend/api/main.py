from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.constants import (
    DOCUMENT_STATUSES,
    KNOWLEDGE_ROLE_CODES,
    MAX_UPLOAD_BYTES,
    MODULE_STATUSES,
    MODULE_VERSION_STATUSES,
    PUBLISH_JOB_STATUSES,
    PREPARATION_JOB_STATUSES,
    SUPPORTED_PREPARATION_EXTENSIONS,
    SUPPORTED_UPLOAD_EXTENSIONS,
)
from backend.admin.preparation_service import AdminPreparationService
from backend.admin.publish_service import AdminPublishService
from backend.admin.repository import DuplicateRecordError, NotFoundError, RepositoryError
from backend.admin.review_service import AdminReviewService
from backend.admin.service import AdminPersistenceService, ValidationError, to_dict
from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.admin.upload_service import AdminUploadService
from backend.mentor_response.chat_service import (
    answer_chat_turn,
    get_default_module,
    load_chat_module_config,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = WORKSPACE_ROOT / "configs" / "chat_modules.yaml"
STATIC_DIR = WORKSPACE_ROOT / "frontend" / "learner_chat"
TESTING_DIR = WORKSPACE_ROOT / "testing"
FINAL_DEMO_SUMMARY_PATH = TESTING_DIR / "mentor_final_v3_demo_summary.json"
FINAL_RESULTS_PATH = TESTING_DIR / "mentor_final_v3_results.json"
FINAL_DEBUG_PATH = TESTING_DIR / "mentor_final_v3_retrieval_debug.json"
FINAL_SHORTLIST_PATH = TESTING_DIR / "mentor_final_v3_manual_review_shortlist.json"
HUMAN_REVIEW_PATH = TESTING_DIR / "human_review_results.json"
ADMIN_DB_PATH = WORKSPACE_ROOT / "data" / "ai_mentor.db"
ADMIN_UPLOAD_ROOT = WORKSPACE_ROOT / "data" / "uploads"
ADMIN_PREPARED_ROOT = WORKSPACE_ROOT / "data" / "prepared"


class ChatHistoryTurn(BaseModel):
    role: Literal["learner", "mentor"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    module_id: str | None = None
    level: str | None = None
    conversation_id: str | None = None
    history: list[ChatHistoryTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    module_id: str
    level: str
    module_name: str
    answer: str
    sources: list[str]
    no_context: bool


class HumanReviewRecord(BaseModel):
    test_id: str = Field(min_length=1, max_length=80)
    checklist: dict[str, bool] = Field(default_factory=dict)
    human_status: Literal["Not Reviewed", "Approved", "Needs Improvement"] = "Not Reviewed"
    reviewer: str = Field(default="", max_length=200)
    reviewed_at: str = Field(default="", max_length=80)
    comments: str = Field(default="", max_length=4000)


class AdminModuleCreateRequest(BaseModel):
    module_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    status: str = Field(default="DRAFT", max_length=40)


class AdminModuleVersionCreateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    level: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=4000)
    status: str = Field(default="DRAFT", max_length=40)


class AdminDocumentMetadataCreateRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=300)
    stored_filename: str = Field(min_length=1, max_length=300)
    file_path: str = Field(min_length=1, max_length=1000)
    file_type: str = Field(min_length=1, max_length=40)
    document_type: str = Field(min_length=1, max_length=120)
    knowledge_role: str = Field(min_length=1, max_length=80)
    instructional_unit: str | None = Field(default=None, max_length=120)
    version: str = Field(default="v1", max_length=80)
    status: str = Field(default="UPLOADED", max_length=40)
    uploaded_by: str = Field(default="local-demo", max_length=200)


class AdminReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=4000)
    allow_blocking: bool = False


class AdminChunkMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated_by: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=4000)
    section_title: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=500)
    task_reference: str | None = Field(default=None, max_length=200)
    instructional_unit: str | None = Field(default=None, max_length=200)
    knowledge_role: str | None = Field(default=None, max_length=80)


class AdminBulkReviewRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=4000)
    chunk_ids: list[str] = Field(default_factory=list)
    document_id: str | None = None
    allow_blocking: bool = False


class AdminVersionApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=4000)


class AdminReopenVersionRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=4000)


class AdminDocumentExcludeRequest(BaseModel):
    excluded_by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)


class AdminPublishRequest(BaseModel):
    requested_by: str = Field(default="local-demo", max_length=200)


app = FastAPI(title="AI Mentor Learner Chat", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/admin/metadata")
def admin_metadata() -> dict[str, Any]:
    return {
        "knowledge_roles": sorted(KNOWLEDGE_ROLE_CODES),
        "statuses": {
            "module": sorted(MODULE_STATUSES),
            "module_version": sorted(MODULE_VERSION_STATUSES),
            "document": sorted(DOCUMENT_STATUSES),
            "preparation_job": sorted(PREPARATION_JOB_STATUSES),
            "publish_job": sorted(PUBLISH_JOB_STATUSES),
        },
        "database": str(ADMIN_DB_PATH.relative_to(WORKSPACE_ROOT)),
        "uploads": {
            "root": str(ADMIN_UPLOAD_ROOT.relative_to(WORKSPACE_ROOT)),
            "max_bytes": MAX_UPLOAD_BYTES,
            "allowed_extensions": sorted(SUPPORTED_UPLOAD_EXTENSIONS),
            "preparation_supported_extensions": sorted(SUPPORTED_PREPARATION_EXTENSIONS),
        },
    }


@app.post("/api/admin/modules")
def create_admin_module(request: AdminModuleCreateRequest) -> dict[str, Any]:
    service = _admin_service()
    try:
        module = service.create_module(
            module_code=request.module_code,
            name=request.name,
            description=request.description,
            status=request.status,
        )
    except DuplicateRecordError as exc:
        raise HTTPException(status_code=409, detail="Module code already exists.") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"module": to_dict(module)}


@app.get("/api/admin/modules")
def list_admin_modules() -> dict[str, Any]:
    service = _admin_service()
    return {"modules": [to_dict(module) for module in service.list_modules()]}


@app.get("/api/admin/modules/{module_id}")
def get_admin_module(module_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        return {"module": to_dict(service.get_module(module_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/modules/{module_id}/versions")
def create_admin_module_version(module_id: str, request: AdminModuleVersionCreateRequest) -> dict[str, Any]:
    service = _admin_service()
    try:
        version = service.create_module_version(
            module_id=module_id,
            version=request.version,
            level=request.level,
            description=request.description,
            status=request.status,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRecordError as exc:
        raise HTTPException(status_code=409, detail="Version already exists for this module and level.") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"version": to_dict(version)}


@app.get("/api/admin/modules/{module_id}/versions")
def list_admin_module_versions(module_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        versions = service.list_module_versions(module_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"versions": [to_dict(version) for version in versions]}


@app.get("/api/admin/versions/{version_id}")
def get_admin_module_version(version_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        return {"version": to_dict(service.get_module_version(version_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/versions/{version_id}/documents")
def create_admin_document_metadata(version_id: str, request: AdminDocumentMetadataCreateRequest) -> dict[str, Any]:
    service = _admin_service()
    try:
        document = service.create_document_metadata(
            module_version_id=version_id,
            original_filename=request.original_filename,
            stored_filename=request.stored_filename,
            file_path=request.file_path,
            file_type=request.file_type,
            document_type=request.document_type,
            knowledge_role=request.knowledge_role,
            instructional_unit=request.instructional_unit,
            version=request.version,
            status=request.status,
            uploaded_by=request.uploaded_by,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RepositoryError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document": to_dict(document)}


@app.get("/api/admin/versions/{version_id}/documents")
def list_admin_document_metadata(version_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        documents = service.list_documents_for_version(version_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"documents": [to_dict(document) for document in documents]}


@app.get("/api/admin/documents/{document_id}")
def get_admin_document_metadata(document_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        return {"document": to_dict(service.get_document(document_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/versions/{version_id}/documents/upload")
async def upload_admin_document(
    version_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    knowledge_role: str = Form(...),
    instructional_unit: str | None = Form(default=None),
    document_version: str = Form(default="v1"),
    uploaded_by: str = Form(default="local-demo"),
) -> dict[str, Any]:
    service = _admin_upload_service()
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        document = service.save_document_upload(
            version_id=version_id,
            original_filename=file.filename or "",
            content=content,
            document_type=document_type,
            knowledge_role=knowledge_role,
            instructional_unit=instructional_unit,
            document_version=document_version,
            uploaded_by=uploaded_by,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document": to_dict(document)}


@app.post("/api/admin/versions/{version_id}/prepare")
def prepare_admin_version(version_id: str, created_by: str = "local-demo") -> dict[str, Any]:
    service = _admin_preparation_service()
    try:
        job = service.prepare_version(version_id=version_id, created_by=created_by)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": to_dict(job)}


@app.get("/api/admin/versions/{version_id}/preparation-jobs")
def list_admin_preparation_jobs(version_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        jobs = service.list_preparation_jobs(version_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"jobs": [to_dict(job) for job in jobs]}


@app.get("/api/admin/preparation-jobs/{job_id}")
def get_admin_preparation_job(job_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        return {"job": to_dict(service.get_preparation_job(job_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/admin/preparation-jobs/{job_id}/chunks")
def list_admin_prepared_chunks(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    document_id: str | None = None,
    status: str | None = None,
    knowledge_role: str | None = None,
    embedding_eligible: bool | None = None,
) -> dict[str, Any]:
    service = _admin_service()
    try:
        chunks = service.list_prepared_chunks(
            job_id,
            limit=limit,
            offset=offset,
            document_id=document_id,
            status=status,
            knowledge_role=knowledge_role,
            embedding_eligible=embedding_eligible,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"chunks": [to_dict(chunk) for chunk in chunks], "limit": limit, "offset": offset}


@app.get("/api/admin/preparation-jobs/{job_id}/warnings")
def list_admin_preparation_warnings(job_id: str) -> dict[str, Any]:
    service = _admin_service()
    try:
        warnings = service.list_preparation_warnings(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"warnings": [to_dict(warning) for warning in warnings]}


@app.get("/api/admin/chunks/{chunk_id}")
def get_admin_chunk(chunk_id: str) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        return {"chunk": to_dict(service.get_chunk(chunk_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/chunks/{chunk_id}/approve")
def approve_admin_chunk(chunk_id: str, request: AdminReviewRequest) -> dict[str, Any]:
    return _set_admin_chunk_status(chunk_id, "APPROVED", request)


@app.post("/api/admin/chunks/{chunk_id}/reject")
def reject_admin_chunk(chunk_id: str, request: AdminReviewRequest) -> dict[str, Any]:
    return _set_admin_chunk_status(chunk_id, "REJECTED", request)


@app.post("/api/admin/chunks/{chunk_id}/needs-review")
def reset_admin_chunk(chunk_id: str, request: AdminReviewRequest) -> dict[str, Any]:
    return _set_admin_chunk_status(chunk_id, "NEEDS_REVIEW", request)


@app.patch("/api/admin/chunks/{chunk_id}/metadata")
def update_admin_chunk_metadata(chunk_id: str, request: AdminChunkMetadataUpdateRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        chunk = service.update_chunk_metadata(
            chunk_id,
            updated_by=request.updated_by,
            comment=request.comment,
            section_title=request.section_title,
            topic=request.topic,
            task_reference=request.task_reference,
            instructional_unit=request.instructional_unit,
            knowledge_role=request.knowledge_role,
        )
        return {"chunk": to_dict(chunk)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/chunks/bulk-review")
def bulk_review_admin_chunks(request: AdminBulkReviewRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        if request.document_id and not request.chunk_ids and request.action.lower().replace("_", "-") == "approve":
            return service.approve_document_eligible_chunks(
                document_id=request.document_id,
                reviewer=request.reviewer,
                comment=request.comment,
            )
        return service.bulk_review_chunks(
            chunk_ids=request.chunk_ids,
            action=request.action,
            reviewer=request.reviewer,
            comment=request.comment,
            allow_blocking=request.allow_blocking,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/documents/{document_id}/review-summary")
def get_admin_document_review_summary(document_id: str) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        return {"summary": service.document_review_summary(document_id)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/documents/{document_id}/exclude")
def exclude_admin_document(document_id: str, request: AdminDocumentExcludeRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        document = service.exclude_document(document_id=document_id, excluded_by=request.excluded_by, reason=request.reason)
        return {"document": to_dict(document)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/versions/{version_id}/review-summary")
def get_admin_version_review_summary(version_id: str) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        return {"summary": service.version_review_summary(version_id)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/admin/versions/{version_id}/approve")
def approve_admin_version(version_id: str, request: AdminVersionApprovalRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        version = service.approve_version(version_id=version_id, approved_by=request.approved_by, comment=request.comment)
        return {"version": to_dict(version)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/versions/{version_id}/reopen")
def reopen_admin_version(version_id: str, request: AdminReopenVersionRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        version = service.reopen_version(version_id=version_id, actor=request.actor, comment=request.comment)
        return {"version": to_dict(version)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/review-events")
def list_admin_review_events(entity_type: str | None = None, entity_id: str | None = None) -> dict[str, Any]:
    service = _admin_review_service()
    return {"events": [to_dict(event) for event in service.list_review_events(entity_type, entity_id)]}


@app.post("/api/admin/versions/{version_id}/publish")
def publish_admin_version(version_id: str, request: AdminPublishRequest) -> dict[str, Any]:
    service = _admin_publish_service()
    try:
        job = service.publish_version(version_id=version_id, requested_by=request.requested_by)
        return {"job": to_dict(job)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/versions/{version_id}/publish-jobs")
def list_admin_publish_jobs(version_id: str) -> dict[str, Any]:
    service = _admin_publish_service()
    try:
        jobs = service.list_publish_jobs(version_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"jobs": [to_dict(job) for job in jobs]}


@app.get("/api/admin/publish-jobs/{job_id}")
def get_admin_publish_job(job_id: str) -> dict[str, Any]:
    service = _admin_publish_service()
    try:
        return {"job": to_dict(service.get_publish_job(job_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/admin/modules/{module_id}/active-version")
def get_admin_active_version(module_id: str, level: str) -> dict[str, Any]:
    service = _admin_publish_service()
    try:
        return {"version": to_dict(service.active_version(module_id, level))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    default_module_id, default_level = get_default_module(REGISTRY_PATH)
    module_id = request.module_id or default_module_id
    level = request.level or default_level
    try:
        module_config = load_chat_module_config(module_id, level, REGISTRY_PATH, WORKSPACE_ROOT)
        result = answer_chat_turn(
            message=request.message,
            module_config=module_config,
            workspace_root=WORKSPACE_ROOT,
            history=[turn.model_dump() for turn in request.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The AI Mentor could not answer right now. Please try again.") from exc

    return ChatResponse(
        conversation_id=request.conversation_id or str(uuid4()),
        module_id=result["module_id"],
        level=result["level"],
        module_name=result["module_name"],
        answer=result["answer"],
        sources=result["sources"],
        no_context=result["no_context"],
    )


@app.get("/api/evaluation/summary")
def evaluation_summary() -> dict[str, Any]:
    demo = _read_json(FINAL_DEMO_SUMMARY_PATH, {})
    final = _read_json(FINAL_RESULTS_PATH, {})
    shortlist = _read_json(FINAL_SHORTLIST_PATH, [])
    reviews = _read_reviews()
    return {
        "demo_summary": demo,
        "final_summary": final.get("summary", {}),
        "run_started_at": final.get("run_started_at"),
        "human_review_summary": _human_review_summary(final.get("results", []), reviews),
        "manual_review_shortlist": shortlist,
    }


@app.get("/api/evaluation/tests")
def evaluation_tests() -> dict[str, Any]:
    final = _read_json(FINAL_RESULTS_PATH, {})
    reviews = _read_reviews()
    rows = []
    for row in final.get("results", []):
        test_id = row.get("Test ID", "")
        review = reviews.get(test_id, _default_review(test_id))
        rows.append(
            {
                "test_id": test_id,
                "category": row.get("Category", ""),
                "learner_question": row.get("Learner Question", ""),
                "automated_result": row.get("Automated Result", ""),
                "human_status": review["human_status"],
                "expected_behavior": row.get("Expected Behavior", ""),
                "expected_source": row.get("Expected Primary Source", ""),
                "actual_sources": row.get("Actual Sources", ""),
                "flags": row.get("Flags", []),
                "detected_behavior": row.get("Detected Interaction Behavior", ""),
            }
        )
    return {"tests": rows}


@app.get("/api/evaluation/tests/{test_id}")
def evaluation_test_detail(test_id: str) -> dict[str, Any]:
    final = _read_json(FINAL_RESULTS_PATH, {})
    debug_rows = _read_json(FINAL_DEBUG_PATH, [])
    reviews = _read_reviews()
    row = next((item for item in final.get("results", []) if item.get("Test ID") == test_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Evaluation test not found.")
    debug = next((item for item in debug_rows if item.get("Test ID") == test_id), {})
    return {
        "test": row,
        "debug": {
            "retrieval_query": debug.get("retrieval_query"),
            "detected_behavior": debug.get("detected_behavior"),
            "detected_task_or_topic": debug.get("detected_task_or_topic"),
            "evidence": debug.get("evidence", []),
        },
        "human_review": reviews.get(test_id, _default_review(test_id)),
    }


@app.get("/api/evaluation/human-reviews")
def list_human_reviews() -> dict[str, Any]:
    final = _read_json(FINAL_RESULTS_PATH, {})
    reviews = _read_reviews()
    return {
        "reviews": reviews,
        "summary": _human_review_summary(final.get("results", []), reviews),
    }


@app.get("/api/evaluation/human-reviews/{test_id}")
def get_human_review(test_id: str) -> dict[str, Any]:
    return _read_reviews().get(test_id, _default_review(test_id))


@app.post("/api/evaluation/human-reviews/{test_id}")
def save_human_review(test_id: str, record: HumanReviewRecord) -> dict[str, Any]:
    if record.test_id != test_id:
        raise HTTPException(status_code=400, detail="Path test_id and review test_id must match.")
    reviews = _read_reviews()
    reviews[test_id] = record.model_dump()
    HUMAN_REVIEW_PATH.write_text(json.dumps(reviews, indent=2, ensure_ascii=False), encoding="utf-8")
    final = _read_json(FINAL_RESULTS_PATH, {})
    return {
        "review": reviews[test_id],
        "summary": _human_review_summary(final.get("results", []), reviews),
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _admin_service() -> AdminPersistenceService:
    repository = SQLiteAdminRepository(ADMIN_DB_PATH)
    service = AdminPersistenceService(repository)
    service.initialize()
    return service


def _admin_upload_service() -> AdminUploadService:
    repository = SQLiteAdminRepository(ADMIN_DB_PATH)
    repository.initialize()
    return AdminUploadService(repository, ADMIN_UPLOAD_ROOT)


def _admin_preparation_service() -> AdminPreparationService:
    repository = SQLiteAdminRepository(ADMIN_DB_PATH)
    repository.initialize()
    return AdminPreparationService(repository, WORKSPACE_ROOT, ADMIN_PREPARED_ROOT)


def _admin_review_service() -> AdminReviewService:
    repository = SQLiteAdminRepository(ADMIN_DB_PATH)
    repository.initialize()
    return AdminReviewService(repository)


def _admin_publish_service() -> AdminPublishService:
    repository = SQLiteAdminRepository(ADMIN_DB_PATH)
    repository.initialize()
    return AdminPublishService(
        repository,
        workspace_root=WORKSPACE_ROOT,
        chroma_root=WORKSPACE_ROOT / "data" / "admin_chroma",
        config_root=WORKSPACE_ROOT / "data" / "published_configs",
    )


def _set_admin_chunk_status(chunk_id: str, review_status: str, request: AdminReviewRequest) -> dict[str, Any]:
    service = _admin_review_service()
    try:
        chunk = service.set_chunk_review_status(
            chunk_id,
            review_status=review_status,
            reviewer=request.reviewer,
            comment=request.comment,
            allow_blocking=request.allow_blocking,
        )
        return {"chunk": to_dict(chunk)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _read_reviews() -> dict[str, Any]:
    data = _read_json(HUMAN_REVIEW_PATH, {})
    return data if isinstance(data, dict) else {}


def _default_review(test_id: str) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "checklist": {},
        "human_status": "Not Reviewed",
        "reviewer": "",
        "reviewed_at": "",
        "comments": "",
    }


def _human_review_summary(results: list[dict[str, Any]], reviews: dict[str, Any]) -> dict[str, int]:
    review_cases = [row for row in results if row.get("Automated Result") == "REVIEW"]
    counts = {"Automated REVIEW cases": len(review_cases), "Approved": 0, "Needs Improvement": 0, "Not Reviewed": 0}
    for row in review_cases:
        status = reviews.get(row.get("Test ID", ""), {}).get("human_status", "Not Reviewed")
        if status not in {"Approved", "Needs Improvement"}:
            status = "Not Reviewed"
        counts[status] += 1
    return counts
