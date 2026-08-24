# DMV Basic V1 RAG Preparation Design

Purpose: design extraction, chunking, and metadata preparation for the DMV Basic AI Mentor V1 knowledge base.

This design uses only the frozen nine-document baseline. It does not reconsider source selection.

## Selected Nine Files Confirmed

### Official Requirement Source

1. `knowledge_base/brief/DMV-Project_Brief_Basic-v1-formatted.pdf`

Authoritative for the project scenario, objectives, business requirements, dataset description, success factors, Task 1-5 requirements, expected outcomes, deliverables, marking rubric, and Foundation / Proficient expectations.

### Learning Material Sources

2. `knowledge_base/learning_materials/IU1_1.pdf`
3. `knowledge_base/learning_materials/IU1_2.pdf`
4. `knowledge_base/learning_materials/IU1_3.pdf`
5. `knowledge_base/learning_materials/IU2_1.pdf`
6. `knowledge_base/learning_materials/IU2_2.pdf`
7. `knowledge_base/learning_materials/IU3_1.pdf`
8. `knowledge_base/learning_materials/IU4_1.pdf`

### Module Guidance Source

9. `knowledge_base/module_guide/Learner_Guide_PDDS_DMV_v4.pdf`

Authoritative for general module/course guidance contained in the Learner Guide.

Excluded from V1: `DMV-Basic_Assignments-v1-formatted.pdf`, Assignment 1-5 guide PDFs, Know-How documents, Case Studies, Submission Templates, and Advanced-level documents.

This is a design document only. It does not modify source files, create filtered PDFs, create embeddings, create ChromaDB/vector DB, call OpenAI, implement retrieval, implement LLM prompts, implement frontend/backend, build Admin UI, or commit anything.

## Inspected Document Structure

| File | Observed structure | Preparation implications |
|---|---|---|
| `DMV-Project_Brief_Basic-v1-formatted.pdf` | 8 pages, no PDF outline/bookmarks. Clear uppercase headings: `PROJECT TITLE`, `BUSINESS SCENARIO`, `PROJECT OBJECTIVE`, `BUSINESS REQUIREMENTS`, `DATASET PROVIDED`, `SUCCESS FACTORS`, `PROJECT TASKS`, `DELIVERABLES`, `MARKING RUBRICS`. Many bullet lists. Rubric table spans pages 7-8. Repeated header/footer text appears on each page. | Use heading detection from text blocks, not PDF bookmarks. Split tasks and deliverables semantically. Reconstruct rubric rows across pages with assessment area, task reference, performance bands, and marks intact. |
| `IU1_1.pdf` | 15 pages, no outline. Repeated header `Introduction to Data Analytics`. Numbered sections: `1. What is Data Analytics?`, `2. Who is Data Analyst?`, `3. Roles in Data`, and `4. Tasks Of Data Analyst`. Contains conceptual paragraphs, examples, role descriptions, analytics types, and the data analyst task cycle. | Split by numbered section and teaching topic: data analytics definition, retail/business data examples, data storytelling, data analyst role, analytics types, data roles, and Prepare/Model/Visualize/Analyze/Manage tasks. Do not store the whole 15-page IU as one chunk. |
| `IU1_2.pdf` | 36 pages, no outline. Repeated header `Get Started Building With Power BI`. Numbered sections: Power BI introduction, workflow, building blocks, Desktop, Service, Desktop vs Service, apps. Some pages contain image/screenshot-dependent fragments. | Split by numbered section and subtopic. Preserve topics such as semantic models, reports, dashboards, visuals, Desktop, Service, publish/share. |
| `IU1_3.pdf` | 19 pages, no outline. Repeated header `Get Data for Analysis`. Numbered sections for getting data, files, relational data, online services. Lists and procedures appear across page boundaries. | Split by data-source section, then by procedure/topic such as file import, Navigator, Load vs Transform Data, source settings. |
| `IU2_1.pdf` | 30 pages, no outline. Repeated header `Data Transformation with Power BI`. Numbered sections for cleaning/loading, shaping, simplifying, data types, combining tables, profiling. Contains lists, procedural paragraphs, and image-dependent examples. | Split by transformation topic: Power Query Editor, headers, rename/remove columns, replace values/nulls, duplicates, data types, profiling. |
| `IU2_2.pdf` | 41 pages, no outline. Repeated header `Data Modelling with Power BI`. Numbered sections for modelling, star schema, tables, date table, dimensions, granularity, relationships/cardinality. Contains a fact/dimension comparison table. | Split large sections aggressively by modelling concept. Preserve table row relationships. Star schema and cardinality must become small, targeted concept chunks. |
| `IU3_1.pdf` | 31 pages, no outline. Repeated header `Data Modelling with DAX`. Numbered sections for DAX formulas, data types, operators, functions, variables, measures. Contains DAX data type and operator tables. | Split by DAX concept/function family. Preserve code examples and operator/data-type tables with context. |
| `IU4_1.pdf` | 62 pages, no outline. Repeated header `Power BI Formatting, Reports and Dashboards`. Numbered sections for report requirements, audience, report types, UI/UX, report design, layout, visual selection, formatting, KPIs, filters, slicers, details. Some pages are screenshot/image heavy. | Split by design topic and visual family. The large `Select report visuals` and filtering/slicer sections must not remain as broad 20+ page chunks. |
| `Learner_Guide_PDDS_DMV_v4.pdf` | 21 pages, no outline. Repeated header `Learner Guide_V4.0` and `WSQ Data Modelling & Visualization (SF)`. Sections include cover/module details, table of contents, revision history, `1. Module Brief`, `2. Learners Profile`, `3. Learning Outcomes & Targeted Job Roles`, `4. Technical Skills and Competencies`, `5. Learning Design`, `6. Assessments`, `7. Grading`, `8. Learning Resources`, `9. Recommended Readings`, `10. Class Size`, `11. Faculty Background`, and `12. Lesson Plan`. | Classify as `document_type: learner_guide` and `knowledge_role: MODULE_GUIDANCE`. Split by module-information section and by lesson-plan session groups, not fixed token windows. Use for general module guidance only; do not let it override Project Brief assessment requirements. |

Additional extraction findings from the actual files:

- The Brief uses a repeated running header/footer on every page: `Project Brief_v3.0`, `Data Modelling and Visualisation`, and a displayed `Page | 1` string that should not be used as the citation page number.
- The Brief index is on physical page 1, while the substantive requirement content starts on physical page 2.
- The Brief rubric is a two-page table on physical pages 7-8. `pdfplumber` detects it as one table per page, but the header is split across visual lines, especially `Proficient (75-` and `100%)`.
- The Brief text extraction loses or distorts some punctuation: `3-5 basic DAX measures` is extracted as `35 basic DAX measures`, and `Profit = Sales Amount - Cost Amount` is extracted without the minus sign. These are critical requirement values and must be validated against table/block extraction or manual review before ingestion.
- IU low-text pages are not empty source pages; they usually contain screenshots, examples, or step images. They should be flagged for review instead of discarded.

## Extraction Strategy

Use a two-pass extraction design.

### Pass 1: Layout-Aware Page Extraction

For every page, extract:

- physical PDF page number;
- text blocks with coordinates and reading order;
- words with coordinates where available;
- paragraph text;
- bullet and numbered-list text;
- table candidates;
- repeated header/footer candidates;
- image-heavy or low-text pages.

Recommended later implementation approach:

- Use PyMuPDF-style block extraction for layout and reading order.
- Use pdfplumber-style table extraction for table candidates.
- Fall back to full page text when block/table extraction is incomplete.

The Project Brief and IU files have no useful PDF outline, so headings must be inferred from text:

- uppercase section labels in the Brief;
- numbered IU headings such as `2. Star schema design`;
- standalone subheadings such as `Fact tables`, `Dimension tables`, `Slicers`, `Visual interactions`;
- slide/page-style large text only when present in extracted blocks.

### Pass 2: Normalized Document Tree

Convert extracted content into:

```text
Document
  Section
    Subsection
      Chunk candidate
        paragraphs
        lists
        tables
```

Normalization rules:

- Remove repeated running headers and footers from chunk body text.
- Preserve physical `page_start` and `page_end`.
- Preserve source headings and subheadings.
- Preserve bullets and numbered steps as lists.
- Preserve tables as Markdown-style rows or structured records.
- Mark image-heavy or fragmented pages with `status: needs_review` if important text appears missing.
- Do not combine Project Brief, IU, and Learner Guide text into one stored chunk.

Extraction repair rules:

- Normalize obvious PDF line-break artifacts without changing meaning.
- Preserve assessment-critical numbers, operators, marks, and ranges only after checking against layout/table extraction.
- If two extraction methods disagree on a requirement value, mark the chunk `needs_review` and keep the citation precise.
- Never silently repair rubric marks, DAX measure counts, formula operators, or performance-band ranges without a traceable review decision.

## Chunking Strategy

Primary strategy:

```text
Document -> Section -> Subsection -> coherent chunk
```

Do not blindly split every document into fixed-size character blocks.

A chunk should normally represent one coherent requirement, task, expected outcome, deliverable, rubric criterion, concept, method, teaching topic, or table with its explanatory context.

### Project Brief Chunking

Use the Project Brief as the only `OFFICIAL_REQUIREMENT` source.

Recommended chunks:

- `Business Scenario`
- `Project Objective`
- `Business Requirements`
- `Dataset Provided`
- `Success Factors`
- `Task 1: Transform and Clean Data Using Power Query`
- `Task 2: Create Data Models, Relationships and Hierarchies`
- `Task 3: Generate Informative Reports`
- `Task 4: Develop an Interactive Dashboard`
- `Task 5: Showcase Key Metrics and Trends`
- `Deliverables: Power BI .pbix file`
- `Deliverables: Business Insights Summary`
- one rubric chunk per assessment area/task row.

Prevent task mixing:

- Task boundaries start at `Task N:` and end before the next `Task N:` or the next major heading.
- Each task chunk keeps only its own requirements and expected outcome.
- Shared context such as business requirements remains in a separate Brief chunk.

### IU Chunking

Use IU PDFs only as `LEARNING_MATERIAL`.

Rules:

- Split first by numbered section headings.
- Split large numbered sections by subheading.
- Split still-large subsections by coherent concept or procedure.
- Keep examples close to the concept they explain unless they exceed fallback size.
- Keep source code/formula examples with the DAX concept they demonstrate.
- Keep tables with the paragraph that introduces them if compact; otherwise create a dedicated table chunk with the parent heading repeated.

Examples of intended IU chunks:

- `What is Data Analytics?`
- `Data storytelling`
- `Types of analytics`
- `Roles in Data`
- `Tasks Of Data Analyst`
- `Star schemas`
- `Fact tables`
- `Dimension tables`
- `Compare fact and dimension tables`
- `Relate star schema tables`
- `Many-to-one or one-to-many relationship`
- `Calculated columns`
- `Measures`
- `Create simple measures`
- `DISTINCTCOUNT function`
- `Apply filters with slicers`
- `Visual interactions`
- `Categorical visuals`
- `Time series visuals`

## Recommended Token-Size and Overlap Fallback

Size limits are fallback controls, not the main segmentation method.

| Setting | Recommendation |
|---|---|
| Target chunk size | 450-850 tokens |
| Soft maximum | 1,000 tokens |
| Hard maximum | 1,200 tokens |
| Overlap when size-splitting only | 80-120 tokens |
| Minimum useful chunk | About 100-150 tokens unless it is a precise requirement/rubric row |

Overlap should not be used when splitting cleanly by heading, task, rubric row, or table row. Instead, prepend compact context inside the chunk text, for example:

```text
Document: IU2_2
Section: Star schema design
Subsection: Fact tables
```

If a section is too large:

1. Split by subheading.
2. If still too large, split by paragraph groups or list groups.
3. Repeat parent section/subsection title in every child chunk.
4. Use overlap only if a paragraph group must be split mid-topic.

If a section is very small:

- Combine with adjacent content only within the same document, section, role, and topic.
- Never combine separate tasks, separate rubric rows, Project Brief text with IU text, or Learner Guide text with either requirement or IU chunks.

## Metadata Schema

Metadata must be generic. DMV-specific values such as `Task 2` or `IU3_1` are data values, not application logic branches.

| Field | Required | Type | Purpose | Value source | Filtering/reranking use | Citation use |
|---|---:|---|---|---|---|---|
| `module_id` | Yes | string | Identifies module. | Source registry or document cover, e.g. `PDDS-DMV`. | Filter by module. | Optional. |
| `level` | Yes | string | Identifies learner level/scope. | Source registry, e.g. `Basic`. | Filter by level. | Optional. |
| `document_id` | Yes | string | Stable logical document key. | Source registry, e.g. `dmv_basic_project_brief`, `iu2_2`. | Filter/debug/rerank by document. | Optional. |
| `document_type` | Yes | string | Generic document kind. | Source registry, e.g. `project_brief`, `instructional_unit`, `learner_guide`. | Rerank/filter by type. | Optional. |
| `knowledge_role` | Yes | enum | Preserves authority role. | Source registry. Values: `OFFICIAL_REQUIREMENT`, `LEARNING_MATERIAL`, `MODULE_GUIDANCE`. | Important for authority-aware reranking. | Optional. |
| `section_title` | Yes | string | Nearest section title for context. | Extracted heading or generated from page/section. | Rerank and display. | Yes. |
| `topic` | No | string/null | Concise topic label. | Extracted heading/subheading or generic topic inference during preparation. | Useful for reranking and diagnostics. | Optional. |
| `task_reference` | No | string/null | Links chunks to assessment task when present. | Extracted from Brief headings such as `Task 2`. | Filter/rerank for task questions. | Yes when present. |
| `instructional_unit` | No | string/null | IU identifier for learning-material chunks. | Source registry, e.g. `IU3_1`. | Filter/rerank for IU-specific retrieval. | Optional. |
| `source_file` | Yes | string | Traceability to source file. | Source registry path. | Debug/filter. | Yes. |
| `page_start` | Yes | integer | Citation start page. | Physical PDF page. | Debug. | Yes. |
| `page_end` | Yes | integer | Citation end page. | Physical PDF page. | Debug. | Yes. |
| `status` | Yes | enum/string | Preparation quality/status. | Ingestion pipeline. Suggested: `ready`, `needs_review`, `low_text`, `table_reconstructed`. | Filter out or review risky chunks. | No, unless useful internally. |

Optional implementation-only fields may include `chunk_id`, `chunk_index`, `parent_section_id`, `rubric_criterion`, `marks`, and `table_id`. These are not mandatory for all chunks but are useful for debugging and rubric reconstruction.

## Authority Handling

Every stored chunk must have exactly one role:

| Role | Source |
|---|---|
| `OFFICIAL_REQUIREMENT` | `DMV-Project_Brief_Basic-v1-formatted.pdf` only |
| `LEARNING_MATERIAL` | `IU1_1.pdf`, `IU1_2.pdf`, `IU1_3.pdf`, `IU2_1.pdf`, `IU2_2.pdf`, `IU3_1.pdf`, `IU4_1.pdf` |
| `MODULE_GUIDANCE` | `Learner_Guide_PDDS_DMV_v4.pdf` only |

Authority rules:

- `OFFICIAL_REQUIREMENT` is authoritative for assessment tasks, deliverables, rubric expectations, marks, and what learners must do.
- `LEARNING_MATERIAL` is authoritative for taught concepts and explanations within the IU materials.
- `MODULE_GUIDANCE` is authoritative for general module/course guidance contained in the Learner Guide.

The later retrieval layer should be able to prefer `OFFICIAL_REQUIREMENT` for questions about what is required, what is assessed, what must be submitted, expected outcomes, Foundation / Proficient expectations, and marks/weighting.

The later retrieval layer should be able to use `LEARNING_MATERIAL` for explaining terms, teaching concepts, giving method guidance, and simplifying Power BI ideas.

The later retrieval layer should be able to use `MODULE_GUIDANCE` for module overview, learning outcomes, delivery model, learning resources, learner support, assessment eligibility, grading, and lesson-plan guidance.

If content overlaps or conflicts, general module guidance or IU material must not override an explicit Project Brief assessment requirement.

This document does not implement retrieval ranking.

## Project Brief and Rubric Handling

The Project Brief requires special handling because it contains both requirements and rubric tables.

### Requirements and Tasks

Each Task 1-5 chunk should contain:

- task title;
- required actions;
- expected outcome;
- page range;
- `task_reference`.

Do not let one task absorb bullets from the next task. The parser should use explicit `Task N:` headings as hard boundaries.

### Deliverables

Split deliverables into two chunks:

- `.pbix file` expectations;
- Business Insights Summary expectations.

This supports questions such as "What do I need to submit?" without retrieving unrelated task instructions.

### Rubric Tables

Observed rubric structure:

- page 7 begins the rubric with columns for assessment area, task reference, Failed, Foundation, Proficient, marks;
- page 8 continues the same rubric;
- extracted tables have split headers such as `Proficient (75-` and `100%)`;
- row text can span multiple visual lines.

Rubric reconstruction rules:

1. Detect the `MARKING RUBRICS` section.
2. Merge page 7 and page 8 into one logical rubric table.
3. Normalize headers into `assessment_area`, `task_reference`, `failed_expectation`, `foundation_expectation`, `proficient_expectation`, and `marks`.
4. Create one chunk per assessment area/task row.
5. In each chunk, repeat the task reference and assessment area.
6. Keep Failed, Foundation, Proficient, and Marks together.
7. Do not create standalone chunks from individual cells.
8. Preserve the final `Total 100` row as rubric summary metadata or a compact summary chunk, not as an orphaned assessment criterion.
9. Validate numeric ranges and counts that text extraction may corrupt, such as `1-2`, `3-5`, `75-100%`, and formula operators.

This prevents rubric cells losing context, performance bands detaching from the assessment area/task, marks becoming meaningless standalone chunks, and questions like "What is expected for Proficient in Task 2?" retrieving only a fragment.

## Large IU Handling

The IU documents are large but retained whole. Retrieval friendliness comes from segmentation and metadata, not manual deletion.

### `IU1_1.pdf`

Prepare chunks by introduction to data analytics; business uses of data analytics; retail data examples; data storytelling and data culture; who a data analyst is; analytics types: descriptive, diagnostic, predictive, prescriptive, and cognitive; roles in data: business analyst, data analyst, data engineer, data scientist, and database administrator; and tasks of a data analyst: Prepare, Model, Visualize, Analyze, and Manage.

The `Tasks Of Data Analyst` section should not become one large page 11-15 chunk. Split it into separate task chunks so questions such as "Why is data cleaning important?", "What does modeling mean?", or "What does a data analyst manage in Power BI?" retrieve the precise task explanation.

### `IU1_2.pdf`

Prepare chunks by introduction to Power BI; Desktop / Service / Mobile distinctions; common Power BI workflow; building blocks: visualizations, semantic models, reports, dashboards, tiles; Power BI Desktop: connect, transform, create visuals, create reports, share reports; Power BI Service; Desktop vs Service; apps/app marketplace sections as their own clearly titled chunks.

### `IU1_3.pdf`

Prepare chunks by getting data overview; getting data from files; local/cloud file location concepts; file connection and Navigator; Load vs Transform Data; change source file/settings; relational data source sections; SQL query sections; online services sections.

### `IU2_1.pdf`

Prepare chunks by clean/transform/load overview; Power Query Editor; headers; rename columns; remove rows/columns; pivot/unpivot; replace values; null handling; duplicate removal; naming conventions; data type evaluation/change; append/merge queries; profiling data, column quality, column distribution, column profile.

### `IU2_2.pdf`

Prepare chunks by modelling overview; primary/foreign keys; star schemas; fact tables; dimension tables; fact/dimension comparison table; relating star schema tables; model relationships/table properties; date table creation; dimensions and hierarchies; granularity; relationship types; one-to-many/many-to-one; cross-filter direction; many-to-many.

For a learner question like "What is a star schema?", the chunk title/topic should be `Star schemas` or `Star schema design`, not a broad 41-page IU2_2 chunk. Metadata should include `document_id: iu2_2`, `section_title: Star schema design`, and `topic: Star Schema`.

### `IU3_1.pdf`

Prepare chunks by DAX calculation types; calculated tables; calculated columns; measures; DAX formula structure; table/column/measure references; data types and BLANK; operator tables; DAX functions; variables; implicit and explicit measures; simple measures; compound/quick measures; calculated columns vs measures.

### `IU4_1.pdf`

Prepare chunks by report design requirements; audience; report types; UI requirements; UX requirements; Power BI report structure; analytical layout; visual design principles; report objects; visual selection by family: categorical, time series, proportional, numeric, grid, performance, geospatial; visual formatting; KPIs; report filters; slicers; visual interactions; drillthrough/tooltips/bookmarks/query reduction as separately titled chunks.

## Learner Guide Handling

Use the Learner Guide only as `MODULE_GUIDANCE`.

Recommended chunks:

- cover/module identity and delivery-mode information from page 1;
- revision history from page 3 if needed for source version traceability;
- `Module Brief` from page 4;
- `Learners Profile` from page 4;
- `Learning Outcomes & Targeted Job Roles` from pages 4-5;
- `Technical Skills and Competencies` from pages 5-6;
- `Learning Design` overview and activity-duration table from page 6;
- separate chunks for `5.1 E-learning`, `5.2 Flipped Class`, `5.3 Assignments`, Project Mentoring, Project Implementation, and `5.6 Summative Assessment`;
- `Assessments`, split into formative assessments, project report, project presentation, and oral questioning;
- `Grading`, split into assignment grading and summative assessment grading;
- `Learning Resources`, `Recommended Readings`, `Class Size`, and `Faculty Background`;
- `Lesson Plan`, split by session group / instructional-unit cluster instead of one broad page 13-21 chunk;
- Advanced-level notes on page 21 as an excluded-from-Basic retrieval risk or a low-priority guidance chunk tagged clearly as Advanced-level content.

The Learner Guide includes broad module/project language and lesson-plan references to assignments, project reports, auto-grading, and Advanced-level activities. These chunks can support general module navigation questions, but they must not be used to change Basic V1 Project Brief requirements, deliverables, marks, or rubric expectations.

## Image-Heavy / Low-Text Pages

Some IU pages and the Project Brief rubric pages contain screenshots, diagrams, or table layouts where extraction may be incomplete or fragmented.

Preparation rules:

- Detect pages with very low text density but large image area.
- If the page belongs to a critical section, mark affected chunks `status: needs_review`.
- Do not use OCR or image interpretation in this design step unless implementation later explicitly chooses it.
- Do not silently drop a critical page. Emit a review note or low-text placeholder with page citation if needed.

## Example Prepared Chunks

These are representative prepared chunks using actual source structure. They are not embedding records and are not generated files.

### 1. Task Requirement Chunk from the Brief

```text
chunk_text:
Section: PROJECT TASKS
Task 2: Create Data Models, Relationships and Hierarchies

Create a basic data model using Power BI. The learner is required to create a Sales fact table; create Product, Store, and Date dimension tables; establish one-to-many relationships between fact and dimension tables; configure appropriate relationship cardinality; create a Product hierarchy from Category to Product; create a Date hierarchy from Year to Quarter to Month to Date; and organize the model clearly and logically.

Expected outcome: A functional basic star-schema data model that allows users to analyze sales across products, stores, regions, and time.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: dmv_basic_project_brief
document_type: project_brief
knowledge_role: OFFICIAL_REQUIREMENT
section_title: PROJECT TASKS
topic: Data Model Requirements
task_reference: Task 2
instructional_unit: null
source_file: knowledge_base/brief/DMV-Project_Brief_Basic-v1-formatted.pdf
page_start: 4
page_end: 4
status: ready
```

### 2. Rubric Chunk from the Brief

```text
chunk_text:
Section: MARKING RUBRICS
Assessment Area: Data Modelling
Task Reference: Task 2: Create Data Models
Marks: 15

| Performance band | Expectation |
|---|---|
| Failed (0-49%) | Relationships are missing or incorrect, for example many-to-many; no star schema structure; hierarchies not created. |
| Foundation (50-74%) | Basic star schema created; relationships functional but cardinality may be poorly configured; basic hierarchies implemented. |
| Proficient (75-100%) | Robust star-schema; correct one-to-many relationships; fully functional Product and Date hierarchies. |

metadata:
module_id: PDDS-DMV
level: Basic
document_id: dmv_basic_project_brief
document_type: project_brief
knowledge_role: OFFICIAL_REQUIREMENT
section_title: MARKING RUBRICS
topic: Data Modelling Rubric
task_reference: Task 2
instructional_unit: null
source_file: knowledge_base/brief/DMV-Project_Brief_Basic-v1-formatted.pdf
page_start: 7
page_end: 7
status: table_reconstructed
```

### 3. DAX Requirement Chunk from the Brief

```text
chunk_text:
Section: PROJECT TASKS
Task 5: Showcase Key Metrics and Trends

Create 3-5 basic DAX measures to support business analysis. Example measures include Total Sales, Total Quantity, Average Sales, Number of Transactions, and Total Profit. Learners may create a simple calculated column such as Profit = Sales Amount - Cost Amount. DAX should primarily use basic functions such as SUM, AVERAGE, COUNT, and DISTINCTCOUNT. No advanced time-intelligence calculations are required.

Expected outcome: A set of accurate key metrics that clearly communicate the company's sales performance.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: dmv_basic_project_brief
document_type: project_brief
knowledge_role: OFFICIAL_REQUIREMENT
section_title: PROJECT TASKS
topic: DAX Requirements
task_reference: Task 5
instructional_unit: null
source_file: knowledge_base/brief/DMV-Project_Brief_Basic-v1-formatted.pdf
page_start: 5
page_end: 6
status: ready
```

Note: the raw text extraction observed from the PDF renders `3-5` as `35` and drops the minus sign in the Profit formula. The prepared chunk should use the verified source meaning after layout review, and the ingestion log should record that a critical extraction artifact was corrected.

### 4. Star-Schema IU Chunk

```text
chunk_text:
Section: Data Modelling with Power BI
Subsection: Star schemas

A star schema simplifies a model by classifying tables as either dimension tables or fact tables. Fact tables store events or observations, such as sales orders, quantities, and transaction dates. Dimension tables describe business entities, such as products or locations, and provide fields used for filtering and grouping. In the model, dimension tables relate to fact tables using one-to-many relationships.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: iu2_2
document_type: instructional_unit
knowledge_role: LEARNING_MATERIAL
section_title: Star schema design
topic: Star Schema
task_reference: null
instructional_unit: IU2_2
source_file: knowledge_base/learning_materials/IU2_2.pdf
page_start: 6
page_end: 8
status: ready
```

### 5. DAX IU Chunk

```text
chunk_text:
Section: Data Modelling with DAX
Subsection: Create simple measures

A measure formula must return a scalar or single value. Measures do not store values in the model; they are used at query time to return summarizations of model data. A simple measure aggregates values from a single column or table, such as Revenue = SUM(Sales[Sales Amount]), Quantity = SUM(Sales[Order Quantity]), or Order Count = DISTINCTCOUNT('Sales Order'[Sales Order]).

metadata:
module_id: PDDS-DMV
level: Basic
document_id: iu3_1
document_type: instructional_unit
knowledge_role: LEARNING_MATERIAL
section_title: Create simple measures
topic: Simple DAX Measures
task_reference: null
instructional_unit: IU3_1
source_file: knowledge_base/learning_materials/IU3_1.pdf
page_start: 25
page_end: 27
status: ready
```

### 6. Reporting/Dashboard IU Chunk

```text
chunk_text:
Section: Power BI Formatting, Reports and Dashboards
Subsection: Apply filters with slicers

A slicer is a core visual whose purpose is to filter other visuals. By default, slicers filter visuals on the same report page. A slicer can use one or more fields from the same table or a hierarchy. Slicer layouts depend on the data type: text fields can use list or dropdown layouts, numeric fields can use list, dropdown, between, less than or equal to, or greater than or equal to layouts, and date fields can use date-oriented layouts.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: iu4_1
document_type: instructional_unit
knowledge_role: LEARNING_MATERIAL
section_title: Power BI Formatting, Reports and Dashboards
topic: Slicers
task_reference: null
instructional_unit: IU4_1
source_file: knowledge_base/learning_materials/IU4_1.pdf
page_start: 55
page_end: 58
status: ready
```

### 7. Data Analytics IU Chunk

```text
chunk_text:
Section: Introduction to Data Analytics
Subsection: What is Data Analytics?

Data analytics is the process of collecting, cleaning, analyzing, and presenting data to gain insights that can improve business decisions. The IU explains that analytics can help answer business questions about customer buying habits, effective marketing channels, conversion rates, business risks, and operational efficiency. It also introduces the need to tell a story with data so business decision makers can act on accurate information.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: iu1_1
document_type: instructional_unit
knowledge_role: LEARNING_MATERIAL
section_title: What is Data Analytics?
topic: Data Analytics Concepts
task_reference: null
instructional_unit: IU1_1
source_file: knowledge_base/learning_materials/IU1_1.pdf
page_start: 1
page_end: 3
status: ready
```

### 8. Learner Guide Chunk

```text
chunk_text:
Section: 1. Module Brief

The Data Modelling & Visualization module covers the end-to-end Power BI analytics workflow across five instructional units. Learners connect to and profile data sources, clean and transform data using Power Query, build data models with relationships and star schemas, write DAX measures and calculated columns, and design formatted reports and interactive dashboards for business reporting. Learners work hands-on with Power BI Desktop, Power BI Service, Power Query, and DAX.

metadata:
module_id: PDDS-DMV
level: Basic
document_id: dmv_learner_guide
document_type: learner_guide
knowledge_role: MODULE_GUIDANCE
section_title: Module Brief
topic: Module Overview
task_reference: null
instructional_unit: null
source_file: knowledge_base/module_guide/Learner_Guide_PDDS_DMV_v4.pdf
page_start: 4
page_end: 4
status: ready
```

## Replicability

This design should later support DMV Advanced, another module, different assessment structures, different IU structures, and modules without Task 1-5 naming because:

- source selection lives in a source registry, not ingestion logic;
- document roles are generic: `OFFICIAL_REQUIREMENT`, `LEARNING_MATERIAL`, and `MODULE_GUIDANCE`;
- headings, sections, tables, and pages are detected structurally;
- `task_reference` is optional and extracted only when present;
- IU identifiers are metadata values, not code branches;
- topic names are extracted/assigned as data, not hard-coded Python keyword maps;
- rubric handling is based on generic rubric/table structure, not DMV-specific row names.

For another module, update the source registry and metadata defaults, then reuse the same extraction and chunking pipeline.

## Risks and Open Decisions

1. Rubric extraction from the Brief is table-fragment prone and must be tested carefully before ingestion.
2. The Brief displays repeated `Page | 1`; citation should use physical PDF page numbers, not displayed page text.
3. Some extracted text contains encoding artifacts from PDF fonts. A light normalization layer may be needed, but source meaning must not be changed.
4. IU screenshot-heavy pages may lose information in text extraction. Critical low-text chunks should be marked `needs_review`.
5. Keeping whole IU documents means advanced/peripheral IU chunks will exist in the corpus. Retrieval ranking/filtering must later use metadata and query intent to avoid noisy matches.
6. Table chunks need deterministic reconstruction; isolated cells must never be stored as independent chunks.
7. The exact final `topic` assignment approach remains an implementation decision: it can come from headings, subheadings, or a controlled generic preparation config, but not from DMV-specific application logic.
8. Assessment-critical source values can be corrupted during extraction, as observed with `3-5` and the Profit formula. The ingestion implementation needs a validation/review path for these fields.
9. The Learner Guide contains Advanced-level notes and general assignment/project guidance. These must be tagged clearly and must not override Basic Project Brief requirements.
10. The Learner Guide mentions AI Mentor support and auto-grading in places, while the current chatbot is a learning mentor, not an Auto Grader. Generation rules later need to keep that product boundary clear.

## Final Design Report

1. Selected nine files confirmed: one Project Brief as `OFFICIAL_REQUIREMENT`, seven IU PDFs as `LEARNING_MATERIAL`, and one Learner Guide as `MODULE_GUIDANCE`.
2. Extraction strategy: layout-aware page extraction, table candidate extraction, heading inference, repeated header/footer removal, page traceability, low-text/image-heavy status marking.
3. Chunking strategy: semantic hierarchy first, with separate chunks for Brief sections/tasks/deliverables/rubric rows and IU concepts/subsections.
4. Token-size fallback: target 450-850 tokens, soft max 1,000, hard max 1,200, overlap 80-120 tokens only when size-splitting is unavoidable.
5. Metadata schema: minimal generic fields for module, level, document, role, section, topic, task/IU reference, source file, pages, and status. It supports `document_type: learner_guide`, `knowledge_role: MODULE_GUIDANCE`, and `instructional_unit: IU1_1`.
6. Project Brief/rubric handling: split requirements by task, split deliverables by deliverable type, reconstruct rubric rows with assessment area, task, bands, and marks together.
7. Large-IU and guidance handling: keep all seven IU PDFs and the Learner Guide whole as sources, but chunk by numbered heading, subheading, concept, table, procedure, module-information section, and lesson-plan group with precise metadata.
8. Example chunks: examples above cover one task requirement, one rubric row, one DAX requirement, one star-schema IU chunk, one DAX IU chunk, one reporting/dashboard IU chunk, one `IU1_1` chunk, and one Learner Guide chunk.
9. Risks/open decisions: table reconstruction, PDF artifacts, image-heavy pages, peripheral IU noise, Learner Guide Advanced-level noise, citation page policy, and final topic assignment mechanics.
