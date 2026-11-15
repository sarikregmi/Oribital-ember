// The frontend talks only to the local FastAPI JSON contract.
const apiBase = "";
const state = { investigations: [], selectedId: null };

// Cache the small set of UI elements used by search, rendering, and the inspector.
const elements = {
  search: document.querySelector("#search"),
  question: document.querySelector("#question"),
  askButton: document.querySelector("#ask-button"),
  scenarioAskButton: document.querySelector("#scenario-ask-button"),
  answer: document.querySelector("#answer"),
  scenarioMaterial: document.querySelector("#scenario-material"),
  scenarioOxygen: document.querySelector("#scenario-oxygen"),
  scenarioPressure: document.querySelector("#scenario-pressure"),
  scenarioAirflow: document.querySelector("#scenario-airflow"),
  scenarioGravity: document.querySelector("#scenario-gravity"),
  scenarioThickness: document.querySelector("#scenario-thickness"),
  domain: document.querySelector("#domain"),
  status: document.querySelector("#status"),
  resultTitle: document.querySelector("#result-title"),
  resultCount: document.querySelector("#result-count"),
  results: document.querySelector("#results"),
  savedResources: document.querySelector("#saved-resources"),
  psiArchive: document.querySelector("#psi-archive"),
  insight: document.querySelector("#insight-panel"),
};

// Switch complete workflows without duplicating their state or API behavior.
function setView(viewId) {
  document.querySelectorAll(".app-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === viewId));
  document.querySelectorAll(".app-view").forEach((view) => view.classList.toggle("active-view", view.dataset.view === viewId));
}

// Show the exact slider context returned by the backend on the Evidence tab.
function scenarioSummary(scenario) {
  if (!scenario) return "No custom scenario supplied.";
  return Object.entries(scenario)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
    .join(" · ");
}

// Render suggested next questions without making the user select another record.
function followUpQuestions(questions) {
  return questions?.length
    ? `<div class="follow-ups"><strong>Ask next</strong>${questions.map((question) => `<button type="button" class="follow-up">${escapeHtml(question)}</button>`).join("")}</div>`
    : "";
}

// Keep official data suggestions visible even when external search permission is off.
function dataSuggestions(sources) {
  return sources?.length
    ? `<div class="data-suggestions"><strong>Where to get more data</strong>${sources.map((source) => `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.title)}</a>`).join("")}</div>`
    : "";
}

// Read the sliders as user context; the backend does not turn them into fake measurements.
function readScenario() {
  return {
    material: elements.scenarioMaterial.value || null,
    oxygen_percent: Number(elements.scenarioOxygen.value),
    pressure_atm: Number(elements.scenarioPressure.value),
    airflow_cm_s: Number(elements.scenarioAirflow.value),
    gravity_g: Number(elements.scenarioGravity.value),
    thickness_mm: Number(elements.scenarioThickness.value),
  };
}

// Keep slider labels synchronized so a question always has visible numeric context.
function syncScenarioLabels() {
  document.querySelector("#scenario-oxygen-value").textContent = `${elements.scenarioOxygen.value}%`;
  document.querySelector("#scenario-pressure-value").textContent = `${Number(elements.scenarioPressure.value).toFixed(2)} atm`;
  document.querySelector("#scenario-airflow-value").textContent = `${elements.scenarioAirflow.value} cm/s`;
  document.querySelector("#scenario-gravity-value").textContent = `${Number(elements.scenarioGravity.value).toFixed(2)} g`;
  document.querySelector("#scenario-thickness-value").textContent = `${Number(elements.scenarioThickness.value).toFixed(2)} mm`;
}

// Collect the scoped resource set before exposing the main interface.
async function bootstrapResources() {
  const message = document.querySelector("#startup-message");
  try {
    const response = await fetch(`${apiBase}/api/v1/psi/archive`);
    if (!response.ok) throw new Error("PSI archive status unavailable");
    const data = await response.json();
    const storage = data.storage || {};
    message.textContent = `Bundled NASA PSI archive: ${storage.investigations || 0} investigations · ${storage.downloaded_files || 0} files downloaded · 12 GB PSI-only limit. Checking for updates...`;
    renderPsiArchive(data);
  } catch (error) {
    message.textContent = "NASA PSI archive is not available yet. Connect to the internet and refresh the index.";
  }
  document.querySelector("#startup-loader").classList.add("hidden");
}

function renderPsiArchive(data) {
  if (!elements.psiArchive) return;
  const storage = data.storage || {};
  const files = data.files || [];
  const downloaded = files.filter((file) => file.downloaded);
  const queued = files.filter((file) => !file.downloaded);
  const size = (bytes) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  elements.psiArchive.innerHTML = `
    <div class="section-heading"><div><h2>NASA PSI research archive</h2><p class="muted">${storage.investigations || 0} investigations · ${storage.listed_files || 0} listed files · ${downloaded.length} downloaded</p></div><span class="count">${size(storage.storage_bytes || 0)} / 12 GB</span></div>
    <div class="startup-progress"><i style="width:${Math.min(100, storage.storage_percent || 0)}%"></i></div>
    <p class="muted">The 12 GB limit applies only to PSI files. PDFs, datasets and supporting documents are downloaded in small batches. Other Orbital Ember sources use separate storage.</p>
    <button id="sync-psi-batch" type="button" class="resource-analyze">Download next PSI update batch</button>
    ${downloaded.length ? `<h3>Downloaded PSI files</h3><div class="saved-list">${downloaded.slice(0, 30).map((file) => `<article class="saved-resource"><div class="resource-title"><strong>${escapeHtml(file.name)}</strong><span class="resource-size">${size(file.size_bytes || 0)}</span></div><span>${escapeHtml(file.investigation_id || "NASA PSI")} · ${escapeHtml(file.category || "file")}</span><a href="/api/v1/psi/files/${encodeURIComponent(file.id)}/download">Open local file</a></article>`).join("")}</div>` : `<p class="muted">No PSI files have been bundled or downloaded yet.</p>`}
    ${queued.length ? `<p class="muted">${queued.length} more PSI files are listed and waiting for later download batches.</p>` : ""}
  `;
  document.querySelector("#sync-psi-batch")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Checking NASA and downloading...";
    try {
      const response = await fetch(`${apiBase}/api/v1/investigations/sync`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "PSI update failed");
      const refreshed = await fetch(`${apiBase}/api/v1/psi/archive`);
      renderPsiArchive(await refreshed.json());
      await loadInvestigations();
    } catch (error) {
      button.textContent = `Update failed: ${error.message}`;
    } finally {
      if (document.querySelector("#sync-psi-batch")) {
        const next = document.querySelector("#sync-psi-batch");
        next.disabled = false;
        next.textContent = "Download next PSI update batch";
      }
    }
  });
}

// Visualize counts returned by the API, rather than inventing physical measurements.
function evidenceProfile(data) {
  const investigations = data.matched_investigations || [];
  if (!investigations.length) return `<p class="muted">No local investigation matched this question. The answer above is a general explanation; use the source links to continue.</p>`;
  const unique = (key) => new Set(investigations.flatMap((item) => item[key] || [])).size;
  const values = [
    ["Matched investigations", investigations.length],
    ["Gravity contexts", unique("gravity")],
    ["Measured categories", unique("measurements")],
    ["Research sources", (data.sources || []).length],
  ];
  const max = Math.max(...values.map((entry) => entry[1]), 1);
  return `<div class="evidence-profile">${values.map(([label, value]) => `
    <div class="evidence-row"><span>${escapeHtml(label)}</span><div class="evidence-track"><i style="width:${(value / max) * 100}%"></i></div><b>${value}</b></div>
  `).join("")}</div>`;
}

// Ask the backend to search the whole local catalog before it considers outside sources.
async function askAcrossCatalog(allowExternal = true) {
  const question = elements.question.value.trim();
  if (!question) return;
  elements.askButton.disabled = true;
  elements.askButton.textContent = "Searching...";
  elements.answer.innerHTML = `<p class="muted">Checking local PSI investigations first.</p>`;
  try {
    const response = await fetch(`${apiBase}/api/v1/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        allow_external_search: allowExternal,
        include_nasa_search: allowExternal,
        include_web_search: allowExternal,
        scenario: readScenario(),
      }),
    });
    if (!response.ok) throw new Error("Ask request failed");
    const data = await response.json();
    state.investigations = data.matched_investigations;
    const pathLabels = {
      "local": "Local PSI evidence",
      "local+nasa-web": "Local PSI + live NASA/web research",
      "local+cached": "Local PSI + saved research",
      "local+external-unavailable": "Offline research mode",
    };
    elements.answer.innerHTML = `
      <p class="eyebrow">${escapeHtml(pathLabels[data.search_path] || data.search_path)}</p>
      <h2>Answer</h2>
      <p class="answer-text">${escapeHtml(data.answer).replaceAll("\n", "<br>")}</p>
      <p class="scenario-readout"><strong>Scenario used:</strong> ${escapeHtml(scenarioSummary(data.scenario))}</p>
      ${evidenceProfile(data)}
      ${tags(data.sources.map((source) => `${source.source_type}: ${source.title}`))}
      ${followUpQuestions(data.follow_up_questions)}
      ${dataSuggestions(data.recommended_data_sources)}
      <p class="muted">Saved research files: ${data.saved_resources.length}</p>
    `;
    document.querySelectorAll(".follow-up").forEach((button) => {
      button.addEventListener("click", () => {
        elements.question.value = button.textContent;
        setView("ask-view");
        askAcrossCatalog(true);
      });
    });
    if (data.matched_investigations.length) {
      renderResults({ query: question, total: data.matched_investigations.length, results: data.matched_investigations });
    }
  } catch (error) {
    elements.answer.innerHTML = `<p class="notice">The AI search could not be reached.</p>`;
  } finally {
    elements.askButton.disabled = false;
    elements.askButton.textContent = "Ask AI";
    setView("evidence-view");
  }
}

// Escape server text before inserting it into HTML because catalog data is external input.
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Only permit ordinary web links for source records; HTML escaping alone does not block javascript: URLs.
function safeExternalUrl(value) {
  try {
    const url = new URL(String(value), window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}

// Convert a list into compact tags while keeping empty metadata unobtrusive.
function tags(values) {
  return values?.length
    ? `<div class="tag-row">${values.map((value) => `<span class="tag">${escapeHtml(value)}</span>`).join("")}</div>`
    : "";
}

// Render real local download records separately from the fixed investigation catalog.
function renderSavedResources(resources) {
  if (!resources.length) {
    elements.savedResources.innerHTML = `${resourceHeading(0)}${resourceImportForm()}<p id="other-resource-status" class="muted" role="status">No other research datasets imported yet. These files use storage separate from the NASA PSI archive.</p>`;
    wireResourceActions();
    return;
  }
  elements.savedResources.innerHTML = `
    ${resourceHeading(resources.length)}
    <p id="other-resource-status" class="muted" role="status">Imported research resources are stored separately from the NASA PSI archive and its 12 GB quota.</p>
    ${resourceImportForm()}
    <div class="saved-list">${resources.map((item) => `
      <article class="saved-resource">
        <div class="resource-title"><strong>${escapeHtml(item.title)}</strong><span class="resource-size">${(item.size_bytes / 1024).toFixed(1)} KB</span></div>
        <span>${escapeHtml(item.provider || item.source_type)} · ${escapeHtml(item.filename)} · ${escapeHtml(item.snippet || "No source description supplied")}</span>
        <div class="resource-actions">
          <a href="${apiBase}/api/v1/resources/${encodeURIComponent(item.id)}/download">Download saved file</a>
          <a href="${escapeHtml(safeExternalUrl(item.url))}" target="_blank" rel="noopener noreferrer">Original source</a>
          ${item.analysis_supported ? `<button type="button" class="resource-analyze" data-resource-id="${escapeHtml(item.id)}">Analyze dataset</button>` : `<span class="muted">Reference file · tabular analysis unavailable</span>`}
        </div>
      </article>
    `).join("")}</div>
    <div id="dataset-analysis" class="dataset-analysis" aria-live="polite"></div>
  `;
  elements.savedResources.querySelectorAll("[data-resource-id]").forEach((button) => {
    button.addEventListener("click", () => analyzeResource(button.dataset.resourceId, button));
  });
  wireResourceActions();
}

function resourceHeading(count) {
  return `<div class="saved-heading"><span class="eyebrow">OTHER IMPORTED RESEARCH FILES</span><span class="count">${count} local files</span></div>`;
}

function wireResourceActions() {
  document.querySelector("#resource-import-form")?.addEventListener("submit", importNasaDataset);
}

function resourceImportForm() {
  return `<form id="resource-import-form" class="resource-import">
    <strong>Import another NASA research dataset</strong>
    <label>Dataset file <input id="resource-file" name="file" type="file" accept=".csv,.tsv,.json,.jsonl,.zip" required></label>
    <label>NASA source page URL <input id="resource-source-url" name="source_url" type="url" placeholder="https://psi.nasa.gov/..." required></label>
    <button class="resource-analyze" type="submit">Save downloaded record</button>
    <span id="resource-import-status" class="muted" role="status"></span>
  </form>`;
}

async function importNasaDataset(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const status = form.querySelector("#resource-import-status");
  const file = form.querySelector("#resource-file").files[0];
  if (!file) return;
  const data = new FormData();
  data.append("file", file);
  data.append("source_url", form.querySelector("#resource-source-url").value.trim());
  data.append("title", file.name);
  status.textContent = "Saving file and source provenance...";
  try {
    const response = await fetch(`${apiBase}/api/v1/resources/import`, { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Import failed");
    status.textContent = `Saved ${payload.filename}.`;
    await loadInvestigations();
  } catch (error) {
    status.textContent = error.message;
  }
}

// Request descriptive statistics from the backend and render traceable numeric plots.
async function analyzeResource(resourceId, button) {
  const panel = document.querySelector("#dataset-analysis");
  if (!panel) return;
  button.disabled = true;
  button.textContent = "Analyzing...";
  panel.innerHTML = `<p class="muted">Reading the downloaded dataset...</p>`;
  try {
    const response = await fetch(`${apiBase}/api/v1/resources/${encodeURIComponent(resourceId)}/analysis`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Dataset analysis failed");
    const analysis = payload.analysis;
    const datasets = analysis.format === "ZIP" ? analysis.datasets : [{ file_name: payload.file_name, analysis }];
    panel.innerHTML = `
      <div class="analysis-heading"><p class="eyebrow">DATASET ANALYSIS</p><h3>${escapeHtml(payload.title)}</h3>
        <p class="muted">${escapeHtml(analysis.format)} · ${escapeHtml(payload.file_name)} · ${payload.file_size_bytes.toLocaleString()} bytes</p>
        <a href="${escapeHtml(safeExternalUrl(payload.source_url))}" target="_blank" rel="noopener noreferrer">Verify original source</a>
      </div>
      ${datasets.map((dataset) => renderDatasetDetails(dataset.file_name, dataset.analysis)).join("")}
      <p class="science-notice">${escapeHtml(analysis.notice || "")} </p>
    `;
  } catch (error) {
    panel.innerHTML = `<p class="notice">${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "Analyze dataset";
  }
}

function renderDatasetDetails(fileName, analysis) {
  return `<section class="dataset-file"><h4>${escapeHtml(fileName)} · ${analysis.row_count.toLocaleString()} rows · ${analysis.column_count} columns</h4>
    <div class="column-analysis">${analysis.columns.map((column) => `
      <article class="column-card"><h4>${escapeHtml(column.name)}</h4>
        <p class="muted">${column.type} · ${column.non_empty} values · ${column.missing} missing</p>
        ${column.type === "numeric" ? `
          <div class="numeric-stats"><span>Min <b>${column.min}</b></span><span>Mean <b>${column.mean}</b></span><span>Median <b>${column.median}</b></span><span>Max <b>${column.max}</b></span></div>
          ${renderSeries(column.series || [])}` : `
          <div class="category-stats">${(column.top_values || []).map((entry) => `<span>${escapeHtml(entry.value)} <b>${entry.count}</b></span>`).join("")}</div>`}
      </article>`).join("")}</div>
    <details><summary>Preview first ${analysis.sample_rows.length} records</summary><pre>${escapeHtml(JSON.stringify(analysis.sample_rows, null, 2))}</pre></details>
    <p class="science-notice">${escapeHtml(analysis.notice)}${analysis.truncated ? " The dataset was truncated at the analysis row limit." : ""}</p>
  </section>`;
}

function renderSeries(values) {
  if (values.length < 2) return `<p class="muted">Not enough numeric values to plot.</p>`;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 300},${90 - ((value - min) / span) * 80}`).join(" ");
  return `<svg class="dataset-plot" viewBox="0 0 300 100" role="img" aria-label="Values across the first ${values.length} observations"><polyline points="${points}" fill="none" stroke="#78d6ba" stroke-width="2" vector-effect="non-scaling-stroke"/><line x1="0" y1="90" x2="300" y2="90" stroke="#263a3a"/></svg><span class="plot-caption">First ${values.length} valid observations · normalized within this column</span>`;
}

// Fetch the ranked catalog whenever the user changes search or domain filters.
async function loadInvestigations() {
  const params = new URLSearchParams({ q: elements.search.value, limit: "20" });
  if (elements.domain.value) params.set("domain", elements.domain.value);
  elements.resultTitle.textContent = "Searching investigations";
  try {
    const [response, resourceResponse, archiveResponse] = await Promise.all([
      fetch(`${apiBase}/api/v1/investigations?${params}`),
      fetch(`${apiBase}/api/v1/resources`),
      fetch(`${apiBase}/api/v1/psi/archive`),
    ]);
    if (!response.ok || !resourceResponse.ok || !archiveResponse.ok) throw new Error("Search request failed");
    const data = await response.json();
    renderSavedResources(await resourceResponse.json());
    renderPsiArchive(await archiveResponse.json());
    state.investigations = data.results;
    elements.status.textContent = "Local API connected";
    elements.status.classList.remove("offline");
    renderResults(data);
  } catch (error) {
    elements.status.textContent = "API offline";
    elements.status.classList.add("offline");
    elements.resultTitle.textContent = "Backend unavailable";
    elements.results.innerHTML = `<p class="notice">Start the Python app, then reload this window.</p>`;
  }
}

// Render cards from API data without hiding the score or the source signals.
function renderResults(data) {
  elements.resultTitle.textContent = data.query ? `Matches for “${escapeHtml(data.query)}”` : "NASA investigation catalog";
  elements.resultCount.textContent = `${data.total} NASA records`;
  if (!data.results.length) {
    elements.results.innerHTML = `<p class="notice">No NASA PSI records are in this archive yet. Run the PSI archive build on an internet-connected machine, or use “Refresh NASA index” to retry. The app will not substitute sample records.</p>`;
    return;
  }
  elements.results.innerHTML = data.results.map((item) => `
    <article class="result-card ${state.selectedId === item.id ? "selected" : ""}" data-id="${escapeHtml(item.id)}">
      <div>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.description)}</p>
        ${tags([item.domain, ...item.gravity])}
      </div>
      <span class="score">${item.relevance_score.toFixed(1)} relevance</span>
    </article>
  `).join("");
  document.querySelectorAll(".result-card").forEach((card) => {
    card.addEventListener("click", () => selectInvestigation(card.dataset.id));
  });
}

// Show the selected record and request a grounded explanation only on user action.
function selectInvestigation(id) {
  state.selectedId = id;
  const item = state.investigations.find((candidate) => candidate.id === id);
  if (!item) return;
  renderResults({ query: elements.search.value, total: state.investigations.length, results: state.investigations });
  elements.insight.innerHTML = `
    <p class="eyebrow">GROUNDED INSIGHT</p>
    <h2>${escapeHtml(item.name)}</h2>
    <p class="muted">${escapeHtml(item.description)}</p>
    <dl class="detail-list">
      <div><dt>Fuel</dt><dd>${escapeHtml(item.fuels.join(", ") || "Not specified")}</dd></div>
      <div><dt>Conditions</dt><dd>${escapeHtml(item.conditions.join(", ") || "Not specified")}</dd></div>
      <div><dt>Measurements</dt><dd>${escapeHtml(item.measurements.join(", ") || "Not specified")}</dd></div>
    </dl>
    <button class="insight-button" id="explain">Generate local explanation</button>
    <div id="explanation" class="muted" aria-live="polite"></div>
  `;
  document.querySelector("#explain").addEventListener("click", () => explain(item.id));
}

// Ask the backend AI boundary and display its mode so the result remains transparent.
async function explain(id) {
  const button = document.querySelector("#explain");
  const output = document.querySelector("#explanation");
  button.disabled = true;
  button.textContent = "Preparing explanation...";
  try {
    const response = await fetch(`${apiBase}/api/v1/investigations/${encodeURIComponent(id)}/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: elements.question.value.trim() || "Explain the fire-safety meaning of this investigation.",
        include_nasa_search: true,
        include_web_search: true,
      }),
    });
    if (!response.ok) throw new Error("Explanation request failed");
    const data = await response.json();
    output.innerHTML = `<p><strong>${escapeHtml(data.ai_mode)}</strong><br>${escapeHtml(data.direct_answer)}</p>${tags(data.fire_safety_implications)}${followUpQuestions(data.follow_up_questions)}${dataSuggestions(data.recommended_data_sources)}<p>${data.limitations.map(escapeHtml).join(" ")}</p>`;
    document.querySelectorAll(".follow-up").forEach((button) => {
      button.addEventListener("click", () => {
        elements.question.value = button.textContent;
        setView("ask-view");
        askAcrossCatalog(true);
      });
    });
  } catch (error) {
    output.innerHTML = `<p class="notice">Could not generate an explanation.</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "Generate local explanation";
  }
}

// Debounce typing so the local API is not queried on every keystroke.
let searchTimer;
elements.search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadInvestigations, 180);
});
elements.domain.addEventListener("change", loadInvestigations);
elements.askButton.addEventListener("click", () => askAcrossCatalog(true));
elements.scenarioAskButton.addEventListener("click", () => {
  if (!elements.question.value.trim()) elements.question.value = "Explain this custom spacecraft fire-safety scenario.";
  askAcrossCatalog(true);
});
elements.question.addEventListener("keydown", (event) => {
  if (event.key === "Enter") askAcrossCatalog(true);
});
document.querySelectorAll(".app-tab").forEach((tab) => {
  tab.addEventListener("click", () => setView(tab.dataset.view));
});
document.querySelectorAll("#scenario-material, #scenario-oxygen, #scenario-pressure, #scenario-airflow, #scenario-gravity, #scenario-thickness").forEach((control) => {
  control.addEventListener("input", syncScenarioLabels);
  control.addEventListener("change", syncScenarioLabels);
});
syncScenarioLabels();
async function refreshInvestigationIndex() {
  const button = document.querySelector("#refresh-investigations");
  if (!button) return;
  button.disabled = true;
  button.textContent = "Refreshing...";
  try {
    const response = await fetch(`${apiBase}/api/v1/investigations/sync`, { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "NASA index refresh failed");
    await loadInvestigations();
    if (result.status === "unavailable") {
      elements.resultCount.textContent = "NASA unavailable";
    }
  } catch (error) {
    elements.results.innerHTML = `<p class="notice">Could not refresh the NASA investigation index: ${escapeHtml(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "Refresh NASA index";
  }
}

document.querySelector("#refresh-investigations")?.addEventListener("click", refreshInvestigationIndex);

bootstrapResources().finally(loadInvestigations);
