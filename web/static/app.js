const logEl = document.getElementById("log-output");
const configBadge = document.getElementById("config-badge");
const configContent = document.getElementById("config-content");
const exportsList = document.getElementById("exports-list");
const exportSelect = document.getElementById("export-select");
const resultsContent = document.getElementById("results-content");
const logSource = document.getElementById("log-source");

let currentJobId = null;
let latestPopulationResult = null;
let latestValidationResult = null;

async function fetchConfig() {
  try {
    const r = await fetch("/api/config/status");
    const data = await r.json();
    if (data.valid) {
      configBadge.textContent = "Config ✓";
      configBadge.className = "badge ok";
      configContent.innerHTML = `OnWatch: ${data.onwatch_ip || "—"} | Version: ${data.onwatch_version || "—"}`;
    } else {
      configBadge.textContent = "Config ✗";
      configBadge.className = "badge error";
      configContent.innerHTML = `<span class="error-list">${(data.errors || []).join("<br>")}</span>`;
    }
  } catch (e) {
    configBadge.textContent = "Config ?";
    configBadge.className = "badge pending";
    configContent.textContent = "Could not load config status";
  }
}

async function fetchExports() {
  try {
    const r = await fetch("/api/exports");
    const exports = await r.json();
    exportsList.innerHTML = exports.length
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

    exportSelect.innerHTML = '<option value="">-- Select export file --</option>' + exports.map((e) => `<option value="${e.path}">${e.filename}</option>`).join("");
  } catch (e) {
    exportsList.innerHTML = "<div class='exports-item'>Could not load exports</div>";
  }
}

function appendLog(line) {
  if (line === "[DONE]") return;
  logEl.textContent += line + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLogs() {
  logEl.textContent = "";
}

function streamLogs(jobId, jobType) {
  currentJobId = jobId;
  logSource.textContent = `(${jobType})`;
  const es = new EventSource(`/api/logs/${jobId}`);
  es.onmessage = (e) => {
    appendLog(e.data);
    if (e.data === "[DONE]") {
      es.close();
      pollStatus(jobId, jobType);
    }
  };
  es.onerror = () => {
    es.close();
    pollStatus(jobId, jobType);
  };
}

async function pollStatus(jobId, jobType) {
  const maxAttempts = 30;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const r = await fetch(`/api/status/${jobId}`);
      const data = await r.json();
      if (data.status === "done") {
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
  if (latestPopulationResult) {
    const r = latestPopulationResult;
    const status = r.success ? "success" : "failure";
    const rs = r.run_status || {};
    html += `<div class="result-card ${status}">
      <h3>Population: ${r.success ? "✓" : "✗"} ${rs.successful_steps ?? "?"}/${rs.total_steps ?? "?"} steps</h3>
      <div class="detail">${r.duration || ""} | Export: ${r.export_path ? r.export_path.split("/").pop() : "—"}</div>
      ${r.error ? `<div class="errors-list"><ul><li>${r.error}</li></ul></div>` : ""}
    </div>`;
  }
  if (latestValidationResult) {
    const r = latestValidationResult;
    const status = r.success ? "success" : "failure";
    html += `<div class="result-card ${status}">
      <h3>Validation: ${r.success ? "✓" : "✗"} Passed ${r.passed ?? 0} | Failed ${r.failed ?? 0}</h3>
      <div class="detail">Acknowledged: ${(r.acknowledged || []).map((a) => a[0]).join(", ") || "—"}</div>
      ${(r.errors || []).length ? `<div class="errors-list"><ul>${(r.errors || []).map((e) => `<li>${e}</li>`).join("")}</ul></div>` : ""}
      ${(r.manual_checklist || []).length ? `<ul class="checklist">${(r.manual_checklist || []).map((c) => `<li>${c}</li>`).join("")}</ul>` : ""}
      ${r.error ? `<div class="errors-list"><ul><li>${r.error}</li></ul></div>` : ""}
    </div>`;
  }
  resultsContent.innerHTML = html || "<p class='detail'>Run population or validation to see results.</p>";
}

async function runPopulation() {
  const btn = document.getElementById("btn-run-population");
  btn.disabled = true;
  clearLogs();
  try {
    const r = await fetch("/api/run-population", { method: "POST" });
    const data = await r.json();
    if (data.job_id) {
      streamLogs(data.job_id, "Population");
    } else {
      appendLog("Error: " + (data.error || "Unknown error"));
    }
  } catch (e) {
    appendLog("Error: " + e.message);
  }
  btn.disabled = false;
}

async function runValidation() {
  const file = exportSelect.value;
  if (!file) {
    appendLog("Please select an export file first.");
    return;
  }
  const btn = document.getElementById("btn-validate");
  btn.disabled = true;
  clearLogs();
  try {
    const r = await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file }),
    });
    const data = await r.json();
    if (data.job_id) {
      streamLogs(data.job_id, "Validation");
    } else {
      appendLog("Error: " + (data.error || "Unknown error"));
    }
  } catch (e) {
    appendLog("Error: " + e.message);
  }
  btn.disabled = false;
}

document.getElementById("btn-run-population").addEventListener("click", runPopulation);
document.getElementById("btn-validate").addEventListener("click", runValidation);
document.getElementById("btn-refresh-exports").addEventListener("click", fetchExports);
document.getElementById("btn-clear-logs").addEventListener("click", clearLogs);

fetchConfig();
fetchExports();
renderResults();
