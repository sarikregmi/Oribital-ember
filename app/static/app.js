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
    const response = await fetch(`${apiBase}/api/v1/resources/bootstrap`, { method: "POST" });
    if (!response.ok) throw new Error("Resource bootstrap failed");
    const data = await response.json();
    message.textContent = `Saved ${data.saved_resources.length} research files. Starting interface...`;
  } catch (error) {
    message.textContent = "Live research was unavailable. Starting with local catalog data...";
  }
  document.querySelector("#startup-loader").classList.add("hidden");
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

// Convert a list into compact tags while keeping empty metadata unobtrusive.
function tags(values) {
  return values?.length
    ? `<div class="tag-row">${values.map((value) => `<span class="tag">${escapeHtml(value)}</span>`).join("")}</div>`
    : "";
}

// Render downloaded source files separately so they are not mistaken for investigations.
function renderSavedResources(resources) {
  if (!resources.length) {
    elements.savedResources.innerHTML = "";
    return;
  }
  elements.savedResources.innerHTML = `
    <div class="saved-heading"><span class="eyebrow">DOWNLOADED RESEARCH</span><span class="count">${resources.length} saved sources</span></div>
    <div class="saved-list">${resources.map((source) => `
      <a class="saved-resource" href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">
        <strong>${escapeHtml(source.title)}</strong><span>${escapeHtml(source.source_type)} · ${escapeHtml(source.snippet)}</span>
      </a>
    `).join("")}</div>
  `;
}

// Fetch the ranked catalog whenever the user changes search or domain filters.
async function loadInvestigations() {
  const params = new URLSearchParams({ q: elements.search.value, limit: "20" });
  if (elements.domain.value) params.set("domain", elements.domain.value);
  elements.resultTitle.textContent = "Searching investigations";
  try {
    const [response, resourceResponse] = await Promise.all([
      fetch(`${apiBase}/api/v1/investigations?${params}`),
      fetch(`${apiBase}/api/v1/resources`),
    ]);
    if (!response.ok || !resourceResponse.ok) throw new Error("Search request failed");
    const data = await response.json();
    renderSavedResources(await resourceResponse.json());
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
  elements.resultTitle.textContent = data.query ? `Matches for “${escapeHtml(data.query)}”` : "All investigations";
  elements.resultCount.textContent = `${data.total} records`;
  if (!data.results.length) {
    elements.results.innerHTML = `<p class="muted">No investigations matched that search.</p>`;
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
bootstrapResources().finally(loadInvestigations);
