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
  configPreviewLink: () => document.getElementById("config-preview-link"),
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
  previewModal: () => document.getElementById("preview-modal"),
  previewModalTitle: () => document.getElementById("preview-modal-title"),
  previewModalBody: () => document.getElementById("preview-modal-body"),
  previewModalClose: () => document.getElementById("preview-modal-close"),
};

// =============================================================================
// Auth
// =============================================================================

function redirectToLoginIfUnauthorized(r) {
  if (r && r.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.href);
    return true;
  }
  return false;
}

// =============================================================================
// State
// =============================================================================

let currentJobId = null;
let latestPopulationResult = null;
let latestValidationResult = null;
let lastRunType = null; // "population" | "validation" — only show result for most recent run

// =============================================================================
// Micro-interactions — toasts, confetti, count-up, ripple
// =============================================================================

const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function showToast(message, type = "info", timeout = 4200) {
  const host = document.getElementById("toast-container");
  if (!host) return;
  const icon = { success: "✓", error: "✗", warning: "⚠️", info: "ℹ️" }[type] || "ℹ️";
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-msg"></span>`;
  el.querySelector(".toast-msg").textContent = message;
  host.appendChild(el);
  const remove = () => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 320);
  };
  el.addEventListener("click", remove);
  setTimeout(remove, timeout);
}

// Animate every [data-count] number inside a container from 0 to its target.
function animateCounts(container) {
  if (!container) return;
  container.querySelectorAll("[data-count]").forEach((el) => {
    const target = parseInt(el.dataset.count, 10);
    if (isNaN(target)) return;
    if (prefersReducedMotion()) {
      el.textContent = String(target);
      return;
    }
    const duration = 750;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      el.textContent = String(Math.round(target * eased));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

// Lightweight, dependency-free confetti burst for a fully successful run.
function celebrate() {
  if (prefersReducedMotion()) return;
  let canvas = document.getElementById("confetti-canvas");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "confetti-canvas";
    document.body.appendChild(canvas);
  }
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  ctx.scale(dpr, dpr);
  const W = window.innerWidth;
  const colors = ["#4a8ff7", "#2dd4bf", "#3fb950", "#7c5cff", "#f7c948"];
  // Deliberately restrained: a brief, small flourish rather than a full-screen
  // shower — this tool is often driven in front of a customer.
  const DURATION = 1500;
  const parts = Array.from({ length: 55 }, () => ({
    x: W / 2 + (Math.random() - 0.5) * 140,
    y: window.innerHeight * 0.3,
    vx: (Math.random() - 0.5) * 6,
    vy: Math.random() * -8 - 3,
    size: Math.random() * 5 + 3,
    color: colors[(Math.random() * colors.length) | 0],
    rot: Math.random() * Math.PI,
    vr: (Math.random() - 0.5) * 0.3,
    life: 1,
  }));
  const start = performance.now();
  const draw = (now) => {
    const elapsed = now - start;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    parts.forEach((p) => {
      p.vy += 0.22; // gravity
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      p.life = Math.max(0, 1 - elapsed / DURATION);
      ctx.save();
      ctx.globalAlpha = p.life * 0.85;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
      ctx.restore();
    });
    if (elapsed < DURATION) requestAnimationFrame(draw);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  };
  requestAnimationFrame(draw);
}

// Workflow stepper — orient the operator in the 4-phase journey. This is a
// coarse orientation aid driven from run state, NOT a precise state machine:
// phase 3 ("Upgrade OnWatch") happens outside this tool, so we can only mark it
// as the *next* thing after a population finishes.
const WF_ORDER = ["configure", "populate", "upgrade", "validate"];
function setWorkflowPhase(phase, { done = false, issuesPhase = null } = {}) {
  const nav = document.getElementById("workflow");
  if (!nav) return;
  const curIdx = WF_ORDER.indexOf(phase);
  if (curIdx < 0) return;
  nav.querySelectorAll(".wf-step").forEach((el) => {
    const idx = WF_ORDER.indexOf(el.dataset.phase);
    el.classList.remove("is-current", "is-done", "is-upcoming", "is-issues");
    if (idx < curIdx) el.classList.add("is-done");
    else if (idx === curIdx) el.classList.add(done ? "is-done" : "is-current");
    else el.classList.add("is-upcoming");
  });
  if (issuesPhase) {
    const el = nav.querySelector(`.wf-step[data-phase="${issuesPhase}"]`);
    if (el) {
      el.classList.remove("is-done", "is-current", "is-upcoming");
      el.classList.add("is-issues");
    }
  }
}

// Material-style ripple on button presses.
function attachRipples() {
  document.querySelectorAll(".btn").forEach((btn) => {
    if (btn.dataset.ripple) return;
    btn.dataset.ripple = "1";
    btn.addEventListener("click", (e) => {
      if (prefersReducedMotion()) return;
      const rect = btn.getBoundingClientRect();
      const d = Math.max(rect.width, rect.height);
      const r = document.createElement("span");
      r.className = "ripple";
      r.style.width = r.style.height = `${d}px`;
      r.style.left = `${e.clientX - rect.left - d / 2}px`;
      r.style.top = `${e.clientY - rect.top - d / 2}px`;
      btn.appendChild(r);
      setTimeout(() => r.remove(), 600);
    });
  });
}

// =============================================================================
// Config
// =============================================================================

async function fetchConfig() {
  try {
    const r = await fetch("/api/config/status", { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    const ip = data.onwatch_ip || "";
    const version = data.onwatch_version || "";
    const currentLine = (ip || version)
      ? `<div class="config-current">Current target — IP: <strong>${escapeHtml(ip || "—")}</strong> · Version: <strong>${escapeHtml(version || "—")}</strong></div>`
      : `<div class="config-current">No IP/Version set yet.</div>`;
    if (data.valid) {
      DOM.configBadge().textContent = ip && version ? `Config ✓ (${ip} · ${version})` : "Config ✓";
      DOM.configBadge().className = "badge ok";
      DOM.configContent().innerHTML = currentLine + "<div>Set IP and Version below to change them before running.</div>";
    } else {
      DOM.configBadge().textContent = "Config ✗";
      DOM.configBadge().className = "badge error";
      DOM.configContent().innerHTML = currentLine + `<span class="error-list">${(data.errors || []).join("<br>")}</span>`;
    }
    document.getElementById("config-ip").value = "";
    document.getElementById("config-version").value = "";
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
  showToast(msg.replace(/^✓\s*/, ""), isError ? "error" : "success");
}

function clearConfigStatus() {
  const el = DOM.configStatusMsg();
  el.textContent = "";
  el.className = "config-status-msg";
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
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
    });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    if (data.success) {
      showConfigStatus("✓ " + data.message);
      clearActionError();  // any prior "no IP/version" error no longer applies
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
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    if (data.success) {
      showConfigStatus("✓ " + data.message);
      clearActionError();  // any prior "no IP/version" error no longer applies
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
    const r = await fetch("/api/exports", { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return;
    const exports = await r.json();
    DOM.exportsList().innerHTML = exports.length
      ? exports
          .map(
            (e) =>
              `<div class="exports-item">
                <span class="filename preview-link" data-file-path="${escapeHtml(e.path)}" data-file-name="${escapeHtml(e.filename)}">${e.filename}</span>
                <div class="meta">${e.generated_at || ""} | ${e.total_duration || ""} | ${e.successful_steps ?? ""}/${e.total_steps ?? ""} steps</div>
              </div>`
          )
          .join("")
      : "<div class='exports-item'>No data inserted files found. Run population first.</div>";

    DOM.exportSelect().innerHTML =
      '<option value="">-- Select a saved snapshot --</option>' + exports.map((e) => `<option value="${e.path}">${e.filename}</option>`).join("");

    // Attach click handlers for file preview
    DOM.exportsList().querySelectorAll(".filename.preview-link").forEach((el) => {
      el.addEventListener("click", () => showFilePreview(el.dataset.filePath, el.dataset.fileName));
    });
  } catch (e) {
    DOM.exportsList().innerHTML = "<div class='exports-item'>Could not load data inserted files</div>";
  }
}

// =============================================================================
// Preview modal
// =============================================================================

async function showConfigPreview() {
  try {
    const r = await fetch("/api/config/preview", { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return;
    if (!r.ok) throw new Error(await r.text());
    const content = await r.text();
    showPreviewModal("config.yaml", content);
  } catch (e) {
    showPreviewModal("config.yaml", `Error: ${e.message}`);
  }
}

async function showFilePreview(path, filename) {
  try {
    const r = await fetch("/api/file/preview?path=" + encodeURIComponent(path), { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return;
    if (!r.ok) throw new Error(await r.text());
    const content = await r.text();
    showPreviewModal(filename || "Preview", content);
  } catch (e) {
    showPreviewModal(filename || "Preview", `Error: ${e.message}`);
  }
}

function highlightYaml(text) {
  return text.split("\n").map((line) => {
    const esc = (s) => {
      const d = document.createElement("div");
      d.textContent = s;
      return d.innerHTML;
    };
    const trimmed = line.trimStart();
    const indent = line.slice(0, line.length - trimmed.length);
    if (trimmed.startsWith("#")) {
      return esc(indent) + '<span class="yaml-comment">' + esc(trimmed) + "</span>";
    }
    const colonIdx = trimmed.indexOf(":");
    if (colonIdx === -1) {
      return esc(line);
    }
    const key = trimmed.slice(0, colonIdx);
    let rest = trimmed.slice(colonIdx + 1);
    const inlineComment = rest.match(/\s+#\s+(.*)$/);
    let value = rest;
    let commentPart = "";
    if (inlineComment) {
      value = rest.slice(0, rest.indexOf("#")).trimEnd();
      commentPart = ' <span class="yaml-comment"># ' + esc(inlineComment[1]) + "</span>";
    }
    const valuePart = value ? '<span class="yaml-value">' + esc(value) + "</span>" : "";
    return esc(indent) + '<span class="yaml-key">' + esc(key) + "</span>: " + valuePart + commentPart;
  }).join("\n");
}

function showPreviewModal(title, content) {
  DOM.previewModalTitle().textContent = title;
  const looksLikeYaml =
    !content.trimStart().startsWith("Error:") &&
    (/\.(yaml|yml)$/i.test(title) || content.trimStart().startsWith("#") || (content.includes("\n  ") && content.includes(":\n")));
  DOM.previewModalBody().innerHTML = looksLikeYaml ? highlightYaml(content) : escapeHtml(content);
  DOM.previewModal().classList.remove("hidden");
  DOM.previewModal().setAttribute("aria-hidden", "false");
}

function hidePreviewModal() {
  DOM.previewModal().classList.add("hidden");
  DOM.previewModal().setAttribute("aria-hidden", "true");
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
  const icon = (s) => (s.status === "success" ? "✓" : s.status === "failed" ? "✗" : s.status === "skipped" ? "⊘" : "●");
  const cls = (s) => (s.status === "running" ? "running" : s.status);
  DOM.progressSteps().innerHTML = steps
    .map(
      (s) =>
        `<div class="progress-step ${cls(s)}"><span class="step-dot"></span><span class="step-icon">${icon(s)}</span><span class="step-name">${escapeHtml(s.name || "")}</span></div>`
    )
    .join("");
  // Keep the active step in view as the timeline grows.
  const running = DOM.progressSteps().querySelector(".progress-step.running");
  if (running) running.scrollIntoView({ block: "nearest" });
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
    <span>Select a data inserted file from the dropdown above, then click Validate.</span>
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

function stopStepTimer(ctx) {
  if (ctx.tickTimer) {
    clearInterval(ctx.tickTimer);
    ctx.tickTimer = null;
  }
}

function startStepTimer(ctx) {
  stopStepTimer(ctx);
  ctx.tickTimer = setInterval(() => {
    if (!ctx.stepStart) return;
    const elapsed = Math.floor((Date.now() - ctx.stepStart) / 1000);
    const budget = ctx.stepTimeout ? ` / max ${ctx.stepTimeout}s` : "";
    const sub = ctx.subMessage ? ` · ${ctx.subMessage}` : "";
    // A dedicated "elapsed" line (plus any sub-step message) reassures the
    // operator a slow step (inquiry uploads/analysis, translation) is still
    // working, not hung.
    DOM.progressText().textContent = `${ctx.stepBase}${sub} — running ${elapsed}s${budget}`;
  }, 1000);
}

function handleProgressEvent(ev, jobType, ctx) {
  const { steps } = ctx;

  if (ev.type === "step_start") {
    if (ev.total) ctx.total = ev.total;
    const t = ctx.total || ev.step;
    steps.push({ num: ev.step, name: ev.name, status: "running" });
    DOM.progressBar().style.width = `${((ev.step - 1) / t) * 100}%`;
    ctx.stepBase = `Step ${ev.step}/${t}: ${ev.name}`;
    ctx.subMessage = "";
    ctx.stepStart = Date.now();
    ctx.stepTimeout = ev.timeout || null;
    DOM.progressText().textContent = `${ctx.stepBase}...`;
    startStepTimer(ctx);
    renderProgressSteps(steps);
    return;
  }

  if (ev.type === "substep") {
    // Fine-grained progress within a long step (e.g. per-file inquiry upload).
    ctx.subMessage = (ev.message || "").trim();
    return;
  }

  if (ev.type === "step_done") {
    stopStepTimer(ctx);
    ctx.stepStart = null;
    ctx.subMessage = "";
    const s = steps.find((x) => x.num === ev.step);
    if (s) s.status = ev.status;
    if (ev.total) ctx.total = ev.total;
    const t = ctx.total || ev.step;
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

  if (ev.type === "interrupted") {
    stopStepTimer(ctx);
    DOM.progressText().textContent = "Run interrupted";
    const cp = ev.checkpoint ? ` Partial data was checkpointed to <code>${escapeHtml(ev.checkpoint)}</code> — you can validate against it or re-run.` : "";
    DOM.progressSummary().innerHTML = `<div class="summary-card failure">⚠️ ${escapeHtml(ev.message || "Run was interrupted.")}${cp}</div>`;
    setWorkflowPhase(jobType === "validation" ? "validate" : "populate", {
      issuesPhase: jobType === "validation" ? "validate" : "populate",
    });
    return;
  }

  if (ev.type === "complete") {
    stopStepTimer(ctx);
    DOM.progressBar().style.width = "100%";
    if (ev.success) {
      celebrate();
      showToast(`${jobType === "validation" ? "Validation" : "Population"} completed successfully`, "success");
    } else {
      showToast(`${jobType === "validation" ? "Validation" : "Population"} finished with issues — see results`, "warning", 6000);
    }
    if (jobType === "population" && ev.run_status) {
      const rs = ev.run_status;
      DOM.progressText().textContent = `Done: ${rs.successful_steps ?? 0}/${rs.total_steps ?? 0} steps | ${ev.duration || ""}`;
      lastRunType = "population";
      latestPopulationResult = {
        success: ev.success,
        run_status: ev.run_status,
        duration: ev.duration,
        export_path: ev.export_path,
        error: ev.error,
        errors_count: ev.errors_count || 0,
        errors: ev.errors || [],
        manual_checklist: ev.manual_checklist || [],
      };
      renderResults();
      scrollToResults();
      // Population finished — the operator's next step is the OnWatch upgrade
      // (done outside this tool), so advance the stepper to phase 3.
      setWorkflowPhase("upgrade", ev.success ? {} : { issuesPhase: "populate" });
    }
    if (jobType === "validation" && ev.passed !== undefined) {
      DOM.progressText().textContent = `Done: ${ev.passed} passed, ${ev.failed} failed`;
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
      scrollToResults();
      setWorkflowPhase("validate", { done: true, issuesPhase: ev.success ? null : "validate" });
    }
  }
}

// =============================================================================
// Progress stream — connect EventSource, handle events
// =============================================================================

function scrollToProgressAndResults() {
  document.getElementById("progress-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function scrollToResults() {
  document.getElementById("results-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

function streamProgress(jobId, jobType) {
  currentJobId = jobId;
  setActionsEnabled(false);
  clearProgress();
  DOM.progressSource().textContent = `(${jobType})`;
  scrollToProgressAndResults();

  const ctx = { steps: [], warnings: [], total: 0 };

  const es = new EventSource(`/api/progress/${jobId}`);
  es.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      if (ev.type === "stream_done") {
        stopStepTimer(ctx);
        es.close();
        if (ev.error === "job_not_found") {
          DOM.progressSummary().innerHTML = `<div class="summary-card failure">Job not found (server may use multiple workers). Try again.</div>`;
        } else {
          pollStatus(jobId, jobType);
        }
        setActionsEnabled(true);
        currentJobId = null;
        DOM.progressSource().textContent = "";
        return;
      }
      handleProgressEvent(ev, jobType, ctx);
    } catch (_) {}
  };
  es.onerror = () => {
    stopStepTimer(ctx);
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
      const r = await fetch(`/api/status/${jobId}`, { credentials: "same-origin" });
      if (redirectToLoginIfUnauthorized(r)) return;
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
        scrollToResults();
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
      <p class="results-empty-hint">Run <strong>Population</strong> first, then select a data inserted file and run <strong>Validate</strong> to check data after upgrade.</p>
    </div>`;
  }
  DOM.resultsContent().innerHTML = html;
  animateCounts(DOM.resultsContent());
}

function buildPopulationResultCard(r) {
  const rs = r.run_status || {};
  const errorsCount = r.errors_count || 0;
  const status = r.success ? "success" : "failure";
  // Distinguish a clean run from one that finished but couldn't create some
  // items (e.g. license-blocked cameras/inquiries) from an outright failure.
  let heading;
  if (r.success) {
    heading = `Population: ✓ ${rs.successful_steps ?? "?"}/${rs.total_steps ?? "?"} steps`;
  } else if (errorsCount > 0) {
    heading = `Population: ⚠️ completed with ${errorsCount} issue${errorsCount === 1 ? "" : "s"} — ${rs.successful_steps ?? "?"}/${rs.total_steps ?? "?"} steps succeeded`;
  } else {
    heading = `Population: ✗ ${rs.successful_steps ?? "?"}/${rs.total_steps ?? "?"} steps`;
  }
  // Detailed errors stay in the live panel / run log; the card stays readable
  // with the friendly manual checklist below (which names each affected item).
  const stats = `<div class="result-stats">
    <div class="stat-tile ok"><div class="stat-num" data-count="${rs.successful_steps ?? 0}">0</div><div class="stat-label">Steps done</div></div>
    <div class="stat-tile ${errorsCount > 0 ? "issues" : ""}"><div class="stat-num" data-count="${errorsCount}">0</div><div class="stat-label">Issues</div></div>
    <div class="stat-tile"><div class="stat-num" data-count="${rs.skipped_steps ?? 0}">0</div><div class="stat-label">Skipped</div></div>
    <div class="stat-tile"><div class="stat-num-static">${escapeHtml(r.duration || "—")}</div><div class="stat-label">Duration</div></div>
  </div>`;
  return `<div class="result-card ${status}">
    <h3>${heading}</h3>
    ${stats}
    <div class="detail">Data inserted: ${r.export_path ? escapeHtml(r.export_path.split("/").pop()) : "—"}</div>
    ${r.error ? `<div class="errors-list"><ul><li>${escapeHtml(r.error)}</li></ul></div>` : ""}
    ${(r.manual_checklist || []).length ? `<ul class="checklist">${(r.manual_checklist || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function buildValidationResultCard(r) {
  const status = r.success ? "success" : "failure";
  const stats = `<div class="result-stats">
    <div class="stat-tile ok"><div class="stat-num" data-count="${r.passed ?? 0}">0</div><div class="stat-label">Passed</div></div>
    <div class="stat-tile ${(r.failed ?? 0) > 0 ? "bad" : ""}"><div class="stat-num" data-count="${r.failed ?? 0}">0</div><div class="stat-label">Failed</div></div>
    <div class="stat-tile"><div class="stat-num" data-count="${r.validated ?? 0}">0</div><div class="stat-label">Checked</div></div>
  </div>`;
  return `<div class="result-card ${status}">
    <h3>Validation: ${r.success ? "✓ Data survived the upgrade" : "✗ Discrepancies found"}</h3>
    ${stats}
    <div class="detail">Acknowledged: ${escapeHtml((r.acknowledged || []).map((a) => a[0]).join(", ") || "—")}</div>
    ${(r.errors || []).length ? `<div class="errors-list"><ul>${(r.errors || []).map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul></div>` : ""}
    ${(r.manual_checklist || []).length ? `<ul class="checklist">${(r.manual_checklist || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>` : ""}
    ${r.error ? `<div class="errors-list"><ul><li>${escapeHtml(r.error)}</li></ul></div>` : ""}
  </div>`;
}

// =============================================================================
// Actions — run population, run validation
// =============================================================================

async function fetchSavedTarget() {
  // Read the IP/version that are actually saved on the server. The input fields
  // are write-only ("change this"); they're cleared after a successful Set, so
  // reading them here would falsely report "no IP/version" on every subsequent run.
  try {
    const r = await fetch("/api/config/status", { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return null;
    const data = await r.json();
    return { ip: (data.onwatch_ip || "").trim(), version: (data.onwatch_version || "").trim() };
  } catch (_) {
    return null;
  }
}

async function runPopulation() {
  if (currentJobId) return;
  clearActionError();
  const target = await fetchSavedTarget();
  if (!target) {
    showConfigStatus("Could not read config status. Try again.", true);
    return;
  }
  if (!target.ip || !target.version) {
    showConfigStatus("No IP/Version configured. Use the Set IP / Set Version buttons below.", true);
    return;
  }
  const userName = document.getElementById("user-name").value.trim();
  if (!userName) {
    showConfigStatus("Your name is required", true);
    document.getElementById("user-name").focus();
    return;
  }
  const msg = `Run population on:\n  IP: ${target.ip}\n  Version: ${target.version}\n  As: ${userName}\n\nVerify this is correct before continuing.`;
  if (!confirm(msg)) return;
  try {
    const r = await fetch("/api/run-population", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: userName }),
    });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    if (data.job_id) {
      clearConfigStatus();
      showToast(`Population started on ${target.ip} (${target.version})`, "info");
      setWorkflowPhase("populate");
      streamProgress(data.job_id, "population");
    } else {
      const errMsg = data.error || "Unknown error";
      showConfigStatus(errMsg, true);
      DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${escapeHtml(errMsg)}</div>`;
    }
  } catch (e) {
    DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${e.message}</div>`;
  }
}

async function runValidation() {
  if (currentJobId) return;
  clearActionError();
  const target = await fetchSavedTarget();
  if (!target) {
    showConfigStatus("Could not read config status. Try again.", true);
    return;
  }
  if (!target.ip || !target.version) {
    showConfigStatus("No IP/Version configured. Use the Set IP / Set Version buttons below.", true);
    return;
  }
  const file = DOM.exportSelect().value;
  if (!file) {
    showValidationError("Please select a data inserted file (last population run) to validate against.");
    return;
  }
  try {
    const r = await fetch("/api/validate", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file }),
    });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    if (data.job_id) {
      clearConfigStatus();
      showToast("Validation started", "info");
      setWorkflowPhase("validate");
      streamProgress(data.job_id, "validation");
    } else {
      const errMsg = data.error || "Unknown error";
      showConfigStatus(errMsg, true);
      DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${escapeHtml(errMsg)}</div>`;
    }
  } catch (e) {
    DOM.progressSummary().innerHTML = `<div class="summary-card failure">Error: ${e.message}</div>`;
  }
}

// =============================================================================
// Reconnect — restore an in-flight or most-recent run after a page reload
// =============================================================================

async function restoreActiveJob() {
  // A run lives on the server, not in this tab. On load, reconnect to any
  // in-flight run (the progress stream replays from the start) so refreshing
  // the page, opening a second tab, or a brief disconnect never loses a run.
  try {
    const r = await fetch("/api/jobs/active", { credentials: "same-origin" });
    if (redirectToLoginIfUnauthorized(r)) return;
    const data = await r.json();
    if (data.running && data.running_job) {
      setWorkflowPhase(data.running_job.type === "validation" ? "validate" : "populate");
      streamProgress(data.running_job.job_id, data.running_job.type);
      return;
    }
    const last = data.latest_job;
    if (last && last.status === "interrupted") {
      DOM.progressSection().scrollIntoView({ behavior: "smooth", block: "start" });
      const cp = last.checkpoint ? ` Partial data was checkpointed to <code>${escapeHtml(last.checkpoint)}</code> — you can validate against it or re-run.` : "";
      DOM.progressSummary().innerHTML = `<div class="summary-card failure">⚠️ Your last run was interrupted (the server restarted mid-run). Partial data may already be on OnWatch.${cp}</div>`;
      setWorkflowPhase(last.type === "validation" ? "validate" : "populate", {
        issuesPhase: last.type === "validation" ? "validate" : "populate",
      });
      return;
    }
    if (last && last.result && (last.status === "done" || last.status === "error")) {
      lastRunType = last.type;
      if (last.type === "population") {
        latestPopulationResult = last.result;
        setWorkflowPhase("upgrade", last.result.success ? {} : { issuesPhase: "populate" });
      } else {
        latestValidationResult = last.result;
        setWorkflowPhase("validate", { done: true, issuesPhase: last.result.success ? null : "validate" });
      }
      renderResults();
    }
  } catch (_) {
    /* best-effort; a failed restore just leaves the page in its default state */
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

// Remember the operator's name across visits so they don't retype it every time.
const NAME_KEY = "ow:user-name";
(function restoreName() {
  const saved = localStorage.getItem(NAME_KEY);
  if (saved) document.getElementById("user-name").value = saved;
})();
document.getElementById("user-name").addEventListener("input", (e) => {
  const v = (e.target.value || "").trim();
  if (v) localStorage.setItem(NAME_KEY, v);
  else localStorage.removeItem(NAME_KEY);
});

// Guidance section — default open on first visit; persist user choice.
const GUIDANCE_KEY = "ow:guidance-collapsed";
function applyGuidanceState() {
  const btn = document.getElementById("guidance-toggle");
  const content = document.getElementById("guidance-content");
  const collapsed = localStorage.getItem(GUIDANCE_KEY) === "1";
  btn.setAttribute("aria-expanded", String(!collapsed));
  content.classList.toggle("hidden", collapsed);
}
document.getElementById("guidance-toggle").addEventListener("click", () => {
  const btn = document.getElementById("guidance-toggle");
  const expanded = btn.getAttribute("aria-expanded") === "true";
  localStorage.setItem(GUIDANCE_KEY, expanded ? "1" : "0");
  applyGuidanceState();
});
applyGuidanceState();
DOM.configPreviewLink().addEventListener("click", (e) => {
  e.preventDefault();
  showConfigPreview();
});
DOM.previewModalClose().addEventListener("click", hidePreviewModal);
DOM.previewModal().querySelector(".modal-backdrop").addEventListener("click", hidePreviewModal);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !DOM.previewModal().classList.contains("hidden")) hidePreviewModal();
});

attachRipples();
setWorkflowPhase("configure");
fetchConfig();
fetchExports();
renderResults();
restoreActiveJob();
