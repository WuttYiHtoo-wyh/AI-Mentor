# Lecturer/Admin V1 Design

This document defines a reusable Lecturer/Admin workflow for onboarding modules into the AI Mentor platform. It is design-only. Learner V1 remains frozen for the manager demo.

The goal is that a future module can be onboarded mainly by creating module configuration, uploading documents, assigning document roles, preparing and validating knowledge, lecturer review, approval, and publish. The existing generic Python preparation and retrieval components should remain the core implementation; Admin V1 must not create a second ingestion pipeline.

## Existing Component Reuse Map

| Area | Current component | Reuse for Admin V1 | Current limitation |
|---|---|---|---|
| Module/source registry | `configs/modules/dmv_basic.yaml` | Becomes the generated module/source configuration for preparation jobs. | Local YAML file; one DMV Basic module; edited manually. |
| Knowledge roles | `OFFICIAL_REQUIREMENT`, `LEARNING_MATERIAL`, `MODULE_GUIDANCE` in preparation config/models | Same roles exposed in Admin upload/review UI. | Allowed role list is code-backed; future role extension would currently need a code change. |
| Preparation pipeline | `backend/knowledge_preparation/pipeline.py` | Admin API should call this through a service wrapper. | CLI/config-path oriented; writes output files directly. |
| Extraction | `backend/knowledge_preparation/extractor.py` | Reuse for PDFs and extend generically for DOCX/PPTX/XLSX. | Current tested path is PDF-oriented. |
| Structure/chunking | `structure.py`, `chunker.py`, `rubric.py` | Reuse generic section-aware chunking and rubric reconstruction. | Rubric reconstruction is generic enough to reuse but should be monitored for non-DMV formats. |
| Validation/reporting | `validator.py`, `eligibility.py`, `writer.py` | Use validation report as Admin preparation result. | Review decisions are not persisted per chunk yet. |
| Prepared outputs | `prepared_knowledge/dmv_basic/prepared_chunks.jsonl`, `validation_report.json` | Admin stores per-module-version prepared artifacts. | Local artifact paths are manually chosen. |
| Embeddings/vector store | `backend/retrieval_experiment/pipeline.py`, `vector_store.py`, `embeddings.py` | Publish step should call embedding/vector-store update for approved chunks. | Current baseline pipeline resets a collection; Admin publish needs version-safe update semantics. |
| Retrieval config | `configs/retrieval_experiment3.yaml` | Admin publish should generate/activate retrieval config for a module version. | Local YAML; DMV collection/path names are manually set. |
| Learner chat registry | `configs/chat_modules.yaml` | Publish should add or update active published module entries. | Local YAML; not backed by a module database. |
| API structure | `backend/api/main.py` | Add `/api/admin/*` endpoints alongside existing `/api/chat` and `/api/evaluation/*`. | Current API is lightweight and file-backed. |
| Learner UI/Evaluation/Capabilities | `frontend/learner_chat/*` | Do not change for Admin V1 design; Admin UI should be separate or gated. | No Admin/Lecturer UI exists. |

## What Is Too Local or DMV-Specific Today

- `configs/modules/dmv_basic.yaml` is reusable in shape but manually names DMV Basic files and output paths.
- `configs/retrieval_experiment3.yaml` contains one prepared chunk path, Chroma collection, module ID, and level.
- `configs/chat_modules.yaml` contains one active learner module.
- `prepared_knowledge/dmv_basic` and `vectorstores/baseline_chroma` are local artifact paths, not managed records.
- Current preparation supports the V1 DMV source set well, but upload-type support for DOCX/PPTX/XLSX is not designed as an Admin-facing service yet.
- Publish currently has no lifecycle gate. Learner retrieval can use whatever config points to; Admin V1 must ensure only `PUBLISHED` active versions are exposed.

No DMV topic map or module-specific Python parser should be added for future modules.

## Lecturer/Admin Workflow

```text
Lecturer
->
Create Module
->
Enter Module Information
->
Upload Documents
->
Assign Knowledge Roles
->
Prepare Knowledge
->
Review Preparation Results
->
Review / Approve Knowledge
->
Publish
->
Embeddings + Vector Store
->
Module available to Learner AI Mentor
```

### 1. Create Module

Lecturer creates a module shell before upload.

Recommended fields:

- `module_id`: stable unique ID. V1 should system-generate a slug from name/level, with optional admin override before first publish. Example: `programming-fundamentals-basic`.
- `module_name`: display name.
- `level`: Basic, Advanced, or other institution-approved label.
- `version`: initial draft version, for example `v1`.
- `description`: short lecturer-facing description.
- `status`: starts as `DRAFT`.
- `created_by`, `created_at`, `updated_at`.

System-generated IDs reduce collisions and avoid inconsistent naming. Manual override is useful for institutional codes, but only before publishing.

### 2. Upload Documents

Lecturer uploads supported source files:

- PDF
- DOCX
- PPTX
- XLSX

V1 should validate extension, MIME type where available, file size, and path safety before storing.

Document metadata:

- `document_id`: system-generated stable ID.
- `module_id`
- `module_version`
- `filename_original`
- `storage_path`
- `document_type`
- `knowledge_role`
- `level`
- `instructional_unit` when applicable
- `upload_date`
- `uploaded_by`
- `version`
- `status`
- `checksum_sha256`

Files should be stored under a controlled upload root, for example:

```text
storage/uploads/{module_id}/{module_version}/{document_id}/{safe_filename}
```

Never use the user-supplied filename as an executable path. Store it as display metadata only.

### 3. Assign Knowledge Roles

Lecturer assigns one of the current generic roles:

- `OFFICIAL_REQUIREMENT`: authoritative for assessment tasks, deliverables, rubric, marks, and what learners must do.
- `LEARNING_MATERIAL`: authoritative for taught concepts and explanations.
- `MODULE_GUIDANCE`: authoritative for general module/course guidance.

Role assignment should be explicit before preparation. The UI should show short explanations and examples, but not module-specific rules.

Future role extensibility should be config/data driven:

```text
knowledge_roles
- code
- label
- description
- authority_priority
- enabled
```

V1 may keep the three roles fixed, but the data model should not assume roles are permanently hard-coded.

### 4. Prepare Knowledge

Admin layer calls the existing reusable engine:

```text
uploaded documents + module/source metadata
->
generated module config
->
backend.knowledge_preparation.prepare_module(...)
->
prepared_chunks.jsonl
->
validation_report.json
```

Needed service wrapper:

```python
prepare_module_job(module_id, version, requested_by) -> preparation_job_id
```

The wrapper should:

- load module/document metadata from storage;
- generate a temporary or persisted module config in the same shape as `configs/modules/dmv_basic.yaml`;
- call the existing preparation pipeline;
- store job status and artifact paths;
- import chunk summaries into the Admin review store;
- preserve full artifacts for audit.

### 5. Review Preparation Results

Lecturer sees a preparation summary such as:

```text
Documents processed: 8
Chunks created: 164
Ready: 151
Needs Review: 13
Warnings: 8
```

Lecturer should be able to inspect:

- source document;
- section/topic;
- chunk content;
- metadata;
- page/source;
- warning;
- status;
- embedding eligibility.

Do not expose embeddings, vector values, Chroma internals, reranking scores, or token-size details by default.

### 6. Review / Approve Knowledge

V1 recommendation: document-level bulk approval with chunk-level exceptions.

Reasoning:

- Chunk-by-chunk approval is safest but too slow for lecturers.
- Blind document-level approval is too risky.
- Bulk approve with exceptions gives a pragmatic V1 flow.

Supported actions:

- approve all ready chunks in a document;
- mark individual chunks rejected;
- mark individual chunks needs review;
- approve individual chunks;
- edit metadata for clear mistakes;
- edit chunk content only with strong audit logging, or defer content editing to V2 if risk is too high.

Every review action should record:

- reviewer;
- timestamp;
- previous status;
- new status;
- comments;
- changed fields, if any.

### 7. Publish

Publish should only use approved, embedding-eligible chunks.

Conceptual flow:

```text
APPROVED chunks
->
embedding generation
->
vector store update
->
mark module version published
->
update active learner module registry
->
module available to Learner AI Mentor
```

Only `PUBLISHED` active module versions should be visible to learner retrieval. This prevents uploaded drafts, failed preparation jobs, and unreviewed chunks from contaminating learner answers.

## Lifecycle

Minimum lifecycle:

```text
UPLOADED
->
PREPARING
->
PREPARED
->
NEEDS_REVIEW
->
APPROVED
->
PUBLISHED
```

Additional statuses:

- `PREPARATION_FAILED`
- `REJECTED`
- `ARCHIVED`
- `PUBLISHING`
- `PUBLISH_FAILED`

Recommended distinction:

- Module version status: `DRAFT`, `PREPARING`, `READY_FOR_REVIEW`, `APPROVED`, `PUBLISHING`, `PUBLISHED`, `ARCHIVED`.
- Document status: `UPLOADED`, `PREPARED`, `NEEDS_REVIEW`, `APPROVED`, `REJECTED`.
- Chunk status: `READY`, `NEEDS_REVIEW`, `APPROVED`, `REJECTED`, `PUBLISHED`.

## Storage and Data Model

V1 should use a database abstraction. SQLite is acceptable for local/demo V1, but the code should hide persistence behind repository/service classes so PostgreSQL can be adopted later without rewriting Admin logic.

Recommended persisted entities:

### `modules`

- `module_id`
- `module_name`
- `level`
- `description`
- `created_by`
- `created_at`
- `status`
- `active_version_id`

### `module_versions`

- `version_id`
- `module_id`
- `version_label`
- `status`
- `created_at`
- `published_at`
- `published_by`
- `prepared_artifact_path`
- `validation_report_path`
- `retrieval_config_path`
- `vector_collection_name`

### `documents`

- `document_id`
- `module_id`
- `version_id`
- `filename_original`
- `storage_path`
- `document_type`
- `knowledge_role`
- `instructional_unit`
- `level`
- `uploaded_by`
- `uploaded_at`
- `checksum_sha256`
- `status`

### `preparation_jobs`

- `job_id`
- `module_id`
- `version_id`
- `status`
- `started_at`
- `finished_at`
- `requested_by`
- `error_message`
- `summary_json`

### `chunks`

- `chunk_id`
- `module_id`
- `version_id`
- `document_id`
- `section_title`
- `topic`
- `task_reference`
- `instructional_unit`
- `page_start`
- `page_end`
- `knowledge_role`
- `status`
- `embedding_eligible`
- `content`
- `warnings_json`
- `source_artifact_path`

### `chunk_reviews`

- `review_id`
- `chunk_id`
- `reviewer`
- `status`
- `comments`
- `reviewed_at`
- `changed_fields_json`

### `publish_jobs`

- `publish_job_id`
- `module_id`
- `version_id`
- `status`
- `started_at`
- `finished_at`
- `published_chunk_count`
- `vector_collection_name`
- `error_message`

## Admin API Proposal

Minimal V1 API:

```text
POST   /api/admin/modules
GET    /api/admin/modules
GET    /api/admin/modules/{module_id}
PATCH  /api/admin/modules/{module_id}

POST   /api/admin/modules/{module_id}/versions
GET    /api/admin/modules/{module_id}/versions
GET    /api/admin/modules/{module_id}/versions/{version_id}

POST   /api/admin/modules/{module_id}/versions/{version_id}/documents
GET    /api/admin/modules/{module_id}/versions/{version_id}/documents
PATCH  /api/admin/documents/{document_id}
DELETE /api/admin/documents/{document_id}

POST   /api/admin/modules/{module_id}/versions/{version_id}/prepare
GET    /api/admin/preparation-jobs/{job_id}
GET    /api/admin/modules/{module_id}/versions/{version_id}/preparation

GET    /api/admin/modules/{module_id}/versions/{version_id}/chunks
GET    /api/admin/chunks/{chunk_id}
POST   /api/admin/chunks/{chunk_id}/approve
POST   /api/admin/chunks/{chunk_id}/reject
POST   /api/admin/chunks/bulk-review

POST   /api/admin/modules/{module_id}/versions/{version_id}/approve
POST   /api/admin/modules/{module_id}/versions/{version_id}/publish
GET    /api/admin/publish-jobs/{publish_job_id}
```

These endpoints are separate from:

- learner `/api/chat`;
- evaluation `/api/evaluation/*`.

## V1 Admin UI Proposal

Minimum pages:

1. Module List
   - module name, level, active version, status, last updated.
2. Create Module
   - module ID/slug, name, level, version, description.
3. Module Metadata
   - editable draft metadata, active version, status.
4. Documents
   - upload files, assign document type, knowledge role, instructional unit.
5. Preparation Status
   - job progress, processed documents, chunk counts, warnings.
6. Prepared Chunks
   - filter by document, role, warning, status; inspect content and metadata.
7. Review
   - approve/reject chunks; bulk approve document with exceptions.
8. Publish Summary
   - approved chunks, excluded chunks, embedding eligible count, warnings.
9. Publish Status
   - embedding/vector update progress and active published version.

Terminology should be lecturer-friendly:

- Preparing knowledge
- Needs review
- Approved
- Published

Avoid exposing:

- embeddings;
- vector distances;
- ChromaDB collection internals;
- reranking;
- chunk token sizes by default.

## Publish and Versioning Strategy

Recommended V1 strategy:

- New uploads create a new draft module version.
- Old published version remains available until a new version publishes successfully.
- Publishing a new version atomically replaces the active version for learner retrieval.
- Learner retrieval uses only the active published version.
- Archived versions remain read-only for audit and rollback.

Example:

```text
DMV Basic v1 is active.
Lecturer uploads revised brief.
System creates DMV Basic v2 draft.
Lecturer prepares + reviews v2.
Publish v2 succeeds.
Active version switches from v1 to v2.
v1 remains archived/read-only.
```

If embedding fails:

- keep old active version unchanged;
- mark publish job `PUBLISH_FAILED`;
- show error and failed stage to lecturer;
- allow retry after issue is fixed.

If only some chunks publish:

- V1 should treat this as publish failure unless partial publish is explicitly approved by an admin.
- Safer default: all approved embedding-eligible chunks must publish, or none become active.

If lecturer republishes after document changes:

- create a new version;
- never mutate the already published version in place.

## Security Notes

V1 requirements:

- Admin/Lecturer access must be separated from learner access.
- Authentication/authorization can be implemented later, but API design should assume lecturer/admin roles.
- Learners must not access unpublished module versions or chunks.
- Validate file type against an allowlist: PDF, DOCX, PPTX, XLSX.
- Enforce file-size limits.
- Store uploads in controlled directories.
- Prevent path traversal.
- Sanitize display filenames.
- Store checksums for uploaded files.
- Avoid exposing local storage paths to learners.
- Audit review and publish actions.
- Do not allow arbitrary YAML path input from API callers.

## Adding a Second Module

Example: Programming Fundamentals.

```text
Create module:
Programming Fundamentals
Level: Basic
Version: v1

Upload:
Programming Brief.pdf
IU1.pdf
IU2.pdf
Learner Guide.pdf

Assign roles:
Programming Brief.pdf -> OFFICIAL_REQUIREMENT
IU1.pdf, IU2.pdf -> LEARNING_MATERIAL
Learner Guide.pdf -> MODULE_GUIDANCE

Prepare
Review
Approve
Publish
```

No new topic map or module-specific Python parser should be required. The same source metadata, section detection, semantic chunking, validation, role-aware retrieval, evidence authority, and learner chat flow should apply.

## Representing Current DMV Through Admin Later

Current `configs/modules/dmv_basic.yaml` already represents what Admin would eventually generate:

- module ID: `PDDS-DMV`
- module name: `Data Modelling and Visualisation`
- level: `Basic`
- output dir: `prepared_knowledge/dmv_basic`
- 9 source documents with document IDs, types, roles, IUs, and paths.

Future migration should:

1. create a `modules` row for DMV Basic;
2. create a `module_versions` row for v1;
3. import the 9 source records into `documents`;
4. link existing prepared artifacts to the version;
5. mark current v1 as published/active without changing learner behavior;
6. leave current YAML/config paths in place until Admin publish can generate replacements safely.

Do not migrate DMV during Admin design.

## Recommended Implementation Phases

1. Persistence foundation
   - SQLite schema or repository abstraction for modules, versions, documents, jobs, chunks, reviews, publish jobs.
2. Module/document APIs
   - create/list modules, create versions, upload documents, assign roles.
3. Preparation service wrapper
   - generate module config from stored metadata and call existing `prepare_module`.
4. Preparation result import
   - store chunk summaries, warnings, validation counts, artifact paths.
5. Review APIs
   - chunk/document approval, rejection, comments, audit trail.
6. Publish service
   - embed approved chunks, create/update vector collection, generate retrieval/chat module config, activate version atomically.
7. Admin UI
   - simple module list, upload, preparation status, review, publish pages.
8. Current DMV migration
   - import existing demo as a published module version once Admin services are stable.

This order protects the frozen learner demo and avoids building UI screens before the underlying lifecycle is reliable.

## Open Decisions and Risks

- Authentication: local demo can defer, but real Admin requires lecturer/admin auth before upload/publish.
- Storage: SQLite is fine for V1, but the service layer should allow PostgreSQL later.
- File formats: PDF is proven; DOCX/PPTX/XLSX extraction needs generic adapters and validation.
- Content editing: allowing chunk content edits improves rescue workflows but creates audit and academic-risk concerns. V1 may limit edits to metadata/comments.
- Role extensibility: roles are currently code-backed; future roles should be data/config driven.
- Publish atomicity: vector-store update must avoid breaking active learner modules if publish fails.
- Current retrieval config generation: Admin publish must generate module-specific retrieval/chat config without corrupting the frozen DMV setup.
- Rubric extraction variation: non-DMV briefs may structure rubrics differently; validation/review must surface reconstruction warnings.
- Multi-tenant storage: future modules and lecturers need scoped storage and permissions.
- Version rollback: V1 should preserve archived versions, but rollback UI may be V2.

## Reusability Assessment

The current architecture is a good base for Admin V1 because module-specific information is already mostly outside Python code in YAML configuration, and the preparation/retrieval layers operate from metadata, roles, and source paths. The biggest adaptation is replacing manually edited local YAML/files with persisted module/document/version records and service wrappers that generate equivalent configs safely.

Admin V1 should therefore focus on lifecycle, persistence, upload safety, review/approval, and publish orchestration, not on new parsing logic or a separate ingestion implementation.

## Admin V1 Phase 1 - Persistence Foundation

Phase 1 creates the reusable metadata foundation only. It does not run uploads, knowledge preparation, chunk review, embeddings, Chroma updates, publishing, learner module switching, or DMV migration.

### SQLite Purpose

SQLite stores Admin/Lecturer management state:

- modules;
- module versions;
- document metadata;
- fixed knowledge-role reference data;
- lifecycle/status values through service validation;
- created/updated timestamps.

SQLite does not store embeddings, Chroma vectors, API keys, full vector-store contents, or prepared chunk content in Phase 1.

### Database Location

The local database path is:

```text
data/ai_mentor.db
```

Initialization is repeatable and creates the `data` directory when needed. It does not delete or recreate existing data.

### Schema

Implemented tables:

- `knowledge_roles`: fixed V1 role definitions and authority priority.
- `modules`: internal module record with unique `module_code`.
- `module_versions`: version/level records linked to a module.
- `documents`: metadata records linked to a module version and knowledge role.

Important constraints:

- `modules.module_code` is unique.
- `module_versions` has a unique `(module_id, version, level)` constraint.
- documents reference `module_versions`.
- documents reference `knowledge_roles`.
- foreign keys are enabled per SQLite connection.
- indexes exist for module-version lookup, document lookup by version, and document lookup by role.

### Repository Abstraction

The implementation follows:

```text
Admin API / Services
-> AdminRepository interface
-> SQLiteAdminRepository
```

Files:

- `backend/admin/repository.py`: repository interface and persistence exceptions.
- `backend/admin/sqlite_repository.py`: SQLite implementation.
- `backend/admin/service.py`: validation and business-facing persistence operations.

This keeps Admin workflow logic from being scattered through SQLite-specific SQL and leaves room for a future PostgreSQL repository.

### Entities

`Module`:

- `id`
- `module_code`
- `name`
- `description`
- `status`
- `created_at`
- `updated_at`

`ModuleVersion`:

- `id`
- `module_id`
- `version`
- `level`
- `description`
- `status`
- `is_active`
- `created_at`
- `updated_at`

`DocumentMetadata`:

- `id`
- `module_version_id`
- `original_filename`
- `stored_filename`
- `file_path`
- `file_type`
- `document_type`
- `knowledge_role`
- `instructional_unit`
- `version`
- `status`
- `uploaded_by`
- `created_at`
- `updated_at`

### Knowledge Roles and Statuses

Knowledge roles are centralized in `backend/admin/constants.py`:

- `OFFICIAL_REQUIREMENT`
- `LEARNING_MATERIAL`
- `MODULE_GUIDANCE`

Phase 1 does not allow lecturer-created roles.

Statuses are separated by domain:

- module statuses: `DRAFT`, `ACTIVE`, `ARCHIVED`;
- module-version statuses: `DRAFT`, `PREPARING`, `PREPARED`, `NEEDS_REVIEW`, `APPROVED`, `PUBLISHED`, `FAILED`, `REJECTED`, `ARCHIVED`;
- document statuses: `UPLOADED`, `PREPARING`, `PREPARED`, `NEEDS_REVIEW`, `APPROVED`, `FAILED`, `REJECTED`, `ARCHIVED`.

### Phase 1 APIs

Implemented proof endpoints:

```text
GET  /api/admin/metadata

POST /api/admin/modules
GET  /api/admin/modules
GET  /api/admin/modules/{module_id}

POST /api/admin/modules/{module_id}/versions
GET  /api/admin/modules/{module_id}/versions
GET  /api/admin/versions/{version_id}

POST /api/admin/versions/{version_id}/documents
GET  /api/admin/versions/{version_id}/documents
GET  /api/admin/documents/{document_id}
```

The document POST creates metadata only. It does not upload or process files.

### Tests

Focused tests live in:

```text
tests/test_admin_persistence.py
```

They cover:

- fresh initialization;
- repeated initialization;
- foreign-key enforcement;
- unique module code;
- module create/list/retrieve;
- duplicate module rejection;
- invalid module data rejection;
- module-version create/list/retrieve;
- invalid parent module rejection;
- duplicate version for same module/version/level rejection;
- document metadata create/list/retrieve;
- valid and invalid knowledge roles;
- invalid module version rejection;
- two unrelated test modules using the same repository/service path.

### Remaining Phase 2 Work

Admin Phase 2 should add the preparation service wrapper:

- safe document upload/storage;
- generated module config from database records;
- call the existing `backend.knowledge_preparation.prepare_module`;
- preparation job records;
- import preparation summaries and validation warnings;
- keep learner config/vector-store behavior unchanged until an explicit publish phase.

## Admin V1 Phase 2 - Upload & Knowledge Preparation Integration

Phase 2 connects Admin module/version/document metadata to the existing reusable preparation engine. It still does not build an Admin UI, approve/reject chunks, publish to Chroma, create embeddings for Admin modules, switch active learner modules, or migrate the frozen DMV learner setup.

### Upload and Storage Design

Admin uploads are stored outside SQLite under:

```text
data/uploads/{module_code}/{version_id}/{generated-safe-filename}
```

SQLite stores only document metadata. The original filename is preserved for display, while the stored filename is a generated UUID-based name with the validated extension.

Upload validation is centralized in `backend/admin/constants.py` and `backend/admin/upload_service.py`:

- allowed extensions: `.pdf`, `.docx`, `.pptx`, `.xlsx`;
- maximum upload size: 50 MB;
- empty files rejected;
- original filename reduced to a display-safe basename;
- generated storage filename, not user-controlled;
- upload path resolved and checked under `data/uploads`;
- invalid module-version IDs rejected;
- knowledge role validated against the fixed V1 role set.

Authentication is still out of scope. `uploaded_by` remains a supplied local/demo value.

### Supported Preparation Formats

Phase 2 upload accepts PDF, DOCX, PPTX, and XLSX metadata/files. Preparation currently supports PDF only because the existing `backend/knowledge_preparation` extractor is PDF-based.

Unsupported preparation formats are not silently chunked. They are preserved as uploaded metadata and marked for review with `unsupported_preparation_format`. DOCX/PPTX/XLSX generic extraction adapters remain future work.

### Preparation Service Wrapper

Implemented wrapper:

```text
AdminPreparationService
-> builds module config from SQLite records
-> calls backend.knowledge_preparation.prepare_module
-> imports prepared chunks and warnings
-> records preparation job status/results
```

The wrapper builds the same generic config shape as `configs/modules/dmv_basic.yaml` using:

- `module_code` as `module_id`;
- module name;
- module-version level;
- document metadata IDs;
- document type;
- knowledge role;
- instructional unit;
- uploaded file path.

The lecturer does not edit YAML manually. A generated config is saved beside the output as an implementation artifact.

### Preparation Job Schema

Implemented table: `preparation_jobs`.

Fields:

- `id`
- `module_version_id`
- `status`
- `started_at`
- `completed_at`
- `created_at`
- `created_by`
- `source_document_count`
- `chunk_count`
- `ready_count`
- `needs_review_count`
- `embedding_eligible_count`
- `warning_count`
- `error_message`
- `output_path`
- `validation_report_path`

Statuses:

- `QUEUED`
- `RUNNING`
- `COMPLETED`
- `COMPLETED_WITH_WARNINGS`
- `FAILED`

Preparation remains synchronous in Phase 2, but the service boundary can later be replaced by a background queue.

### Prepared Output and Chunk Persistence

Admin-prepared artifacts are stored separately from frozen DMV prototype artifacts:

```text
data/prepared/{module_code}/{version_id}/
  module_config.yaml
  preparation_config_used.yaml
  prepared_chunks.jsonl
  validation_report.json
```

The chosen V1 persistence approach is hybrid:

- keep full prepared output as JSONL/report files for audit and compatibility with the existing engine;
- import chunk records into SQLite for Phase 3 review.

Implemented table: `prepared_chunks`.

Fields include:

- preparation job and module-version IDs;
- document ID;
- chunk ID;
- section/topic/task/IU metadata;
- page range;
- knowledge role;
- chunk status;
- embedding eligibility;
- warning count;
- content;
- created timestamp.

No embeddings or vector values are stored in SQLite.

### Warning Persistence

Implemented table: `preparation_warnings`.

Warnings imported from validation reports include extraction warnings, chunk review warnings, table warnings, low-text/image-heavy page warnings, missing metadata, duplicate content, and related validation issues. Unsupported preparation formats are also recorded as warnings.

Image-heavy warnings remain informational under the current V1 policy unless later review identifies missing textual knowledge.

### Phase 2 APIs

Added endpoints:

```text
POST /api/admin/versions/{version_id}/documents/upload
POST /api/admin/versions/{version_id}/prepare

GET  /api/admin/versions/{version_id}/preparation-jobs
GET  /api/admin/preparation-jobs/{job_id}
GET  /api/admin/preparation-jobs/{job_id}/chunks
GET  /api/admin/preparation-jobs/{job_id}/warnings
```

Chunk listing supports pagination and filters:

- `limit`
- `offset`
- `document_id`
- `status`
- `knowledge_role`
- `embedding_eligible`

### Lifecycle Effects

Preparation uses only documents currently in `UPLOADED` status.

Lifecycle behavior:

```text
Version DRAFT
-> PREPARING
-> PREPARED or NEEDS_REVIEW or FAILED
```

Document behavior:

```text
UPLOADED
-> PREPARING
-> PREPARED or NEEDS_REVIEW or FAILED
```

Preparation does not set `APPROVED`, `PUBLISHED`, `ACTIVE`, or learner visibility.

### Failure Handling

If there are no uploaded documents, preparation is rejected before a job runs.

If all uploaded documents use unsupported preparation formats, the job is marked `FAILED`, documents are marked `NEEDS_REVIEW`, and warnings explain the missing adapters.

If the existing preparation engine raises an exception, the job is marked `FAILED`, supported documents are marked `FAILED`, the module version is marked `FAILED`, and the error is persisted. Source uploads are not deleted.

### Tests

Added:

```text
tests/test_admin_phase2.py
testing/admin_phase2_api_smoke.py
```

Coverage includes:

- upload extension validation;
- empty-file rejection;
- safe filename/path behavior;
- document metadata creation;
- preparation job creation and status;
- generated prepared JSONL/report output;
- chunk import into SQLite;
- unsupported format handling;
- two unrelated modules prepared through the same services;
- API-level upload and preparation smoke.

### Remaining Phase 3 Work

Admin Phase 3 should implement Knowledge Review & Approval:

- read-only chunk review UI/API support;
- approve/reject/needs-review transitions;
- document-level bulk approval with chunk-level exceptions;
- review comments and audit trail;
- metadata correction workflow;
- no publish or embeddings until a later publish phase.

## Admin V1 Phase 3 - Knowledge Review & Approval

Phase 3 adds review and approval over prepared Admin chunks. It does not publish, embed, update Chroma, switch learner modules, migrate current DMV YAML, or build the production Admin UI.

### Review Statuses

Prepared chunks now have a review lifecycle separate from preparation status:

```text
NEEDS_REVIEW
APPROVED
REJECTED
```

New chunks imported from preparation start as `NEEDS_REVIEW`. A chunk is not automatically approved just because preparation succeeded.

### Review and Audit Fields

`prepared_chunks` now stores:

- `review_status`
- `reviewed_by`
- `reviewed_at`
- `review_comment`
- `updated_by`
- `updated_at`
- `metadata_change_comment`

Append-only review audit is stored in `review_events`:

- `id`
- `entity_type`
- `entity_id`
- `action`
- `actor`
- `previous_status`
- `new_status`
- `comment`
- `created_at`

Actions include:

- `APPROVE_CHUNK`
- `REJECT_CHUNK`
- `RESET_CHUNK`
- `UPDATE_METADATA`
- `EXCLUDE_DOCUMENT`
- `APPROVE_VERSION`
- `REOPEN_VERSION`

Audit history is not deleted when current status changes.

### Chunk Review Rules

Lecturers can inspect chunk content, document/page metadata, section/topic, role, embedding eligibility, and warnings.

Supported chunk actions:

- approve;
- reject;
- return to needs review;
- add review comments.

Approving a chunk is blocked by default when the chunk is embedding-ineligible or has blocking warning conditions. The API supports an explicit override flag for selected chunk actions, but document-level automatic bulk approval does not use that override.

### Bulk Review

Phase 3 supports:

- approve selected chunks;
- reject selected chunks;
- reset selected chunks to `NEEDS_REVIEW`;
- approve all eligible chunks in a document.

The safest V1 rule is implemented for document-level bulk approval:

- only embedding-eligible chunks are approved;
- chunks with blocking warning conditions are skipped;
- skipped chunks remain `NEEDS_REVIEW`;
- lecturer review comments are recorded on changed chunks.

### Metadata Correction Policy

Allowed V1 metadata corrections:

- section title;
- topic;
- task reference;
- instructional unit;
- knowledge role, only if the new value is one of the validated V1 roles.

Metadata changes record:

- `updated_by`;
- `updated_at`;
- `metadata_change_comment`;
- audit event `UPDATE_METADATA`.

Prepared chunk content cannot be edited in V1. If extracted content is wrong or incomplete, the lecturer should reject the chunk, add a comment, fix/re-upload the source, and re-run preparation. This keeps the source document as the authority and prevents manually edited chunks drifting away from source evidence.

### Warning Classification

Warning classification is centralized and generic.

Informational warnings include:

- `low_text_image_heavy_page`
- `very_low_text_page`
- `table_detected_requires_structure_review`
- `short_chunk_requires_review`
- `chunk_needs_review`
- `duplicate_chunk_content`
- `missing_instructional_unit`

Blocking warnings include:

- `source_file_missing`
- `missing_required_chunk_metadata`
- `empty_chunk`
- `duplicate_chunk_id`
- `unsupported_preparation_format`
- `extraction_warning`
- `unsupported_knowledge_role`

Informational warnings appear in summaries but do not automatically block approval. Blocking warnings prevent version approval unless resolved or tied to an excluded document.

### Document Exclusion

Uploaded documents that were not prepared, including unsupported DOCX/PPTX/XLSX files, cannot silently pass version approval.

V1 supports explicit document exclusion:

```text
POST /api/admin/documents/{document_id}/exclude
```

The file is not deleted. The document is marked `ARCHIVED` and records:

- `excluded_by`
- `excluded_at`
- `exclusion_reason`

Excluded documents do not block version approval.

### Review Summaries

Document summary:

```text
GET /api/admin/documents/{document_id}/review-summary
```

Version summary:

```text
GET /api/admin/versions/{version_id}/review-summary
```

Summaries include total chunks, approved, rejected, needs review, embedding-eligible count, warning count, blocking warning count, informational warning count, warning types, and approval blockers.

### Version Approval Rule

Safe V1 rule:

Version can be `APPROVED` only if:

- at least one preparation job completed successfully;
- no active uploaded document remains unprepared or unsupported;
- unsupported/unprepared documents are either prepared successfully or explicitly excluded with a recorded reason;
- no blocking preparation warning remains for active documents;
- at least one chunk is approved;
- no chunk remains `NEEDS_REVIEW`;
- every chunk review is complete as either `APPROVED` or intentionally `REJECTED`.

Rejected chunks do not block version approval because rejection is treated as intentional exclusion from the approved knowledge set.

Approval records:

- `approved_by`
- `approved_at`
- `approval_comment`

An `APPROVED` unpublished version can be returned to `NEEDS_REVIEW` before Phase 4 publish. This records a `REOPEN_VERSION` audit event.

### Phase 3 APIs

Added endpoints:

```text
GET  /api/admin/chunks/{chunk_id}
POST /api/admin/chunks/{chunk_id}/approve
POST /api/admin/chunks/{chunk_id}/reject
POST /api/admin/chunks/{chunk_id}/needs-review
PATCH /api/admin/chunks/{chunk_id}/metadata

POST /api/admin/chunks/bulk-review

GET  /api/admin/documents/{document_id}/review-summary
POST /api/admin/documents/{document_id}/exclude

GET  /api/admin/versions/{version_id}/review-summary
POST /api/admin/versions/{version_id}/approve
POST /api/admin/versions/{version_id}/reopen

GET  /api/admin/review-events
```

### Tests

Added:

```text
tests/test_admin_phase3.py
testing/admin_phase3_api_smoke.py
```

Coverage includes:

- approve/reject/reset;
- review comments;
- append-only review events;
- metadata correction;
- invalid knowledge role rejection;
- content editing rejection through API schema;
- bulk approve eligible chunks;
- ineligible chunks not silently approved;
- document and version summary counts;
- approval eligibility;
- approval failure with unresolved review;
- approval success when review is complete;
- version reopen before publish;
- unsupported uploaded document blocks approval until excluded;
- two unrelated modules reaching `APPROVED` through the same services.

### Remaining Phase 4 Work

Admin Phase 4 should implement Publish & Vector Activation:

- publish only approved module versions;
- generate embeddings for approved, embedding-eligible, non-rejected chunks;
- create/update a module-version-specific Chroma collection safely;
- activate the published version for learner retrieval atomically;
- preserve rollback to previous active version if publish fails;
- keep Admin draft/review versions invisible to learners until publish succeeds.

## Admin V1 Phase 4 - Publish & Vector Activation

Phase 4 connects approved Admin module versions to the vector layer. It still does not build the Admin frontend, add authentication, migrate the current DMV demo into Admin, add DOCX/PPTX/XLSX extraction adapters, tune retrieval, tune prompts, or deploy.

### Publish Eligibility

A module version can be published only when:

- `module_versions.status == APPROVED`;
- Phase 3 approval conditions still pass at publish time;
- there is at least one approved, embedding-eligible chunk;
- active uploaded documents are prepared or explicitly excluded;
- no active document has blocking warnings.

The publish service rechecks eligibility and does not rely blindly on prior approval.

### Chunk Selection

Only chunks matching all of these conditions are embedded:

- belongs to the exact module version being published;
- `review_status == APPROVED`;
- `embedding_eligible == true`;
- source document is not excluded;
- source document has no unresolved blocking warning.

Never published:

- `REJECTED` chunks;
- `NEEDS_REVIEW` chunks;
- embedding-ineligible chunks;
- chunks from excluded documents;
- chunks from failed preparation;
- chunks from another module version.

### Collection Naming

Admin-published collections use a deterministic, sanitized, version-specific name:

```text
mentor_{module_code}_{level}_{version}_{version_id_prefix}
```

Example:

```text
mentor_prog_fund_basic_v1_a1b2c3d4
```

The current frozen DMV demo collection is not overwritten or deleted. Admin collections are stored separately under:

```text
data/admin_chroma
```

### Publish Jobs

Implemented table: `publish_jobs`.

Fields:

- `id`
- `module_version_id`
- `status`
- `started_at`
- `completed_at`
- `requested_by`
- `source_chunk_count`
- `embedded_chunk_count`
- `collection_name`
- `error_message`
- `created_at`

Statuses:

- `QUEUED`
- `RUNNING`
- `COMPLETED`
- `FAILED`

### Vector Metadata

Published vectors preserve retrieval metadata:

- module code;
- module name;
- module version ID and label;
- level;
- document ID;
- document type;
- knowledge role;
- section title;
- topic;
- task reference;
- instructional unit;
- source file;
- page range;
- chunk ID;
- review status;
- embedding eligibility.

The existing `OFFICIAL_REQUIREMENT`, `LEARNING_MATERIAL`, and `MODULE_GUIDANCE` roles are preserved so authority-aware retrieval and response behavior can continue to work.

### Verification Before Activation

Activation happens only after vector verification succeeds.

Verification checks:

- collection exists;
- vector count equals expected publishable chunk count;
- all retrieved metadata belongs to the requested module version;
- all vector metadata has `review_status == APPROVED`.

If verification fails, the publish job is marked `FAILED` and the version is not activated.

### Atomic Activation

Successful publish flow:

```text
validate approval
-> create publish job
-> create new version-specific collection
-> generate embeddings
-> upsert vectors and metadata
-> verify expected count and metadata
-> mark publish job COMPLETED
-> mark version PUBLISHED and active
-> mark older same-module/same-level versions inactive
```

Only one version is active for the same module and level.

### Failure Handling

If publishing fails:

- publish job becomes `FAILED`;
- error message is stored;
- new collection is never registered as active;
- previous active version remains active;
- previous collection is not deleted.

Failed staging collections are identifiable by publish-job records and can be cleaned later by a safe maintenance task. Phase 4 does not perform destructive cleanup.

### Old Version Behavior

When a newer version is published successfully:

- old version remains `PUBLISHED`;
- old version becomes inactive;
- old Chroma collection is retained for future rollback capability.

Republishing creates a new collection rather than mutating an active collection in place.

### Learner Module Resolution

Phase 4 adds a migration bridge:

```text
static chat_modules.yaml registry first
-> Admin active published version fallback
```

Frozen DMV learner behavior remains protected because the static registry still resolves `PDDS-DMV` Basic first.

Admin-published modules are resolved from SQLite only when the requested module/level is not found in the static registry. The active version provides the retrieval config and collection name.

### Audit Events

Publish uses the existing append-only `review_events` table for:

- `PUBLISH_STARTED`
- `PUBLISH_COMPLETED`
- `PUBLISH_FAILED`
- `VERSION_ACTIVATED`

Each event records actor, timestamp, version, collection/count/error context, and status transition.

### Phase 4 APIs

Added endpoints:

```text
POST /api/admin/versions/{version_id}/publish
GET  /api/admin/versions/{version_id}/publish-jobs
GET  /api/admin/publish-jobs/{job_id}
GET  /api/admin/modules/{module_id}/active-version?level={level}
```

### Tests

Added:

```text
tests/test_admin_phase4.py
```

Coverage includes:

- non-approved version cannot publish;
- approved version can publish;
- only approved/eligible chunks embedded;
- version-specific collection created;
- vector count verification;
- activation only after verification;
- failed publish does not activate;
- previous active version survives failure;
- v2 activation deactivates v1 but retains v1;
- republish/new version does not mutate active collection in place;
- cross-module vector isolation.

### Remaining Work

The backend is now ready for an Admin UI V1 to drive the implemented APIs. Remaining backend/product work includes:

- Admin/Lecturer frontend;
- authentication and real user identity;
- safe rollback UI/workflow;
- maintenance cleanup for failed staging collections;
- DOCX/PPTX/XLSX preparation adapters;
- optional migration of current DMV demo into Admin once the UI is proven.

## Admin V1 Phase 5 - Lecturer/Admin UI

Phase 5 adds a local demo Lecturer/Admin workspace to the existing learner frontend. It uses the Admin APIs from Phases 1-4 and does not change learner retrieval, Mentor prompts, chunking, embeddings logic, or the frozen DMV demo.

### Navigation

The existing top navigation now includes:

- Learner Chat;
- Evaluation;
- AI Mentor Capabilities;
- Lecturer/Admin.

The Lecturer/Admin tab opens the Admin workspace. It is clearly marked as a local V1 demo and does not imply production authentication.

### Module Workflow

The Admin landing view shows Admin-created modules and supports:

- list modules;
- create module;
- open module;
- list versions;
- create version;
- open version workspace.

Lecturer-facing labels use module code and module name. Internal database IDs are not the primary display identifier.

### Version Workspace

The version workspace follows the workflow:

```text
Documents -> Prepare -> Review -> Approve -> Publish
```

It shows current version status and active state where applicable.

### Upload Workflow

The Documents section supports multipart document upload with:

- file;
- knowledge role;
- document type;
- optional instructional unit;
- optional document version;
- uploaded-by demo value.

Knowledge roles are shown with lecturer-friendly labels:

- Official Requirement;
- Learning Material;
- Module Guidance.

Role help text explains the intended source types.

### File-Format Limitation

The UI communicates current support clearly:

- PDF: supported for knowledge preparation;
- DOCX/PPTX/XLSX: upload supported, knowledge preparation not yet supported.

The UI does not claim unsupported formats can become RAG-ready.

### Preparation UI

The Prepare Knowledge section explains that preparation creates searchable knowledge and does not publish to learners. The Prepare button calls the Phase 2 preparation API, shows loading state, and displays the latest preparation summary:

- documents processed;
- prepared chunks;
- embedding eligible;
- needs review;
- warnings.

Warning codes are translated into lecturer-friendly labels, with technical details available inside expandable sections.

### Review UI

The Review Prepared Knowledge section supports:

- status filter: all, needs review, approved, rejected;
- document filter;
- knowledge-role filter;
- chunk cards with source, page, role, section, prepared content, warnings, and review status;
- review comments;
- approve/reject/reset actions.

Prepared chunk content is displayed read-only.

### Metadata Correction

Each chunk has a secondary Edit Metadata panel for:

- section title;
- topic;
- task reference;
- instructional unit;
- knowledge role.

Content editing is not exposed.

### Bulk Review

The UI supports:

- approve selected;
- reject selected;
- reset selected to needs review;
- approve eligible chunks in a selected document.

If backend bulk review skips chunks, the UI reports how many were updated and notes that skipped chunks require attention.

### Approval UI

The Approve Version section displays approval blockers from the backend. The button is enabled only when the version review summary reports eligibility.

The UI explains that approval confirms reviewed knowledge is ready for publishing, but does not publish to learners.

Approved, unpublished versions can be returned to review using the existing backend lifecycle rule.

### Publish UI

Publishing is shown only when the version is `APPROVED`.

The UI requires explicit browser confirmation before calling the publish API. Normal UI copy avoids vector/embedding implementation details and says:

- publishing creates searchable AI Mentor knowledge;
- only approved knowledge is published;
- rejected and excluded knowledge are not published.

On success, it shows that the version is active. On failure, it explains that the new version was not activated and existing learner knowledge remains unchanged.

### Error States

The UI handles:

- API failure;
- duplicate module code;
- invalid upload;
- unsupported preparation format;
- preparation failure;
- approval blockers;
- publish failure;
- network/server error.

Backend messages are shown in readable panels. Python stack traces are not displayed.

### Tests

Added:

```text
tests/test_admin_ui.py
```

Coverage includes:

- Admin navigation is present;
- frontend assets load;
- required Admin workflow labels exist;
- existing learner chat route still works;
- evaluation route still works;
- Admin metadata route works.

Existing backend tests continue to cover end-to-end Admin workflow behavior through APIs and services:

- module creation;
- version creation;
- upload;
- preparation;
- review;
- approval;
- publish;
- active-version switching;
- vector isolation.

### Known Limitations

- No authentication or role-based access.
- No production Admin UI routing; this is a local single-page demo workspace.
- Publish requires a real `OPENAI_API_KEY` because embeddings are generated by the Phase 4 backend.
- DOCX/PPTX/XLSX extraction adapters are still not implemented.
- No rollback UI.
- No vector-store deletion/cleanup UI.
- No migration of the frozen DMV demo into Admin.

### Manager Demo Readiness

Lecturer/Admin V1 is ready for a manager demo of the full intended workflow from module creation through publish, provided PDF sources are used and an OpenAI API key is configured for real publishing.
