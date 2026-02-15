/**
 * OnWatch Data Population Hub - Frontend
 *
 * Handles config, exports, population/validation runs, progress display, and results.
 */

// =============================================================================
// DOM references
// =============================================================================

const DOM = {
  configBadge: () => document.getElementById("config-badge"),
  configContent: () => document.getElementById("config-content"),
  configStatusMsg: () => document.getElementById("config-status-msg"),
  exportsList: () => document.getElementById("exports-list"),
  exportSelect: () => document.getElementById("export-select"),
  actionError: () => document.getElementById("action-error"),
  resultsContent: () => document.getElementById("results-content"),
  progressSection: () => document.getElementById("progress-section"),
  progressSource: () => document.getElementById("progress-source"),
  progressBar: () => document.getElementById("progress-bar"),
  progressText: () => document.getElementById("progress-text"),
  progressSteps: () => document.getElementById("progress-steps"),
  progressWarnings: () => document.getElementById("progress-warnings"),
  progressSummary: () => document.getElementById("progress-summary"),
};

// =============================================================================
// State
// =============================================================================

let currentJobId = null;
let latestPopulationResult = null;
let latestValidationResult = null;
let lastRunType = null; // "population" | "validation" — only show result for most recent run

// =============================================================================
// Config
// =============================================================================

async function fetchConfig() {
  try {
    const r = await fetch("/api/config/status");
    const data = await r.json();
    if (data.valid) {
      DOM.configBadge().textContent = "Config ✓";
      DOM.configBadge().className = "badge ok";
      DOM.configContent().innerHTML = `OnWatch: ${data.onwatch_ip || "—"} | Version: ${data.onwatch_version || "—"}`;
    } else {
      DOM.configBadge().textContent = "Config ✗";
      DOM.configBadge().className = "badge error";
      DOM.configContent().innerHTML = `<span class="error-list">${(data.errors || []).join("<br>")}</span>`;
    }
    document.getElementById("config-ip").value = data.onwatch_ip || "";
    document.getElementById("config-version").value = data.onwatch_version || "";
  } catch (e) {
    DOM.configBadge().textContent = "Config ?";
    DOM.configBadge().className = "badge pending";
    DOM.configContent().textContent = "Could not load config status";
  }
}

function showConfigStatus(msg, isError = false) {
  const el = DOM.configStatusMsg();
  el.textContent = msg;
  el.className = "config-status-msg " + (isError ? "error" : "ok");
  setTimeout(() => {
    el.textContent = "";
    el.className = "config-status-msg";
  }, 4000);
}

async function setIp() {
  const ip = document.getElementById("config-ip").value.trim();
  if (!ip) {
    showConfigStatus("IP address is required", true);
    return;
  }
  try {
    const r = await fetch("/api/config/set-ip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
    });
    const data = await r.json();
    if (data.success) {
      showConfigStatus("✓ " + data.message);
      fetchConfig();
    } else {
      showConfigStatus("Error: " + (data.message || "Failed to set IP"), true);
    }
  } catch (e) {
    showConfigStatus("Error: " + e.message, true);
  }
}

async function setVersion() {
  const version = document.getElementById("config-version").value;
  if (!version) {
    showConfigStatus("Please select a version (2.6 or 2.8)", true);
    return;
  }
  try {
    const r = await fetch("/api/config/set-version", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
    const data = await r.json();
    if (data.success) {
      showConfigStatus("✓ " + data.message);
      fetchConfig();
    } else {
      showConfigStatus("Error: " + (data.message || "Failed to set version"), true);
    }
  } catch (e) {
    showConfigStatus("Error: " + e.message, true);
  }
}

// =============================================================================
// Exports
// =============================================================================

async function fetchExports() {
  try {
    const r = await fetch("/api/exports");
    const exports = await r.json();
    DOM.exportsList().innerHTML = exports.length
      ? exports
          .map(
            (e) =>
              `<div class="exports-item">
                <span class="filename">${e.filename}</span>
                <div class="meta">${e.generated_at || ""} | ${e.total_duration || ""} | ${e.successful_steps ?? ""}/${e.total_steps ?? ""} steps</div>
              </div>`
          )
          .join("")
      : "<div class='exports-item'>No export files found. Run population first.</div>";

    DOM.exportSelect().innerHTML =
      '<option value="">-- Select export file --</option>' + exports.map((e) => `<option value="${e.path}">${e.filename}</option>`).join("");
  } catch (e) {
    DOM.exportsList().innerHTML = "<div class='exports-item'>Could not load exports</div>";
  }
}

// =============================================================================
// Progress UI — bar, steps, warnings, summary
// =============================================================================

function clearProgress() {
  DOM.progressBar().style.width = "0%";
  DOM.progressText().textContent = "";
  DOM.progressSteps().innerHTML = "";
  DOM.progressWarnings().innerHTML = "";
  DOM.progressSummary().innerHTML = "";
}

function setActionsEnabled(enabled) {
  document.getElementById("btn-run-population").disabled = !enabled;
  document.getElementById("btn-validate").disabled = !enabled;
  document.getElementById("export-select").disabled = !enabled;
}

function renderProgressSteps(steps) {
  const icon = (s) => (s.status === "success" ? "✓" : s.status === "failed" ? "✗" : s.status === "skipped" ? "⊘" : "⋯");
  const cls = (s) => (s.status === "running" ? "running" : s.status);
  DOM.progressSteps().innerHTML = steps.map((s) => `<div class="progress-step ${cls(s)}">${icon(s)} ${s.name}</div>`).join("");
}

function renderProgressWarnings(warnings) {
  const filtered = warnings.filter((w) => (w.message || "").trim());
  DOM.progressWarnings().innerHTML = filtered
    .map((w) => `<div class="progress-warning ${w.type}">${w.type === "error" ? "✗" : "⚠️"} ${escapeHtml(w.message)}</div>`)
    .join("");
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function showValidationError(message) {
  DOM.actionError().innerHTML = `<div class="action-error-card">
    <strong>⚠️ ${escapeHtml(message)}</strong>
    <span>Select an export file from the dropdown above, then click Validate.</span>
  </div>`;
  DOM.actionError().classList.add("visible");
  DOM.exportSelect().focus();
  DOM.exportSelect().classList.add("input-error");
  setTimeout(() => DOM.exportSelect().classList.remove("input-error"), 2000);
}

function clearActionError() {
  DOM.actionError().innerHTML = "";
  DOM.actionError().classList.remove("visible");
}

// =============================================================================
// Progress event handlers — process SSE events and update UI
// =============================================================================

function handleProgressEvent(ev, jobType, ctx) {
  const { steps, total } = ctx;

  if (ev.type === "step_start") {
    const t = ev.total || 11;
    steps.push({ num: ev.step, name: ev.name, status: "running" });
    DOM.progressBar().style.width = `${((ev.step - 1) / t) * 100}%`;
    DOM.progressText().textContent = `Step ${ev.step}/${t}: ${ev.name}...`;
    renderProgressSteps(steps);
    return;
  }

  if (ev.type === "step_done") {
    const s = steps.find((x) => x.num === ev.step);
    if (s) s.status = ev.status;
    const t = ev.total || total || 11;
    DOM.progressBar().style.width = `${(ev.step / t) * 100}%`;
    DOM.progressText().textContent = `Step ${ev.step}/${t}: ${ev.name} — ${ev.status}`;
    renderProgressSteps(steps);
    return;
  }

  if (ev.type === "category_start" && jobType === "validation") {
    const t = ev.total || 1;
    steps.push({ name: ev.name, status: "running", isCategory: true });
    DOM.progressBar().style.width = `${((ev.current || 0) / t) * 100}%`;
    DOM.progressText().textContent = `Validating ${ev.name}...`;
    renderProgressSteps(steps);
    return;
  }

  if (ev.type === "category_done") {
    const s = steps.find((x) => x.name === ev.name && x.isCategory);
    if (s) s.status = "success";
    renderProgressSteps(steps);
    return;
  }

  if (ev.type === "warning") {
    const msg = (ev.message || "").trim();
    if (msg) {
      ctx.warnings.push({ type: "warning", message: msg });
      renderProgressWarnings(ctx.warnings);
    }
    return;
  }

  if (ev.type === "error") {
    const msg = (ev.message || "").trim();
    if (msg) {
      ctx.warnings.push({ type: "error", message: msg });
      renderProgressWarnings(ctx.warnings);
    }
    return;
  }

  if (ev.type === "complete") {
    DOM.progressBar().style.width = "100%";
    if (jobType === "population" && ev.run_status) {
      const rs = ev.run_status;
      DOM.progressText().textContent = `Done: ${rs.successful_steps ?? 0}/${rs.total_steps ?? 0} steps | ${ev.duration || ""}`;
      DOM.progressSummary().innerHTML = buildPopulationCompleteSummary(ev);
      // Update Results section from complete event (fallback if pollStatus hasn't run yet)
      lastRunType = "population";
      latestPopulationResult = {
        success: ev.success,
        run_status: ev.run_status,
        duration: ev.duration,
        export_path: ev.export_path,
        error: ev.error,
      };
      renderResults();
    }
    if (jobType === "validation" && ev.passed !== undefined) {
      DOM.progressText().textContent = `Done: ${ev.passed} passed, ${ev.failed} failed`;
      DOM.progressSummary().innerHTML = buildValidationCompleteSummary(ev);
      // Update Results section from complete event
      lastRunType = "validation";
      latestValidationResult = {
        success: ev.success,
        passed: ev.passed,
        failed: ev.failed,
        validated: ev.validated,
        errors: ev.errors || [],
        acknowledged: ev.acknowledged || [],
        manual_checklist: ev.manual_checklist || [],
        error: ev.error,
      };
      renderResults();
    }
  }
}

function buildPopulationCompleteSummary(ev) {
  const rs = ev.run_status || {};
  return `<div class="summary-card ${ev.success ? "success" : "failure"}">
    <strong>${ev.success ? "✓ Population complete" : "✗ Population had failures"}</strong>
    <div class="detail">${rs.successful_steps ?? 0} successful, ${rs.failed_steps ?? 0} failed, ${rs.skipped_steps ?? 0} skipped | ${ev.duration || ""}</div>
    ${ev.export_path ? `<div class="detail">Export: ${ev.export_path.split("/").pop()}</div>` : ""}
    ${(ev.warnings || []).length ? `<div class="warnings-inline">⚠️ ${ev.warnings.length} warning(s)</div>` : ""}
  </div>`;
}

function buildValidationCompleteSummary(ev) {
  return `<div class="summary-card ${ev.success ? "success" : "failure"}">
    <strong>${ev.success ? "✓ Validation passed" : "✗ Validation had failures"}</strong>
    <div class="detail">${ev.passed} passed, ${ev.failed} failed (${ev.validated} validated)</div>
    ${(ev.errors || []).length ? `<ul class="errors-list">${(ev.errors || []).map((err) => `<li>${err}</li>`).join("")}</ul>` : ""}
    ${(ev.manual_checklist || []).length ? `<ul class="checklist">${(ev.manual_checklist || []).map((c) => `<li>${c}</li>`).join("")}</ul>` : ""}
  </div>`;
}

// =============================================================================
// Progress stream — connect EventSource, handle events
// =============================================================================

function streamProgress(jobId, jobType) {
  currentJobId = jobId;
  setActionsEnabled(false);
  clearProgress();
  DOM.progressSource().textContent = `(${jobType})`;

  const ctx = { steps: [], warnings: [], total: jobType === "population" ? 11 : 0 };

  const es = new EventSource(`/api/progress/${jobId}`);
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      if (ev.type === "stream_done") {
        es.close();
        pollStatus(jobId, jobType);
        setActionsEnabled(true);
        currentJobId = null;
        DOM.progressSource().textContent = "";
        return;
      }
      handleProgressEvent(ev, jobType, ctx);
    } catch (_) {}
  };
  es.onerror = () => {
    es.close();
    pollStatus(jobId, jobType);
    setActionsEnabled(true);
    currentJobId = null;
    DOM.progressSource().textContent = "";
  };
}

// =============================================================================
// Job status polling and results
// =============================================================================

async function pollStatus(jobId, jobType) {
  const maxAttempts = 30;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const r = await fetch(`/api/status/${jobId}`);
      const data = await r.json();
      if (data.status === "done") {
        lastRunType = jobType;
        if (jobType === "population") {
          latestPopulationResult = data.result;
        } else {
          latestValidationResult = data.result;
        }
        renderResults();
        fetchExports();
        break;
      }
    } catch (_) {}
    await new Promise((r) => setTimeout(r, 500));
  }
}

function renderResults() {
  let html = "";
  if (lastRunType === "population" && latestPopulationResult) {
    html = buildPopulationResultCard(latestPopulationResult);
  } else if (lastRunType === "validation" && latestValidationResult) {
    html = buildValidationResultCard(latestValidationResult);
  }
  if (!html) {
    html = `<div class="results-empty">
      <p class="results-empty-text">No runs yet.</p>
      <p class="results-empty-hint">Run <strong>Population</strong> first, then select an export file and run <strong>Validate</strong> to check data after upgrade.</p>
    </div>`;
  }
  DOM.resultsContent().innerHTML = html;
}

function buildPopulationResultCard(r) {
  const status = r.success ? "success" : "failure";
  const rs = r.run_status || {};
  return `<div class="result-card ${status}">
    <h3>Population: ${r.success ? "✓" : "✗"} ${rs.successful_steps ?? "?"}/${rs.total_steps ?? "?"} steps</h3>
    <div class="detail">${r.duration || ""} | Export: ${r.export_path ? r.export_path.split("/").pop() : "—"}</div>
    ${r.error ? `<div class="errors-list"><ul><li>${r.error}</li></ul></div>` : ""}
  </div>`;
}

function buildValidationResultCard(r) {
  const status = r.success ? "success" : "failure";
  return `<div class="result-card ${status}">
    <h3>Validation: ${r.success ? "✓" : "✗"} Passed ${r.passed ?? 0} | Failed ${r.failed ?? 0}</h3>
    <div class="detail">Acknowledged: ${(r.acknowledged || []).map((a) => a[0]).join(", ") || "—"}</div>
    ${(r.errors || []).length ? `<div class="errors-list"><ul>${(r.errors || []).map((e) => `<li>${e}</li>`).join("")}</ul></div>` : ""}
    ${(r.manual_checklist || []).length ? `<ul class="checklist">${(r.manual_checklist || []).map((c) => `<li>${c}</li>`).join("")}</ul>` : ""}
    ${r.error ? `<div class="errors-list"><ul><li>${r.error}</li></ul></div>` : ""}
  </div>`;
}

// =============================================================================
// Actions — run population, run validation
// =============================================================================

async function runPopulation() {
  if (currentJobId) return;
  clearActionError();
  try {
    const r = await fetch("/api/run-population", { method: "POST" });
    const data = await r.json();
    if (data.job_id) {
      streamProgress(data.job_id, "population");
    } else {
      DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${data.error || "Unknown error"}</div>`;
    }
  } catch (e) {
    DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${e.message}</div>`;
  }
}

async function runValidation() {
  if (currentJobId) return;
  clearActionError();
  const file = DOM.exportSelect().value;
  if (!file) {
    showValidationError("Please select an export file (last population run) to validate against.");
    return;
  }
  try {
    const r = await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file }),
    });
    const data = await r.json();
    if (data.job_id) {
      streamProgress(data.job_id, "validation");
    } else {
      DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${data.error || "Unknown error"}</div>`;
    }
  } catch (e) {
    DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${e.message}</div>`;
  }
}

// =============================================================================
// Init
// =============================================================================

document.getElementById("btn-run-population").addEventListener("click", runPopulation);
document.getElementById("btn-validate").addEventListener("click", runValidation);
document.getElementById("btn-refresh-exports").addEventListener("click", fetchExports);
document.getElementById("btn-set-ip").addEventListener("click", setIp);
document.getElementById("btn-set-version").addEventListener("click", setVersion);

fetchConfig();
fetchExports();
renderResults();
