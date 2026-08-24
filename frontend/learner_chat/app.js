const conversation = document.getElementById("conversation");
const emptyState = document.getElementById("emptyState");
const form = document.getElementById("chatForm");
const input = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const errorBox = document.getElementById("error");
const chatView = document.getElementById("chatView");
const evaluationView = document.getElementById("evaluationView");
const evaluationRoot = document.getElementById("evaluationRoot");
const capabilitiesView = document.getElementById("capabilitiesView");
const capabilitiesRoot = document.getElementById("capabilitiesRoot");
const adminView = document.getElementById("adminView");
const adminRoot = document.getElementById("adminRoot");
const navTabs = document.querySelectorAll(".nav-tab");

const state = {
  conversationId: crypto.randomUUID(),
  loading: false,
  history: [],
  moduleId: "PDDS-DMV",
  level: "Basic",
  evaluationLoaded: false,
  capabilitiesLoaded: false,
  adminLoaded: false,
  admin: {
    metadata: null,
    modules: [],
    selectedModule: null,
    versions: [],
    selectedVersion: null,
    documents: [],
    preparationJobs: [],
    publishJobs: [],
    chunks: [],
    warnings: [],
    reviewSummary: null,
    chunkFilter: "all",
    documentFilter: "",
    roleFilter: "",
    selectedChunks: new Set(),
    loading: false,
    message: "",
    error: "",
  },
  evaluationSummary: null,
  evaluationTests: [],
  selectedTest: null,
};

const capabilitySections = [
  {
    title: "Assessment requirements",
    text: "Helps learners understand official assessment tasks and requirements.",
    examples: ["Explain Task 1 to me.", "What do I need to do for Task 2?", "How many DAX measures do I need?"],
  },
  {
    title: "Rubric and performance expectations",
    text: "Explains assessment criteria and performance expectations without assigning grades. If the task or assessment area is missing, the Mentor should ask for clarification.",
    examples: ["Explain the Task 2 rubric.", "What is expected for Proficient in Task 2?"],
  },
  {
    title: "Course concepts",
    text: "Explains concepts using approved instructional-unit learning materials.",
    examples: ["What is cardinality?", "What is a star schema?", "What is DAX?", "What is a slicer?"],
  },
  {
    title: "Practical Power BI activities",
    text: "Helps learners understand how taught Power BI activities work.",
    examples: ["Where is the Transform Data button?", "How do I remove duplicates in Power Query?", "How do I import an Excel file into Power BI?"],
  },
  {
    title: "Simpler explanations",
    text: "Re-explains difficult ideas in simpler learner-friendly language.",
    examples: ["I still don't understand measures. Explain with a simple example."],
  },
  {
    title: "Draft review",
    text: "Reviews learner-authored work against approved requirements and learning materials, identifying strengths, gaps, and improvements. Draft review does not mean Auto Grading.",
    examples: ["Here is my Task 2 answer. Can you review it?", "What am I missing from this answer?", "How can I improve this draft?"],
  },
  {
    title: "Improvement guidance",
    text: "Suggests what a learner should strengthen next without rewriting the whole assessed submission.",
    examples: ["What should I improve in this answer?"],
  },
  {
    title: "Module guidance",
    text: "Answers general module questions using the approved Learner Guide.",
    examples: ["What is this module about?", "What are the learning outcomes?", "What learning resources are available?"],
  },
  {
    title: "General Module Questions",
    text: "Helps learners find general information about the programme, faculty, and module from approved module materials.",
    examples: ["Who is the programme manager?", "What are the faculty backgrounds?", "Who are the faculty members?"],
  },
  {
    title: "Learner-facing sources",
    text: "Shows readable references to the approved Project Brief, IU materials, or Learner Guide used in the answer.",
    examples: [],
  },
  {
    title: "Unsupported questions",
    text: "Does not invent answers when approved module knowledge does not support the question. It should return a controlled insufficient-evidence response rather than unrelated DMV content.",
    examples: ["Do you know Suga from the South Korean boy band BTS?"],
  },
  {
    title: "Academic integrity and grading boundaries",
    text: "Supports learning without writing complete assessed submissions or predicting grades. Refusals still offer legitimate learning guidance.",
    examples: ["Write my assignment so I can copy and submit it.", "Can you grade my Task 2 at 85%?"],
  },
];

const sampleDraft = `I created a Sales table with Product, Store and Date tables. I connected the tables and created Product and Date hierarchies. Can you review this and tell me what is missing?`;

function setLoading(value) {
  state.loading = value;
  sendButton.disabled = value || input.value.trim().length === 0;
  input.disabled = value;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function updateSendState() {
  sendButton.disabled = state.loading || input.value.trim().length === 0;
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function scrollToLatest() {
  conversation.scrollTop = conversation.scrollHeight;
}

function hideEmptyState() {
  if (emptyState) {
    emptyState.remove();
  }
}

function addMessage(role, content, sources = []) {
  hideEmptyState();
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "mentor") {
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.textContent = content;
  }
  wrapper.appendChild(bubble);

  if (role === "mentor" && sources.length > 0) {
    const sourcesBox = document.createElement("div");
    sourcesBox.className = "sources";
    const title = document.createElement("div");
    title.className = "sources-title";
    title.textContent = "Sources";
    const list = document.createElement("ul");
    sources.forEach((source) => {
      const item = document.createElement("li");
      item.textContent = source;
      list.appendChild(item);
    });
    sourcesBox.appendChild(title);
    sourcesBox.appendChild(list);
    wrapper.appendChild(sourcesBox);
  }

  conversation.appendChild(wrapper);
  scrollToLatest();
  return wrapper;
}

function addLoadingMessage() {
  const wrapper = addMessage("mentor", "Thinking...");
  wrapper.classList.add("loading");
  return wrapper;
}

function updateHistory(learnerMessage, mentorAnswer) {
  state.history.push({ role: "learner", content: learnerMessage });
  state.history.push({ role: "mentor", content: mentorAnswer });
  state.history = state.history.slice(-8);
}

async function sendMessage(message) {
  clearError();
  addMessage("learner", message);
  const loadingMessage = addLoadingMessage();
  setLoading(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        module_id: state.moduleId,
        level: state.level,
        conversation_id: state.conversationId,
        history: state.history,
      }),
    });

    if (!response.ok) {
      throw new Error("The AI Mentor could not answer right now. Please try again.");
    }

    const data = await response.json();
    state.conversationId = data.conversation_id || state.conversationId;
    loadingMessage.remove();
    addMessage("mentor", data.answer, data.sources || []);
    updateHistory(message, data.answer);
  } catch (error) {
    loadingMessage.remove();
    showError(error.message || "Something went wrong. Please try again.");
  } finally {
    setLoading(false);
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || state.loading) {
    return;
  }
  input.value = "";
  autoResize();
  updateSendState();
  sendMessage(message);
});

input.addEventListener("input", () => {
  autoResize();
  updateSendState();
  clearError();
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".example-question").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.textContent.trim();
    autoResize();
    updateSendState();
    input.focus();
  });
});

updateSendState();

navTabs.forEach((tab) => {
  tab.addEventListener("click", () => switchView(tab.dataset.view));
});

function switchView(view) {
  navTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  chatView.hidden = view !== "chat";
  chatView.classList.toggle("active-view", view === "chat");
  evaluationView.hidden = view !== "evaluation";
  evaluationView.classList.toggle("active-view", view === "evaluation");
  capabilitiesView.hidden = view !== "capabilities";
  capabilitiesView.classList.toggle("active-view", view === "capabilities");
  adminView.hidden = view !== "admin";
  adminView.classList.toggle("active-view", view === "admin");
  if (view === "evaluation" && !state.evaluationLoaded) {
    loadEvaluation();
  }
  if (view === "capabilities" && !state.capabilitiesLoaded) {
    renderCapabilities();
  }
  if (view === "admin" && !state.adminLoaded) {
    loadAdmin();
  }
}

function renderCapabilities() {
  capabilitiesRoot.innerHTML = `
    <section class="capability-hero panel">
      <h2>AI Mentor Capabilities</h2>
      <p>AI Mentor is a course-grounded learning assistant. It uses approved module documents to explain requirements, teach concepts, answer practical questions, and review learner-authored work. It provides guidance rather than grades or complete assessed submissions.</p>
      <p class="muted">Capabilities shown here are based on the current DMV Basic V1 evaluation.</p>
    </section>

    <section class="capability-grid">
      ${capabilitySections.map(capabilityCard).join("")}
    </section>

    <section class="panel">
      <h3>Sample Draft Review</h3>
      <p class="muted">This example will prefill the chat input but will not send automatically.</p>
      <details class="sample-draft" open>
        <summary>View sample learner draft</summary>
        <div class="detail-box preserve">${escapeHtml(sampleDraft)}</div>
        <button type="button" class="try-chat" data-example="${escapeAttribute(sampleDraft)}">Try in Chat</button>
      </details>
    </section>

    <section class="panel boundary-panel">
      <h3>What AI Mentor Does Not Do</h3>
      <div class="boundary-grid">
        ${[
          "Does not assign percentage grades or marks.",
          "Does not guarantee PASS / Foundation / Proficient outcomes.",
          "Does not act as the company's Auto Grader.",
          "Does not write complete assessed assignments for copy-and-submit.",
          "Does not invent unsupported course information.",
          "Does not replace lecturer judgment.",
        ].map((item) => `<div class="boundary-item">${escapeHtml(item)}</div>`).join("")}
      </div>
    </section>
  `;
  capabilitiesRoot.querySelectorAll(".try-chat").forEach((button) => {
    button.addEventListener("click", () => prefillChat(button.dataset.example || ""));
  });
  state.capabilitiesLoaded = true;
}

function capabilityCard(section) {
  return `<article class="capability-card panel">
    <h3>${escapeHtml(section.title)}</h3>
    <p>${escapeHtml(section.text)}</p>
    ${section.examples.length ? `<div class="capability-examples">
      <h4>Example learner questions</h4>
      ${section.examples.map((example) => `<div class="capability-example"><span>${escapeHtml(example)}</span><button type="button" class="try-chat" data-example="${escapeAttribute(example)}">Try in Chat</button></div>`).join("")}
    </div>` : `<p class="muted">Sources are shown after answers; no chat example needed for this capability.</p>`}
  </article>`;
}

function prefillChat(example) {
  switchView("chat");
  input.value = example;
  autoResize();
  updateSendState();
  input.focus();
}

async function loadEvaluation() {
  evaluationRoot.innerHTML = `<div class="panel"><p>Loading evaluation results...</p></div>`;
  try {
    const [summaryResponse, testsResponse] = await Promise.all([
      fetch("/api/evaluation/summary"),
      fetch("/api/evaluation/tests"),
    ]);
    if (!summaryResponse.ok || !testsResponse.ok) {
      throw new Error("Could not load evaluation artifacts.");
    }
    state.evaluationSummary = await summaryResponse.json();
    const testsData = await testsResponse.json();
    state.evaluationTests = testsData.tests || [];
    state.evaluationLoaded = true;
    renderEvaluation();
  } catch (error) {
    evaluationRoot.innerHTML = `<div class="error">Could not load evaluation results. ${escapeHtml(error.message || "")}</div>`;
  }
}

function renderEvaluation() {
  const demo = state.evaluationSummary.demo_summary || {};
  const finalSummary = demo.final_v3_results || state.evaluationSummary.final_summary || {};
  const prep = demo.knowledge_preparation_metrics || {};
  const retrieval = demo.retrieval_experiment_comparison || {};
  const response = demo.response_experiment_results?.summary || {};
  const draft = demo.draft_review_results || {};
  const human = state.evaluationSummary.human_review_summary || {};
  const limitations = demo.known_limitations || [];
  const examples = demo.representative_successful_test_examples || [];

  evaluationRoot.innerHTML = `
    <section class="eval-hero panel">
      <div>
        <p class="eyebrow">DMV Basic</p>
        <h2>Learner V1 Evaluation</h2>
        <p>Learner V1 is frozen for this evaluation baseline. This page shows automated results, review cases, and a separate human-review trail.</p>
        <p class="review-note"><strong>REVIEW does not mean failure.</strong> It means automated checks could not safely determine natural-language answer quality and the case requires human judgment.</p>
      </div>
      <div class="status-card">Learner V1 Status<br><strong>Frozen Baseline</strong></div>
    </section>

    <section class="metric-grid">
      ${metricCard("Source documents", prep.source_documents)}
      ${metricCard("Prepared chunks", prep.prepared_chunks)}
      ${metricCard("Embedding eligible", prep.embedding_eligible)}
      ${metricCard("Embedding ineligible", prep.embedding_ineligible)}
    </section>

    <section class="panel">
      <h3>Final V3 Results</h3>
      <p class="muted">No pass rate is shown because REVIEW and expected NO_CONTEXT are not failures.</p>
      <div class="metric-grid compact">
        ${metricCard("Total tests", finalSummary.total_tests)}
        ${metricCard("PASS", finalSummary.status_counts?.PASS || 0, "pass")}
        ${metricCard("REVIEW", finalSummary.status_counts?.REVIEW || 0, "review")}
        ${metricCard("FAIL", finalSummary.status_counts?.FAIL || 0, "fail")}
        ${metricCard("NO_CONTEXT", finalSummary.status_counts?.NO_CONTEXT || 0, "no-context")}
      </div>
      <div class="definition-row">
        <span><strong>PASS</strong> deterministic checks confirmed behavior</span>
        <span><strong>REVIEW</strong> human judgment required</span>
        <span><strong>FAIL</strong> deterministic violation</span>
        <span><strong>NO_CONTEXT</strong> expected controlled unsupported response</span>
      </div>
    </section>

    <section class="panel">
      <h3>Retrieval Progression</h3>
      <p class="muted">Retrieval evaluation checks whether the system finds the correct course evidence before generating an answer.</p>
      <div class="experiment-grid">${Object.entries(retrieval).map(([name, values]) => experimentCard(name, values)).join("")}</div>
    </section>

    <section class="panel">
      <h3>Focused Response and Draft Review</h3>
      <div class="metric-grid compact">
        ${metricCard("Groundedness", `${response.groundedness?.PASS || 0}/21 PASS`)}
        ${metricCard("Correctness", `${response.correctness?.PASS || 0}/21 PASS`)}
        ${metricCard("Academic integrity", `${response.academic_integrity_behavior?.PASS || 0}/21 PASS`)}
        ${metricCard("Citation quality", `${response.source_citation_quality?.PASS || 0}/21 PASS`)}
        ${metricCard("Unsupported claims", response.unsupported_claim_cases || 0)}
        ${metricCard("Draft focused tests", draft.total || 0)}
        ${metricCard("Draft PASS", draft.status_counts?.PASS || 0, "pass")}
        ${metricCard("Final V3 draft PASS", finalSummary.by_category?.["Draft Review"]?.PASS || 0, "pass")}
      </div>
      <p class="muted">These focused tests evaluate whether good retrieved evidence is turned into correct, grounded learner-facing answers, and whether draft review identifies strengths, gaps, and improvements without grading or replacement submissions.</p>
    </section>

    <section class="panel">
      <h3>Human Review Progress</h3>
      <div class="metric-grid compact">
        ${metricCard("Automated REVIEW cases", human["Automated REVIEW cases"] || 0)}
        ${metricCard("Approved", human.Approved || 0, "pass")}
        ${metricCard("Needs Improvement", human["Needs Improvement"] || 0, "fail")}
        ${metricCard("Not Reviewed", human["Not Reviewed"] || 0, "review")}
      </div>
    </section>

    <section class="panel">
      <div class="table-head">
        <div>
          <h3>Final V3 Test Cases</h3>
          <p class="muted">Search and filter tests, then open a case for evidence, response, and human-review checklist.</p>
        </div>
      </div>
      <div class="filters">
        <input id="evalSearch" type="search" placeholder="Search question or Test ID" />
        <select id="categoryFilter"><option value="">All categories</option></select>
        <select id="resultFilter"><option value="">All automated results</option></select>
        <select id="humanFilter"><option value="">All human statuses</option></select>
      </div>
      <div id="evaluationTable" class="evaluation-table"></div>
    </section>

    <section class="panel">
      <h3>Representative Examples</h3>
      <div class="example-list">${examples.map(exampleCard).join("")}</div>
    </section>

    <section class="panel">
      <h3>Known Limitations</h3>
      <ul class="limitation-list">
        ${limitations.map((item) => `<li><strong>${escapeHtml(item.type || "limitation")}:</strong> ${escapeHtml(item.description || "")}</li>`).join("")}
      </ul>
    </section>
  `;

  setupEvaluationFilters();
  renderEvaluationTable();
}

function metricCard(label, value, tone = "") {
  return `<div class="metric-card ${tone}"><span>${escapeHtml(String(label))}</span><strong>${escapeHtml(String(value ?? "0"))}</strong></div>`;
}

function experimentCard(name, values) {
  return `<div class="experiment-card"><h4>${escapeHtml(name)}</h4><dl>
    <div><dt>Rank 1</dt><dd>${escapeHtml(String(values["Rank 1"]))}</dd></div>
    <div><dt>Top 3</dt><dd>${escapeHtml(String(values["Top 3"]))}</dd></div>
    <div><dt>Top 5</dt><dd>${escapeHtml(String(values["Top 5"]))}</dd></div>
    <div><dt>NO_CONTEXT</dt><dd>${escapeHtml(String(values.NO_CONTEXT))}</dd></div>
  </dl></div>`;
}

function exampleCard(example) {
  return `<details class="example-card">
    <summary><span>${escapeHtml(example.behavior_label || "")}</span><strong>${escapeHtml(example.evaluation_result || "")}</strong></summary>
    <p class="question">${escapeHtml(example.learner_question || "")}</p>
    <div class="rendered">${renderMarkdown(example.mentor_response || "")}</div>
    <p class="muted">Sources: ${escapeHtml(example.learner_facing_sources || "None")}</p>
  </details>`;
}

function setupEvaluationFilters() {
  const categories = [...new Set(state.evaluationTests.map((test) => test.category).filter(Boolean))].sort();
  const results = [...new Set(state.evaluationTests.map((test) => test.automated_result).filter(Boolean))].sort();
  fillSelect(document.getElementById("categoryFilter"), categories);
  fillSelect(document.getElementById("resultFilter"), results);
  fillSelect(document.getElementById("humanFilter"), ["Not Reviewed", "Approved", "Needs Improvement"]);
  ["evalSearch", "categoryFilter", "resultFilter", "humanFilter"].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderEvaluationTable);
  });
}

function fillSelect(select, values) {
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function filteredEvaluationTests() {
  const search = document.getElementById("evalSearch").value.trim().toLowerCase();
  const category = document.getElementById("categoryFilter").value;
  const result = document.getElementById("resultFilter").value;
  const human = document.getElementById("humanFilter").value;
  return state.evaluationTests.filter((test) => {
    const textMatch = !search || `${test.test_id} ${test.learner_question}`.toLowerCase().includes(search);
    return textMatch
      && (!category || test.category === category)
      && (!result || test.automated_result === result)
      && (!human || test.human_status === human);
  });
}

function renderEvaluationTable() {
  const rows = filteredEvaluationTests();
  const table = document.getElementById("evaluationTable");
  table.innerHTML = `
    <table>
      <thead><tr><th>Test ID</th><th>Category</th><th>Question</th><th>Automated</th><th>Human Review</th><th>Expected</th><th>Sources</th></tr></thead>
      <tbody>
        ${rows.map((test) => `
          <tr data-test-id="${escapeHtml(test.test_id)}">
            <td>${escapeHtml(test.test_id)}</td>
            <td>${escapeHtml(test.category)}</td>
            <td>${escapeHtml(shortText(test.learner_question, 120))}</td>
            <td>${badge(test.automated_result)}</td>
            <td>${badge(test.human_status)}</td>
            <td>${escapeHtml(shortText(test.expected_behavior || test.expected_source || "", 90))}</td>
            <td>${escapeHtml(shortText(test.actual_sources || "None", 80))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  table.querySelectorAll("tr[data-test-id]").forEach((row) => {
    row.addEventListener("click", () => openEvaluationDetail(row.dataset.testId));
  });
}

function badge(value) {
  const normalized = String(value || "Not Reviewed").toLowerCase().replace(/[^a-z]+/g, "-");
  return `<span class="badge ${normalized}">${escapeHtml(String(value || "Not Reviewed"))}</span>`;
}

function shortText(text, length) {
  const value = String(text || "");
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

async function openEvaluationDetail(testId) {
  const response = await fetch(`/api/evaluation/tests/${encodeURIComponent(testId)}`);
  if (!response.ok) {
    showError("Could not load evaluation detail.");
    return;
  }
  const detail = await response.json();
  state.selectedTest = detail;
  renderDetailModal(detail);
}

function renderDetailModal(detail) {
  const existing = document.getElementById("detailModal");
  if (existing) existing.remove();
  const test = detail.test;
  const debug = detail.debug || {};
  const review = detail.human_review || {};
  const isDraft = test.Category === "Draft Review" || String(test["Detected Interaction Behavior"] || "").includes("DRAFT");
  const modal = document.createElement("div");
  modal.id = "detailModal";
  modal.className = "modal-backdrop";
  modal.innerHTML = `
    <section class="detail-modal" role="dialog" aria-modal="true" aria-label="Evaluation detail">
      <header class="detail-header">
        <div><h3>${escapeHtml(test["Test ID"])} · ${escapeHtml(test.Category || "")}</h3><p>${badge(test["Automated Result"])} ${badge(review.human_status || "Not Reviewed")}</p></div>
        <button type="button" class="close-button" aria-label="Close">×</button>
      </header>
      <div class="detail-grid">
        <section>
          <h4>Question / Draft</h4>
          <div class="detail-box preserve">${escapeHtml(test["Learner Question"] || "")}</div>
          <h4>Mentor Response</h4>
          <div class="detail-box rendered">${renderMarkdown(test["Actual Response"] || "")}</div>
          <p class="muted">Sources: ${escapeHtml(test["Actual Sources"] || "None")}</p>
        </section>
        <aside>
          <h4>Automated Evaluation</h4>
          <dl class="meta-list">
            <div><dt>Expected behavior</dt><dd>${escapeHtml(test["Expected Behavior"] || "")}</dd></div>
            <div><dt>Expected source</dt><dd>${escapeHtml(test["Expected Primary Source"] || "")}</dd></div>
            <div><dt>Flags</dt><dd>${escapeHtml(test.Notes || "None")}</dd></div>
            <div><dt>Detected behavior</dt><dd>${escapeHtml(test["Detected Interaction Behavior"] || "")}</dd></div>
          </dl>
          ${humanReviewForm(test["Test ID"], review, isDraft)}
          <details class="technical-details">
            <summary>Technical evidence</summary>
            <p class="muted">Retrieval query: ${escapeHtml(debug.retrieval_query || "N/A")}</p>
            ${(debug.evidence || []).map((row) => `<div class="evidence-row">Rank ${escapeHtml(String(row.rank || ""))}: ${escapeHtml(row.knowledge_role || "")} · ${escapeHtml(row.topic || "")} · page ${escapeHtml(String(row.page_start || ""))}</div>`).join("")}
          </details>
        </aside>
      </div>
    </section>
  `;
  document.body.appendChild(modal);
  modal.querySelector(".close-button").addEventListener("click", () => modal.remove());
  modal.addEventListener("click", (event) => {
    if (event.target === modal) modal.remove();
  });
  modal.querySelector("#saveReview").addEventListener("click", () => saveHumanReview(test["Test ID"], isDraft));
}

function humanReviewForm(testId, review, isDraft) {
  const checklist = review.checklist || {};
  const general = [
    "Answer addresses the learner's question",
    "Information is supported by retrieved/approved knowledge",
    "Correct source/authority was used",
    "No important requirement was omitted, or N/A",
    "No unsupported information was added",
    "Explanation is understandable for the learner",
    "Response length/detail is appropriate",
    "Academic-integrity behavior is appropriate, or N/A",
    "Learner-facing sources are appropriate",
  ];
  const draft = [
    "Strengths were identified accurately",
    "Missing/unclear points were identified accurately",
    "Improvement guidance is relevant and supported",
    "No weakness/problem was invented",
    "No grade/percentage was predicted",
    "No complete replacement submission was generated",
  ];
  const items = isDraft ? general.concat(draft) : general;
  return `<form class="review-form" data-test-id="${escapeHtml(testId)}">
    <h4>Human Review Checklist</h4>
    ${items.map((label) => {
      const id = reviewKey(label);
      return `<label><input type="checkbox" data-review-key="${id}" ${checklist[id] ? "checked" : ""}> ${escapeHtml(label)}</label>`;
    }).join("")}
    <label>Human Review
      <select id="humanStatus">
        ${["Not Reviewed", "Approved", "Needs Improvement"].map((status) => `<option value="${status}" ${review.human_status === status ? "selected" : ""}>${status}</option>`).join("")}
      </select>
    </label>
    <label>Reviewer name/role <input id="reviewer" type="text" value="${escapeHtml(review.reviewer || "")}"></label>
    <label>Review date/time <input id="reviewedAt" type="datetime-local" value="${toDateTimeLocal(review.reviewed_at || "")}"></label>
    <label>Comments <textarea id="reviewComments" rows="4">${escapeHtml(review.comments || "")}</textarea></label>
    <button id="saveReview" type="button">Save Human Review</button>
  </form>`;
}

function reviewKey(label) {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function toDateTimeLocal(value) {
  if (!value) return "";
  return value.slice(0, 16);
}

async function saveHumanReview(testId) {
  const modal = document.getElementById("detailModal");
  const checklist = {};
  modal.querySelectorAll("[data-review-key]").forEach((input) => {
    checklist[input.dataset.reviewKey] = input.checked;
  });
  const reviewedAt = modal.querySelector("#reviewedAt").value || new Date().toISOString().slice(0, 16);
  const payload = {
    test_id: testId,
    checklist,
    human_status: modal.querySelector("#humanStatus").value,
    reviewer: modal.querySelector("#reviewer").value.trim(),
    reviewed_at: reviewedAt,
    comments: modal.querySelector("#reviewComments").value.trim(),
  };
  const response = await fetch(`/api/evaluation/human-reviews/${encodeURIComponent(testId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    alert("Could not save human review.");
    return;
  }
  const data = await response.json();
  const row = state.evaluationTests.find((test) => test.test_id === testId);
  if (row) row.human_status = data.review.human_status;
  state.evaluationSummary.human_review_summary = data.summary;
  modal.remove();
  renderEvaluation();
}

async function loadAdmin() {
  adminRoot.innerHTML = `<div class="panel"><p>Loading Lecturer Workspace...</p></div>`;
  state.admin.loading = true;
  try {
    const [metadata, modules] = await Promise.all([
      adminFetch("/api/admin/metadata"),
      adminFetch("/api/admin/modules"),
    ]);
    state.admin.metadata = metadata;
    state.admin.modules = modules.modules || [];
    state.adminLoaded = true;
    state.admin.error = "";
    renderAdminModules();
  } catch (error) {
    state.admin.error = friendlyError(error);
    adminRoot.innerHTML = `<div class="error">${escapeHtml(state.admin.error)}</div>`;
  } finally {
    state.admin.loading = false;
  }
}

async function adminFetch(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || "The Admin request could not be completed.");
  }
  return data;
}

function renderAdminShell(content) {
  adminRoot.innerHTML = `
    <section class="admin-hero panel">
      <div>
        <p class="eyebrow">Local V1 demo</p>
        <h2>Lecturer Workspace</h2>
        <p>Manage the course knowledge used by AI Mentor.</p>
        <p>Create a module, upload your course documents, review the prepared knowledge, and publish it when it is ready for learners.</p>
        <p class="muted">No production authentication is enabled in this local demo.</p>
      </div>
      ${state.admin.selectedVersion ? `<div class="status-card">Current Version<br><strong>${escapeHtml(state.admin.selectedVersion.status)}</strong>${state.admin.selectedVersion.is_active ? "<br>Active: Yes" : ""}</div>` : ""}
    </section>
    ${state.admin.error ? `<div class="error">${escapeHtml(state.admin.error)}</div>` : ""}
    ${state.admin.message ? `<div class="success-message">${escapeHtml(state.admin.message)}</div>` : ""}
    ${content}
  `;
}

function renderAdminModules() {
  state.admin.selectedModule = null;
  state.admin.selectedVersion = null;
  const visibleModules = state.admin.modules.filter((module) => !isDevelopmentModule(module));
  const hiddenModules = state.admin.modules.filter(isDevelopmentModule);
  renderAdminShell(`
    <section class="panel lecturer-landing">
      <div class="admin-section-head">
        <div>
          <h3>Your Modules</h3>
          <p class="muted">Create a module, add documents, prepare knowledge, review it, then publish it to AI Mentor.</p>
        </div>
        <button type="button" class="primary-action" data-focus-module-form>Create Module</button>
      </div>
      ${visibleModules.length ? `<div class="admin-card-grid">
        ${visibleModules.map((module) => `
          <article class="admin-card module-card">
            <h4>${escapeHtml(module.name)}</h4>
            <p class="code-label">${escapeHtml(module.module_code)}</p>
            <p class="muted">${escapeHtml(module.description || "No description yet")}</p>
            <div class="module-card-footer">
              ${badge(module.status)}
              <button type="button" data-open-module="${escapeAttribute(module.id)}">Manage Module</button>
            </div>
          </article>
        `).join("")}
      </div>` : `<div class="empty-admin lecturer-empty">
        <h4>Welcome to Lecturer Workspace</h4>
        <p>Create your first AI Mentor module.</p>
        <ol>
          <li>Add course documents</li>
          <li>Prepare AI Mentor knowledge</li>
          <li>Review the prepared information</li>
          <li>Publish it for learners</li>
        </ol>
        <button type="button" class="primary-action" data-focus-module-form>Create Your First Module</button>
      </div>`}
      ${hiddenModules.length ? `<details class="technical-details">
        <summary>Technical Details: ${hiddenModules.length} development modules hidden</summary>
        <p class="muted">These records were retained in the local database but hidden from the normal lecturer view because their module codes are clearly marked as smoke/development records.</p>
        <div class="hidden-module-list">${hiddenModules.map((module) => `<code>${escapeHtml(module.module_code)}</code>`).join("")}</div>
      </details>` : ""}
    </section>
    <section class="panel">
      <h3>Create AI Mentor Module</h3>
      <form id="moduleForm" class="admin-form">
        <label>Module Name *<input name="name" required maxlength="200" placeholder="Data Modelling and Visualisation"></label>
        <label>Module Code *<input name="module_code" required maxlength="80" placeholder="DMV"></label>
        <label>Description<textarea name="description" rows="3" maxlength="4000"></textarea></label>
        <button type="submit">Create Module</button>
      </form>
    </section>
  `);
  adminRoot.querySelectorAll("[data-open-module]").forEach((button) => {
    button.addEventListener("click", () => openAdminModule(button.dataset.openModule));
  });
  adminRoot.querySelectorAll("[data-focus-module-form]").forEach((button) => {
    button.addEventListener("click", () => adminRoot.querySelector("#moduleForm input[name='name']")?.focus());
  });
  adminRoot.querySelector("#moduleForm").addEventListener("submit", createAdminModule);
}

async function createAdminModule(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  await adminAction(async () => {
    const created = await adminFetch("/api/admin/modules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(formData.entries())),
    });
    const modules = await adminFetch("/api/admin/modules");
    state.admin.modules = modules.modules || [];
    state.admin.message = "Module created. Continue setup by adding a level and version.";
    if (created.module?.id) {
      await openAdminModule(created.module.id);
    } else {
      renderAdminModules();
    }
  });
}

async function openAdminModule(moduleId) {
  await adminAction(async () => {
    const module = await adminFetch(`/api/admin/modules/${encodeURIComponent(moduleId)}`);
    const versions = await adminFetch(`/api/admin/modules/${encodeURIComponent(moduleId)}/versions`);
    state.admin.selectedModule = module.module;
    state.admin.versions = versions.versions || [];
    state.admin.selectedVersion = null;
    renderAdminModuleDetail();
  });
}

function renderAdminModuleDetail() {
  const module = state.admin.selectedModule;
  renderAdminShell(`
    <section class="panel">
      <button type="button" class="link-button" id="backModules">Back to Modules</button>
      <h3>${escapeHtml(module.name)}</h3>
      <p class="code-label">${escapeHtml(module.module_code)}</p>
      <p>${escapeHtml(module.description || "No description")}</p>
    </section>
    <section class="panel">
      <h3>Versions</h3>
      ${state.admin.versions.length ? `<div class="admin-list">
        ${state.admin.versions.map((version) => `
          <div class="admin-list-row">
            <div>
              <strong>${escapeHtml(version.level)} - Version ${escapeHtml(version.version)}</strong>
              <p class="muted">Status: ${escapeHtml(version.status)}${version.is_active ? " | Active: Yes" : ""}</p>
            </div>
            <button type="button" data-open-version="${escapeAttribute(version.id)}">Continue Setup</button>
          </div>
        `).join("")}
      </div>` : `<div class="empty-admin">No setup version yet. Create one to start adding documents.</div>`}
    </section>
    <section class="panel">
      <h3>Set Up Module Knowledge</h3>
      <p class="muted">Versions let you update course knowledge later without changing the version currently used by learners.</p>
      <form id="versionForm" class="admin-form compact-form">
        <label>Level *<input name="level" required maxlength="80" value="Basic" placeholder="Basic"></label>
        <label>Version *<input name="version" required maxlength="80" value="1" placeholder="1"></label>
        <label>Description<textarea name="description" rows="2" maxlength="4000"></textarea></label>
        <button type="submit">Continue</button>
      </form>
    </section>
  `);
  adminRoot.querySelector("#backModules").addEventListener("click", () => loadAdmin());
  adminRoot.querySelectorAll("[data-open-version]").forEach((button) => {
    button.addEventListener("click", () => openAdminVersion(button.dataset.openVersion));
  });
  adminRoot.querySelector("#versionForm").addEventListener("submit", createAdminVersion);
}

async function createAdminVersion(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const moduleId = state.admin.selectedModule.id;
  await adminAction(async () => {
    const created = await adminFetch(`/api/admin/modules/${encodeURIComponent(moduleId)}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(formData.entries())),
    });
    const versions = await adminFetch(`/api/admin/modules/${encodeURIComponent(moduleId)}/versions`);
    state.admin.versions = versions.versions || [];
    state.admin.message = "Version created. Add course documents next.";
    const createdVersion = created.version || state.admin.versions[0];
    if (createdVersion?.id) {
      await openAdminVersion(createdVersion.id);
    } else {
      renderAdminModuleDetail();
    }
  });
}

async function openAdminVersion(versionId) {
  await adminAction(async () => {
    const version = await adminFetch(`/api/admin/versions/${encodeURIComponent(versionId)}`);
    state.admin.selectedVersion = version.version;
    await refreshAdminVersionData();
    renderAdminVersionWorkspace();
  });
}

async function refreshAdminVersionData() {
  const versionId = state.admin.selectedVersion.id;
  const [documents, prepJobs, publishJobs] = await Promise.all([
    adminFetch(`/api/admin/versions/${encodeURIComponent(versionId)}/documents`),
    adminFetch(`/api/admin/versions/${encodeURIComponent(versionId)}/preparation-jobs`),
    adminFetch(`/api/admin/versions/${encodeURIComponent(versionId)}/publish-jobs`),
  ]);
  state.admin.documents = documents.documents || [];
  state.admin.preparationJobs = prepJobs.jobs || [];
  state.admin.publishJobs = publishJobs.jobs || [];
  state.admin.reviewSummary = null;
  state.admin.chunks = [];
  state.admin.warnings = [];
  if (state.admin.preparationJobs.length) {
    const latestJob = state.admin.preparationJobs[0];
    const [chunks, warnings] = await Promise.all([
      adminFetch(`/api/admin/preparation-jobs/${encodeURIComponent(latestJob.id)}/chunks?limit=500`),
      adminFetch(`/api/admin/preparation-jobs/${encodeURIComponent(latestJob.id)}/warnings`),
    ]);
    state.admin.chunks = chunks.chunks || [];
    state.admin.warnings = warnings.warnings || [];
  }
  try {
    const summary = await adminFetch(`/api/admin/versions/${encodeURIComponent(versionId)}/review-summary`);
    state.admin.reviewSummary = summary.summary;
  } catch {
    state.admin.reviewSummary = null;
  }
}

function renderAdminVersionWorkspace() {
  const module = state.admin.selectedModule;
  const version = state.admin.selectedVersion;
  const latestPrep = state.admin.preparationJobs[0];
  const latestPublish = state.admin.publishJobs[0];
  renderAdminShell(`
    <section class="panel">
      <button type="button" class="link-button" id="backModule">Back to Module</button>
      <h3>${escapeHtml(module.name)}</h3>
      <p class="code-label">${escapeHtml(version.level)} - Version ${escapeHtml(version.version)}</p>
      <div class="workflow-steps">
        ${["Documents", "Prepare", "Review", "Approve", "Publish"].map((step, index) => `<div class="workflow-step ${workflowStepClass(index)}"><span>${workflowStepClass(index) === "complete" ? "✓" : index + 1}</span>${step}</div>`).join("")}
      </div>
    </section>
    ${renderDocumentsSection()}
    ${renderPrepareSection(latestPrep)}
    ${renderReviewSection()}
    ${renderApproveSection()}
    ${renderPublishSection(latestPublish)}
  `);
  bindAdminVersionEvents();
}

function workflowStepClass(index) {
  const status = state.admin.selectedVersion.status;
  if (index === 0 && state.admin.documents.length) return "complete";
  if (index === 1 && state.admin.preparationJobs.length) return "complete";
  if (index === 2 && state.admin.reviewSummary && state.admin.reviewSummary.total_chunks) return "complete";
  if (index === 3 && ["APPROVED", "PUBLISHED"].includes(status)) return "complete";
  if (index === 4 && status === "PUBLISHED") return "complete";
  return "";
}

function renderDocumentsSection() {
  return `<section class="panel">
    <div class="admin-section-head">
      <div>
        <h3>1. Add Course Documents</h3>
        <p class="muted">Upload the materials AI Mentor should use when helping learners.</p>
      </div>
    </div>
    <div class="upload-callout">
      <h4>Add Course Documents</h4>
      <p>PDF is supported for AI Mentor knowledge preparation in this version.</p>
      <p class="muted">DOCX, PPTX, and XLSX upload is supported, but AI Mentor knowledge preparation is not yet supported for those formats.</p>
    </div>
    ${state.admin.documents.length ? `<table class="admin-table">
      <thead><tr><th>Document</th><th>Role</th><th>Type</th><th>Status</th><th>Preparation</th></tr></thead>
      <tbody>${state.admin.documents.map((document) => `
        <tr>
          <td>${escapeHtml(document.original_filename)}</td>
          <td>${roleLabel(document.knowledge_role)}</td>
          <td>${escapeHtml(document.document_type)}</td>
          <td>${badge(document.status)}</td>
          <td>${formatSupport(document.file_type)}</td>
        </tr>`).join("")}</tbody>
    </table>` : `<div class="empty-admin">No documents uploaded yet. Upload an assignment brief, learning material, or learner guide to begin.</div>`}
    <form id="uploadForm" class="admin-form upload-form">
      <label>File *<input name="file" type="file" required accept=".pdf,.docx,.pptx,.xlsx"></label>
      <label>Knowledge Role *
        <select name="knowledge_role" required>
          <option value="OFFICIAL_REQUIREMENT">Official Requirement</option>
          <option value="LEARNING_MATERIAL">Learning Material</option>
          <option value="MODULE_GUIDANCE">Module Guidance</option>
        </select>
      </label>
      <label>Document Type *<input name="document_type" required placeholder="project_brief, instructional_unit, learner_guide"></label>
      <label>Instructional Unit<input name="instructional_unit" placeholder="IU1"></label>
      <label>Document Version<input name="document_version" value="v1"></label>
      <label>Uploaded By<input name="uploaded_by" value="local-demo"></label>
      <div class="role-help">
        <p><strong>Official Requirement:</strong> Assessment briefs, required tasks, deliverables and rubric information.</p>
        <p><strong>Learning Material:</strong> Teaching materials, instructional units and concept explanations.</p>
        <p><strong>Module Guidance:</strong> Learning outcomes, module information and general learner guidance.</p>
      </div>
      <button type="submit">Add Document</button>
    </form>
  </section>`;
}

function renderPrepareSection(job) {
  return `<section class="panel">
    <h3>2. Prepare AI Mentor Knowledge</h3>
    <p>The system will read and organise the uploaded course documents so AI Mentor can search them when helping learners.</p>
    <p class="muted">Nothing will be available to learners until you review and publish it.</p>
    <button type="button" id="prepareButton" ${state.admin.loading || !state.admin.documents.length ? "disabled" : ""}>Prepare Knowledge</button>
    ${state.admin.loading ? `<div class="loading-panel"><strong>Preparing knowledge...</strong><p>Reading and organising your course materials. This may take a moment.</p></div>` : ""}
    ${job ? `<div class="prep-summary">
      <h4>${job.status === "FAILED" ? "Knowledge Preparation Failed" : "Knowledge Preparation Complete"}</h4>
      <div class="metric-grid compact">
        ${metricCard("Documents processed", job.source_document_count)}
        ${metricCard("Knowledge items ready", Math.max(0, Number(job.embedding_eligible_count || 0) - Number(job.needs_review_count || 0)), "pass")}
        ${metricCard("Items need attention", job.needs_review_count, "review")}
        ${metricCard("Excluded from AI Mentor", Math.max(0, Number(job.chunk_count || 0) - Number(job.embedding_eligible_count || 0)))}
      </div>
      ${job.error_message ? `<div class="error">${escapeHtml(job.error_message)}</div>` : ""}
      <details class="technical-details">
        <summary>Technical Details</summary>
        <div class="metric-grid compact">
          ${metricCard("Prepared items", job.chunk_count)}
          ${metricCard("Embedding eligible", job.embedding_eligible_count)}
          ${metricCard("Warnings", job.warning_count)}
          ${metricCard("Job status", job.status)}
        </div>
        ${state.admin.warnings.length ? renderWarningSummary() : ""}
      </details>
    </div>` : `<div class="empty-admin">Knowledge has not been prepared yet.</div>`}
  </section>`;
}

function renderReviewSection() {
  const summary = state.admin.reviewSummary;
  const chunks = filteredAdminChunks();
  const defaultNeedsReview = state.admin.chunkFilter === "all" && chunks.some((chunk) => chunk.review_status === "NEEDS_REVIEW");
  const shownChunks = defaultNeedsReview ? chunks.filter((chunk) => chunk.review_status === "NEEDS_REVIEW") : chunks;
  return `<section class="panel">
    <h3>3. Review Knowledge</h3>
    <p class="muted">Most prepared knowledge can be used automatically. Please check the items that need your attention before publishing.</p>
    ${summary ? `<div class="metric-grid compact">
      ${metricCard("Approved", summary.approved)}
      ${metricCard("Needs Review", summary.needs_review)}
      ${metricCard("Rejected", summary.rejected)}
    </div>
    <p class="muted">${summary.approved + summary.rejected} / ${summary.total_chunks} reviewed. Rejected knowledge counts as reviewed but is not published.</p>` : `<div class="empty-admin">Prepare knowledge before review.</div>`}
    ${state.admin.chunks.length ? `
      <div class="filters admin-filters">
        <select id="chunkStatusFilter">
          <option value="all">Needs Review first</option>
          <option value="NEEDS_REVIEW">Needs Review</option>
          <option value="APPROVED">Approved</option>
          <option value="REJECTED">Rejected</option>
          <option value="SHOW_ALL">Show All Knowledge</option>
        </select>
        <select id="chunkDocumentFilter"><option value="">All documents</option>${state.admin.documents.map((document) => `<option value="${escapeAttribute(document.id)}">${escapeHtml(document.original_filename)}</option>`).join("")}</select>
        <select id="chunkRoleFilter"><option value="">All roles</option><option value="OFFICIAL_REQUIREMENT">Official Requirement</option><option value="LEARNING_MATERIAL">Learning Material</option><option value="MODULE_GUIDANCE">Module Guidance</option></select>
      </div>
      <div class="bulk-actions">
        <button type="button" id="approveSelected">Approve Selected</button>
        <button type="button" id="rejectSelected">Reject Selected</button>
        <button type="button" id="resetSelected" class="secondary-button">Move Back to Needs Review</button>
        <button type="button" id="approveEligibleDocument">Approve Eligible in Selected Document</button>
      </div>
      <div class="chunk-list">${shownChunks.length ? shownChunks.map(renderChunkCard).join("") : `<div class="empty-admin">No knowledge items match this filter.</div>`}</div>
    ` : ""}
  </section>`;
}

function renderApproveSection() {
  const summary = state.admin.reviewSummary;
  const canApprove = summary && summary.eligible_for_approval && !["APPROVED", "PUBLISHED"].includes(state.admin.selectedVersion.status);
  return `<section class="panel">
    <h3>4. Approve Knowledge Version</h3>
    ${summary && summary.eligible_for_approval ? `<div class="success-message"><strong>Knowledge Review Complete</strong><br>Approved: ${escapeHtml(String(summary.approved))} | Rejected: ${escapeHtml(String(summary.rejected))} | Needs Review: ${escapeHtml(String(summary.needs_review))}</div>` : ""}
    <p>Approving confirms that this knowledge is ready to be published to AI Mentor.</p>
    ${summary && summary.approval_blockers.length ? `<div class="warning-box"><strong>Before you can approve:</strong><ul>${summary.approval_blockers.map((item) => `<li>${escapeHtml(friendlyApprovalBlocker(item))}</li>`).join("")}</ul></div>` : ""}
    <button type="button" id="approveVersionButton" ${canApprove ? "" : "disabled"}>Approve Knowledge Version</button>
    ${state.admin.selectedVersion.status === "APPROVED" ? `<button type="button" id="reopenVersionButton" class="secondary-button">Return to Review</button>` : ""}
  </section>`;
}

function renderPublishSection(job) {
  const version = state.admin.selectedVersion;
  const canPublish = version.status === "APPROVED";
  return `<section class="panel">
    <h3>5. Publish</h3>
    ${version.status === "PUBLISHED" ? `<div class="success-message publish-success">
      <h4>AI Mentor is Ready</h4>
      <p>${escapeHtml(state.admin.selectedModule.name)}<br>${escapeHtml(version.level)}</p>
      <p>Published successfully. Learners can now ask AI Mentor questions using the approved module knowledge.</p>
      <button type="button" class="secondary-button" id="openLearnerChat">Open Learner Chat</button>
    </div>` : ""}
    ${canPublish ? `<div class="publish-ready">
      <h4>Ready to Publish</h4>
      <p>${escapeHtml(state.admin.selectedModule.name)}<br>${escapeHtml(version.level)} - Version ${escapeHtml(version.version)}</p>
      <p>Publishing makes the approved knowledge available to learners through AI Mentor.</p>
      <button type="button" id="publishButton">Publish to AI Mentor</button>
    </div>` : `<p class="muted">Publishing is enabled after the knowledge version is approved.</p>`}
    ${job ? `<div class="publish-result">
      <p><strong>Latest publish:</strong> ${escapeHtml(job.status)}</p>
      <details class="technical-details"><summary>Technical Details</summary><p class="muted">Source items: ${escapeHtml(String(job.source_chunk_count))} | Published items: ${escapeHtml(String(job.embedded_chunk_count))}</p></details>
      ${job.status === "FAILED" ? `<div class="error">Publishing Failed. The new version was not activated. Existing learner knowledge remains unchanged. ${escapeHtml(job.error_message || "")}</div>` : ""}
    </div>` : ""}
  </section>`;
}

function renderChunkCard(chunk) {
  const document = state.admin.documents.find((item) => item.id === chunk.document_id);
  const warnings = warningsForChunk(chunk);
  return `<article class="chunk-card">
    <label class="chunk-select"><input type="checkbox" data-chunk-select="${escapeAttribute(chunk.id)}"> Select</label>
    <div class="chunk-meta">
      <span>${escapeHtml(document?.original_filename || "Source document")} &bull; Page ${escapeHtml(pageRange(chunk.page_start, chunk.page_end))}</span>
      <span>${roleLabel(chunk.knowledge_role)}</span>
      <span>${badge(chunk.review_status)}</span>
    </div>
    <h4>${escapeHtml(chunk.section_title || "Untitled section")}</h4>
    <p class="muted">${escapeHtml(chunk.topic || "")}</p>
    <div class="detail-box preserve">${escapeHtml(chunk.content)}</div>
    ${warnings.length ? `<details class="technical-details"><summary>Why does this need review?</summary>${warnings.map(renderFriendlyWarning).join("")}</details>` : ""}
    <label>Reviewer comment<textarea data-comment-for="${escapeAttribute(chunk.id)}" rows="2">${escapeHtml(chunk.review_comment || "")}</textarea></label>
    <div class="chunk-actions">
      <button type="button" data-review-action="approve" data-chunk-id="${escapeAttribute(chunk.id)}">Approve</button>
      <button type="button" data-review-action="reject" data-chunk-id="${escapeAttribute(chunk.id)}">Reject</button>
      <button type="button" class="secondary-button" data-review-action="needs-review" data-chunk-id="${escapeAttribute(chunk.id)}">Needs Review</button>
    </div>
    <details class="metadata-editor">
      <summary>Edit Details</summary>
      <form data-metadata-form="${escapeAttribute(chunk.id)}" class="admin-form compact-form">
        <label>Section title<input name="section_title" value="${escapeAttribute(chunk.section_title || "")}"></label>
        <label>Topic<input name="topic" value="${escapeAttribute(chunk.topic || "")}"></label>
        <label>Task reference<input name="task_reference" value="${escapeAttribute(chunk.task_reference || "")}"></label>
        <label>Instructional unit<input name="instructional_unit" value="${escapeAttribute(chunk.instructional_unit || "")}"></label>
        <label>Knowledge role<select name="knowledge_role">
          ${["OFFICIAL_REQUIREMENT", "LEARNING_MATERIAL", "MODULE_GUIDANCE"].map((role) => `<option value="${role}" ${chunk.knowledge_role === role ? "selected" : ""}>${roleLabel(role)}</option>`).join("")}
        </select></label>
        <label>Change comment<input name="comment" placeholder="Why this metadata changed"></label>
        <button type="submit">Save Metadata</button>
      </form>
    </details>
  </article>`;
}

function bindAdminVersionEvents() {
  adminRoot.querySelector("#backModule")?.addEventListener("click", () => openAdminModule(state.admin.selectedModule.id));
  adminRoot.querySelector("#uploadForm")?.addEventListener("submit", uploadAdminDocument);
  adminRoot.querySelector("#prepareButton")?.addEventListener("click", prepareAdminKnowledge);
  adminRoot.querySelector("#approveVersionButton")?.addEventListener("click", approveAdminVersion);
  adminRoot.querySelector("#reopenVersionButton")?.addEventListener("click", reopenAdminVersion);
  adminRoot.querySelector("#publishButton")?.addEventListener("click", publishAdminVersion);
  adminRoot.querySelector("#openLearnerChat")?.addEventListener("click", () => switchView("chat"));
  ["chunkStatusFilter", "chunkDocumentFilter", "chunkRoleFilter"].forEach((id) => {
    adminRoot.querySelector(`#${id}`)?.addEventListener("change", (event) => {
      if (id === "chunkStatusFilter") state.admin.chunkFilter = event.target.value;
      if (id === "chunkDocumentFilter") state.admin.documentFilter = event.target.value;
      if (id === "chunkRoleFilter") state.admin.roleFilter = event.target.value;
      renderAdminVersionWorkspace();
    });
  });
  adminRoot.querySelectorAll("[data-chunk-select]").forEach((input) => {
    input.checked = state.admin.selectedChunks.has(input.dataset.chunkSelect);
    input.addEventListener("change", () => {
      if (input.checked) state.admin.selectedChunks.add(input.dataset.chunkSelect);
      else state.admin.selectedChunks.delete(input.dataset.chunkSelect);
    });
  });
  adminRoot.querySelectorAll("[data-review-action]").forEach((button) => {
    button.addEventListener("click", () => reviewAdminChunk(button.dataset.chunkId, button.dataset.reviewAction));
  });
  adminRoot.querySelectorAll("[data-metadata-form]").forEach((form) => {
    form.addEventListener("submit", updateChunkMetadata);
  });
  adminRoot.querySelector("#approveSelected")?.addEventListener("click", () => bulkReview("approve"));
  adminRoot.querySelector("#rejectSelected")?.addEventListener("click", () => bulkReview("reject"));
  adminRoot.querySelector("#resetSelected")?.addEventListener("click", () => bulkReview("needs-review"));
  adminRoot.querySelector("#approveEligibleDocument")?.addEventListener("click", approveEligibleInDocument);
}

async function uploadAdminDocument(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  await adminAction(async () => {
    await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}/documents/upload`, {
      method: "POST",
      body: formData,
    });
    state.admin.message = "Document uploaded.";
    await reloadAdminVersion();
  });
}

async function prepareAdminKnowledge() {
  await adminAction(async () => {
    state.admin.loading = true;
    renderAdminVersionWorkspace();
    await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}/prepare?created_by=local-demo`, { method: "POST" });
    state.admin.message = "Knowledge preparation complete.";
    await reloadAdminVersion();
  });
}

async function reviewAdminChunk(chunkId, action) {
  const comment = adminRoot.querySelector(`[data-comment-for="${CSS.escape(chunkId)}"]`)?.value || "";
  await adminAction(async () => {
    await adminFetch(`/api/admin/chunks/${encodeURIComponent(chunkId)}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer: "local-demo", comment }),
    });
    await reloadAdminVersion();
  });
}

async function updateChunkMetadata(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const chunkId = form.dataset.metadataForm;
  const values = Object.fromEntries(new FormData(form).entries());
  await adminAction(async () => {
    await adminFetch(`/api/admin/chunks/${encodeURIComponent(chunkId)}/metadata`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updated_by: "local-demo", ...values }),
    });
    state.admin.message = "Metadata updated.";
    await reloadAdminVersion();
  });
}

async function bulkReview(action) {
  const chunkIds = [...state.admin.selectedChunks];
  if (!chunkIds.length) {
    state.admin.error = "Select at least one knowledge item first.";
    renderAdminVersionWorkspace();
    return;
  }
  await adminAction(async () => {
    const result = await adminFetch("/api/admin/chunks/bulk-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, reviewer: "local-demo", comment: "Bulk review from Admin UI", chunk_ids: chunkIds }),
    });
    state.admin.selectedChunks.clear();
    const skipped = (result.results || []).filter((row) => row.status === "skipped").length;
    state.admin.message = `${result.updated || 0} updated${skipped ? `, ${skipped} skipped because they require attention` : ""}.`;
    await reloadAdminVersion();
  });
}

async function approveEligibleInDocument() {
  if (!state.admin.documentFilter) {
    state.admin.error = "Choose a document filter before approving eligible knowledge items in a document.";
    renderAdminVersionWorkspace();
    return;
  }
  await adminAction(async () => {
    const result = await adminFetch("/api/admin/chunks/bulk-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "approve", reviewer: "local-demo", comment: "Bulk approve eligible document knowledge items", document_id: state.admin.documentFilter }),
    });
    state.admin.message = `${result.updated || 0} approved${(result.results || []).some((row) => row.status === "skipped") ? "; some knowledge items were skipped because they require attention" : ""}.`;
    await reloadAdminVersion();
  });
}

async function approveAdminVersion() {
  await adminAction(async () => {
    await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: "local-demo", comment: "Approved from Admin UI" }),
    });
    state.admin.message = "Version approved. It is ready for publishing.";
    await reloadAdminVersion();
  });
}

async function reopenAdminVersion() {
  await adminAction(async () => {
    await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}/reopen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "local-demo", comment: "Returned to review from Admin UI" }),
    });
    state.admin.message = "Version returned to review.";
    await reloadAdminVersion();
  });
}

async function publishAdminVersion() {
  const ok = confirm("Publish to AI Mentor?\n\nOnly approved knowledge will be made available.\n\nRejected, excluded, and unreviewed knowledge will not be published.");
  if (!ok) return;
  await adminAction(async () => {
    state.admin.loading = true;
    state.admin.message = "Publishing knowledge. Creating searchable AI Mentor knowledge.";
    renderAdminVersionWorkspace();
    const result = await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requested_by: "local-demo" }),
    });
    state.admin.message = result.job.status === "COMPLETED"
      ? "Published successfully. This version is now active."
      : "Publishing failed. The new version was not activated.";
    await reloadAdminVersion();
  });
}

async function reloadAdminVersion() {
  const version = await adminFetch(`/api/admin/versions/${encodeURIComponent(state.admin.selectedVersion.id)}`);
  state.admin.selectedVersion = version.version;
  await refreshAdminVersionData();
  renderAdminVersionWorkspace();
}

async function adminAction(callback) {
  state.admin.error = "";
  state.admin.message = "";
  try {
    await callback();
  } catch (error) {
    state.admin.error = friendlyError(error);
    if (state.admin.selectedVersion) renderAdminVersionWorkspace();
    else if (state.admin.selectedModule) renderAdminModuleDetail();
    else renderAdminModules();
  } finally {
    state.admin.loading = false;
  }
}

function filteredAdminChunks() {
  return state.admin.chunks.filter((chunk) => {
    const statusMatches = state.admin.chunkFilter === "all"
      || state.admin.chunkFilter === "SHOW_ALL"
      || chunk.review_status === state.admin.chunkFilter;
    return statusMatches
      && (!state.admin.documentFilter || chunk.document_id === state.admin.documentFilter)
      && (!state.admin.roleFilter || chunk.knowledge_role === state.admin.roleFilter);
  });
}

function warningsForChunk(chunk) {
  return state.admin.warnings.filter((warning) => {
    return warning.chunk_id === chunk.chunk_id || warning.document_id === chunk.document_id;
  });
}

function renderWarningSummary() {
  const grouped = new Map();
  state.admin.warnings.forEach((warning) => {
    grouped.set(warning.warning_type, (grouped.get(warning.warning_type) || 0) + 1);
  });
  return `<details class="technical-details"><summary>Warnings (${state.admin.warnings.length})</summary>
    ${[...grouped.entries()].map(([code, count]) => `<div class="warning-row"><strong>${friendlyWarningTitle(code)}</strong> (${count})<p class="muted">${friendlyWarningText(code)}</p><code>${escapeHtml(code)}</code></div>`).join("")}
  </details>`;
}

function renderFriendlyWarning(warning) {
  return `<div class="warning-row">
    <strong>${friendlyWarningTitle(warning.warning_type)}</strong>
    <p class="muted">${friendlyWarningText(warning.warning_type)}</p>
    <details><summary>Technical details</summary><code>${escapeHtml(warning.warning_type)}</code><pre>${escapeHtml(JSON.stringify(warning.payload || {}, null, 2))}</pre></details>
  </div>`;
}

function friendlyWarningTitle(code) {
  const titles = {
    low_text_image_heavy_page: "Image-heavy page",
    very_low_text_page: "Very low text page",
    table_detected_requires_structure_review: "Table needs checking",
    short_chunk_requires_review: "Short chunk",
    unsupported_preparation_format: "Preparation not supported for this file type",
    missing_required_chunk_metadata: "Missing chunk metadata",
    empty_chunk: "Empty chunk",
    duplicate_chunk_id: "Duplicate chunk ID",
    extraction_warning: "Extraction warning",
  };
  return titles[code] || code.replace(/_/g, " ");
}

function friendlyWarningText(code) {
  const text = {
    low_text_image_heavy_page: "This page contains limited extractable text. Check that important information was captured.",
    very_low_text_page: "This page has very little extracted text and may need lecturer review.",
    table_detected_requires_structure_review: "A table was detected. Check whether the prepared text keeps the table meaning clear.",
    short_chunk_requires_review: "This chunk is short. It may still be acceptable if it is complete and understandable.",
    unsupported_preparation_format: "The file was uploaded, but this format cannot be prepared into AI Mentor knowledge yet.",
  };
  return text[code] || "Review this item before approval if it affects learner-facing knowledge.";
}

function friendlyApprovalBlocker(message) {
  return String(message || "")
    .replace(/chunks/gi, "knowledge items")
    .replace(/chunk/gi, "knowledge item")
    .replace(/embedding eligible/gi, "available for AI Mentor");
}

function isDevelopmentModule(module) {
  const code = String(module.module_code || "").toUpperCase();
  return code.startsWith("SMOKE-") || code.startsWith("PH2-") || code.startsWith("PH3-SMOKE-");
}

function roleLabel(role) {
  const labels = {
    OFFICIAL_REQUIREMENT: "Official Requirement",
    LEARNING_MATERIAL: "Learning Material",
    MODULE_GUIDANCE: "Module Guidance",
  };
  return labels[role] || role || "";
}

function formatSupport(fileType) {
  return String(fileType || "").toLowerCase() === "pdf"
    ? `<span class="badge approved">Supported for knowledge preparation</span>`
    : `<span class="badge review">Upload supported; preparation not yet supported</span>`;
}

function pageRange(start, end) {
  if (!start) return "N/A";
  return String(start) === String(end) || !end ? String(start) : `${start}-${end}`;
}

function friendlyError(error) {
  return error.message || "Something went wrong. Please try again.";
}

function renderMarkdown(markdown) {
  const blocks = [];
  let text = markdown.replace(/\r\n/g, "\n");
  text = text.replace(/```([\s\S]*?)```/g, (_, code) => {
    const token = `@@CODE${blocks.length}@@`;
    blocks.push(`<pre><code>${escapeHtml(code.trim())}</code></pre>`);
    return token;
  });

  const lines = text.split("\n");
  const html = [];
  let listType = null;
  let paragraph = [];

  function flushParagraph() {
    if (paragraph.length > 0) {
      html.push(`<p>${formatInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  }

  function closeList() {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }
    if (trimmed.startsWith("@@CODE")) {
      flushParagraph();
      closeList();
      html.push(trimmed);
      continue;
    }
    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length + 2;
      html.push(`<h${level}>${formatInline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${formatInline(bullet[1])}</li>`);
      continue;
    }
    const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (numbered) {
      flushParagraph();
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${formatInline(numbered[1])}</li>`);
      continue;
    }
    closeList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  closeList();
  let rendered = html.join("");
  blocks.forEach((block, index) => {
    rendered = rendered.replace(`@@CODE${index}@@`, block);
  });
  return rendered;
}

function formatInline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(String(value || ""));
}
