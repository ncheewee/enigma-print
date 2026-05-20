const STORAGE_KEY = "enigmaprint.projects.v2";
const HELPER_URL = "http://127.0.0.1:4777";
const APP_VERSION = "v0.4.0";
const PRINT_PHASES = [
  { key: "config", label: "Load printer settings", percent: 8 },
  { key: "slice", label: "Slice 3MF to G-code", percent: 28 },
  { key: "package", label: "Package printer project", percent: 50 },
  { key: "upload", label: "Upload to A1 mini", percent: 76 },
  { key: "send", label: "Send AMS-off print command", percent: 92 },
  { key: "done", label: "Printer accepted job", percent: 100 }
];

const els = {
  versionBadge: document.querySelector("#versionBadge"),
  projectList: document.querySelector("#projectList"),
  projectTitle: document.querySelector("#projectTitle"),
  projectStatus: document.querySelector("#projectStatus"),
  projectSummary: document.querySelector("#projectSummary"),
  metrics: document.querySelector("#metrics"),
  artworkPreview: document.querySelector("#artworkPreview"),
  todayTitle: document.querySelector("#todayTitle"),
  todayPiece: document.querySelector("#todayPiece"),
  fileList: document.querySelector("#fileList"),
  pieceGrid: document.querySelector("#pieceGrid"),
  markPrintedButton: document.querySelector("#markPrintedButton"),
  exportButton: document.querySelector("#exportButton"),
  resetButton: document.querySelector("#resetButton"),
  newProjectButton: document.querySelector("#newProjectButton"),
  importButton: document.querySelector("#importButton"),
  importInput: document.querySelector("#importInput"),
  dialog: document.querySelector("#projectDialog"),
  form: document.querySelector("#projectForm"),
  nameInput: document.querySelector("#nameInput"),
  hintInput: document.querySelector("#hintInput"),
  piecesInput: document.querySelector("#piecesInput"),
  startInput: document.querySelector("#startInput"),
  progressDialog: document.querySelector("#progressDialog"),
  progressTitle: document.querySelector("#progressTitle"),
  progressPercent: document.querySelector("#progressPercent"),
  progressFill: document.querySelector("#progressFill"),
  progressSteps: document.querySelector("#progressSteps"),
  progressMessage: document.querySelector("#progressMessage"),
  progressCloseButton: document.querySelector("#progressCloseButton")
};

let state = {
  projects: [],
  selectedProjectId: null
};

async function bootstrap() {
  els.versionBadge.textContent = APP_VERSION;
  state.projects = loadProjects();
  await loadPublishedProjects();
  state.selectedProjectId = state.projects[0]?.id ?? null;
  els.startInput.value = new Date().toISOString().slice(0, 10);
  attachEvents();
  render();
  registerServiceWorker();
}

function attachEvents() {
  els.newProjectButton.addEventListener("click", () => els.dialog.showModal());
  els.importButton.addEventListener("click", () => els.importInput.click());
  els.importInput.addEventListener("change", importManifest);

  els.form.addEventListener("submit", (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const project = createProjectFromForm(new FormData(els.form));
    state.projects = [project, ...state.projects];
    state.selectedProjectId = project.id;
    saveProjects();
    els.form.reset();
    els.startInput.value = new Date().toISOString().slice(0, 10);
    els.dialog.close();
    render();
  });

  els.markPrintedButton.addEventListener("click", () => {
    const project = getSelectedProject();
    const nextPiece = project?.pieces.find((piece) => piece.status !== "printed");
    if (!project || !nextPiece) return;
    nextPiece.status = "printed";
    nextPiece.printedAt = new Date().toISOString();
    project.updatedAt = new Date().toISOString();
    saveProjects();
    render();
  });

  els.exportButton.addEventListener("click", () => {
    const project = getSelectedProject();
    if (!project) return;
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.slug}.manifest.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  });

  els.resetButton.addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEY);
    state.projects = [];
    loadPublishedProjects().then(() => {
      state.selectedProjectId = state.projects[0]?.id ?? null;
      render();
    });
  });

  els.pieceGrid.addEventListener("click", handlePieceActionClick);
  els.todayPiece.addEventListener("click", handlePieceActionClick);
  els.progressCloseButton.addEventListener("click", () => els.progressDialog.close());
  els.progressDialog.addEventListener("cancel", (event) => {
    if (els.progressCloseButton.hidden) event.preventDefault();
  });
}

async function handlePieceActionClick(event) {
  const action = event.target.closest("[data-piece-action]");
  if (!action || action.disabled) return;
  const project = getSelectedProject();
  const piece = project?.pieces.find((item) => item.id === action.dataset.pieceId);
  if (!project || !piece) return;
  if (action.dataset.pieceAction === "open") {
    await openPieceWithHelper(project, piece);
  }
  if (action.dataset.pieceAction === "slice") {
    await withBusyAction(action, "Slicing...", () => slicePieceWithHelper(project, piece));
  }
  if (action.dataset.pieceAction === "print") {
    await withBusyAction(action, "Preparing...", () => printPieceWithHelper(project, piece, action));
  }
}

async function importManifest(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    const manifest = JSON.parse(await file.text());
    const project = normalizeProjectManifest(manifest);
    state.projects = [project, ...state.projects.filter((item) => item.id !== project.id)];
    state.selectedProjectId = project.id;
    saveProjects();
    render();
  } catch (error) {
    window.alert(`Could not import manifest: ${error.message}`);
  } finally {
    event.target.value = "";
  }
}

function loadProjects() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      const projects = JSON.parse(saved);
      if (Array.isArray(projects) && projects.length > 0) return projects;
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }
  return [];
}

async function loadPublishedProjects() {
  try {
    const response = await fetch("projects/index.json", { cache: "no-store" });
    if (!response.ok) return;
    const generated = await response.json();
    if (!Array.isArray(generated.projects)) return;

    const imported = generated.projects.map(normalizeProjectManifest);
    const existing = new Map(state.projects.map((project) => [project.id, project]));
    for (const project of imported) {
      existing.set(project.id, { ...existing.get(project.id), ...project });
    }
    state.projects = [...imported, ...state.projects.filter((project) => !imported.some((item) => item.id === project.id))];
    saveProjects();
  } catch {
    // Static file viewing and first-run states may not expose projects/index.json.
  }
}

function saveProjects() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.projects));
}

function getSelectedProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) ?? state.projects[0];
}

function render() {
  const project = getSelectedProject();
  if (!project) {
    renderEmptyState();
    return;
  }
  renderProjectList(project);
  renderProject(project);
}

function renderEmptyState() {
  els.projectList.innerHTML = "";
  els.projectTitle.textContent = "No projects yet";
  els.projectStatus.textContent = "empty";
  els.projectStatus.className = "status-pill";
  els.projectSummary.textContent = "Publish or import a project manifest to start tracking pieces.";
  els.metrics.innerHTML = [metric("0", "projects"), metric("0", "pieces"), metric("A1 mini", "printer")].join("");
  els.artworkPreview.innerHTML = `
    <div class="artwork-placeholder" aria-hidden="true"></div>
    <p>Generated artwork will appear here after loading a project.</p>
  `;
  els.todayTitle.textContent = "Next print";
  els.todayPiece.innerHTML = `<div class="piece-preview"></div><div class="piece-meta"><strong>No queued piece.</strong><p>Import a manifest or generate a puzzle locally.</p></div>`;
  els.fileList.innerHTML = "";
  els.pieceGrid.innerHTML = "";
  els.markPrintedButton.disabled = true;
}

function renderProjectList(selectedProject) {
  els.projectList.innerHTML = "";
  state.projects.forEach((project) => {
    const printed = project.pieces.filter((piece) => piece.status === "printed").length;
    const button = document.createElement("button");
    button.className = `project-nav-item ${project.id === selectedProject.id ? "active" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(project.name)}</strong>
        <span>${printed}/${project.pieces.length} pieces printed</span>
      </span>
      <span class="nav-status ${project.status === "complete" ? "complete" : ""}">${project.status}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedProjectId = project.id;
      render();
    });
    els.projectList.append(button);
  });
}

function renderProject(project) {
  const printed = project.pieces.filter((piece) => piece.status === "printed").length;
  const nextPiece = project.pieces.find((piece) => piece.status !== "printed");
  const completion = Math.round((printed / project.pieces.length) * 100);
  const displayStatus = getProjectStatus(project, printed);

  els.projectTitle.textContent = project.name;
  els.projectStatus.textContent = displayStatus;
  els.projectStatus.className = `status-pill ${displayStatus === "complete" ? "complete" : ""}`;
  els.projectSummary.textContent = project.summary;
  els.markPrintedButton.disabled = !nextPiece;
  els.todayTitle.textContent = nextPiece ? `Day ${nextPiece.day}` : "Puzzle complete";
  renderArtworkPreview(project);

  els.metrics.innerHTML = [
    metric(`${printed}/${project.pieces.length}`, "pieces printed"),
    metric(`${completion}%`, "assembled"),
    metric(project.targetPrinter, "printer")
  ].join("");

  els.todayPiece.innerHTML = nextPiece
    ? renderTodayPiece(nextPiece)
    : `<div class="piece-preview"></div><div class="piece-meta"><strong>All pieces are printed.</strong><p>The finished puzzle can be assembled now.</p></div>`;

  els.fileList.innerHTML = project.files.map((file) => `
    <div class="file-row">
      <span>
        <strong>${escapeHtml(file.name)}</strong>
        <span>${escapeHtml(file.description)}</span>
      </span>
      ${file.path ? `<a class="file-badge" href="${escapeHtml(file.path)}">${escapeHtml(file.type)}</a>` : `<span class="file-badge">${escapeHtml(file.type)}</span>`}
    </div>
  `).join("");

  els.pieceGrid.innerHTML = project.pieces.map((piece) => `
    <article class="piece-card ${piece.status === "printed" ? "printed" : "pending"}">
      <div class="piece-token">${piece.day}</div>
      <strong>${escapeHtml(piece.name)}</strong>
      <p>${escapeHtml(piece.filename)}</p>
      <p>${piece.status === "printed" ? "Printed" : formatDate(piece.scheduledFor)}</p>
      <div class="piece-actions">
        ${piece.path ? `<a class="piece-link" href="${escapeHtml(piece.path)}">Download</a>` : ""}
        ${piece.path ? `<button class="piece-link" type="button" data-piece-action="open" data-piece-id="${escapeHtml(piece.id)}">Open</button>` : ""}
        ${piece.path ? `<button class="piece-link" type="button" data-piece-action="slice" data-piece-id="${escapeHtml(piece.id)}">Slice G-code</button>` : ""}
        ${piece.path ? `<button class="piece-link" type="button" data-piece-action="print" data-piece-id="${escapeHtml(piece.id)}">Print (AMS off)</button>` : ""}
      </div>
    </article>
  `).join("");
}

function renderArtworkPreview(project) {
  const source = project.assets?.sourceHidden || project.assets?.preview || null;
  if (source) {
    els.artworkPreview.innerHTML = `
      <img src="${escapeHtml(source)}" alt="${escapeHtml(project.name)} generated artwork">
      <p>${getProjectStatus(project) === "complete" ? "Final reveal is unlocked." : "Stored as a hidden reveal asset for this generated week."}</p>
    `;
    return;
  }

  els.artworkPreview.innerHTML = `
    <div class="artwork-placeholder" aria-hidden="true"></div>
    <p>Generated artwork will appear here after importing or loading a generator manifest.</p>
  `;
}

function getProjectStatus(project, printed = null) {
  const printedCount = printed ?? project.pieces.filter((piece) => piece.status === "printed").length;
  if (printedCount === project.pieces.length) return "complete";
  if (printedCount === 0 && project.status === "generated") return "generated";
  return "active";
}

function renderTodayPiece(piece) {
  return `
    <div class="piece-preview" aria-hidden="true"></div>
    <div class="piece-meta">
      <strong>${escapeHtml(piece.name)}</strong>
      <span>${formatDate(piece.scheduledFor)} · ${escapeHtml(piece.filename)}</span>
      <p>${escapeHtml(piece.note)}</p>
      ${piece.path ? `
        <div class="piece-actions">
          <a class="piece-link" href="${escapeHtml(piece.path)}">Download 3MF</a>
          <button class="piece-link" type="button" data-piece-action="open" data-piece-id="${escapeHtml(piece.id)}">Open</button>
          <button class="piece-link" type="button" data-piece-action="slice" data-piece-id="${escapeHtml(piece.id)}">Slice G-code</button>
          <button class="piece-link" type="button" data-piece-action="print" data-piece-id="${escapeHtml(piece.id)}">Print (AMS off)</button>
        </div>
      ` : ""}
    </div>
  `;
}

function metric(value, label) {
  return `<div class="metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`;
}

function createProjectFromForm(formData) {
  const name = String(formData.get("name") || "").trim();
  const hint = String(formData.get("hint") || "Unknown weekly mystery").trim();
  const pieceCount = Number(formData.get("pieces") || 7);
  const startDate = String(formData.get("startDate"));
  const slug = slugify(name);

  return {
    id: crypto.randomUUID(),
    name,
    slug,
    status: "active",
    summary: `A ${pieceCount}-day AI generated puzzle queued from the hint: ${hint}. Final image remains hidden until assembly.`,
    targetPrinter: "A1 mini",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    files: [
      { name: `${slug}.manifest.json`, type: "JSON", description: "Project metadata for Google Drive sync" },
      { name: `${slug}-source.png`, type: "PNG", description: "Hidden AI source image" },
      { name: `${slug}-plate.3mf`, type: "3MF", description: "Full reference plate for slicing checks" }
    ],
    pieces: Array.from({ length: pieceCount }, (_, index) => {
      const day = index + 1;
      return {
        id: crypto.randomUUID(),
        day,
        name: `Mystery piece ${day}`,
        filename: `${slug}-day-${String(day).padStart(2, "0")}.3mf`,
        scheduledFor: addDays(startDate, index),
        status: "pending",
        note: "Print this piece overnight, then add it to the weekly assembly tray."
      };
    })
  };
}

function normalizeProjectManifest(manifest) {
  if (!manifest || typeof manifest !== "object") {
    throw new Error("Manifest must be a JSON object.");
  }
  if (!manifest.name || !Array.isArray(manifest.pieces)) {
    throw new Error("Manifest needs a name and pieces array.");
  }

  const slug = manifest.slug || slugify(manifest.name);
  return {
    id: manifest.id || slug,
    name: manifest.name,
    slug,
    status: manifest.status || "generated",
    summary: manifest.summary || "Generated Enigma Print puzzle.",
    targetPrinter: manifest.targetPrinter || "A1 mini",
    createdAt: manifest.createdAt || new Date().toISOString(),
    updatedAt: manifest.updatedAt || new Date().toISOString(),
    assets: manifest.assets || {},
    files: Array.isArray(manifest.files) ? manifest.files : [],
    pieces: manifest.pieces.map((piece, index) => ({
      id: piece.id || `${slug}-${index + 1}`,
      day: piece.day || index + 1,
      name: piece.name || `Day ${index + 1} reveal`,
      filename: piece.filename || `${slug}-day-${String(index + 1).padStart(2, "0")}.stl`,
      path: piece.path || piece.url || "",
      scheduledFor: piece.scheduledFor || addDays(new Date().toISOString().slice(0, 10), index),
      status: piece.status || "pending",
      printedAt: piece.printedAt || null,
      note: piece.note || "Generated puzzle piece."
    }))
  };
}

async function openPieceWithHelper(project, piece) {
  try {
    const response = await fetch(`${HELPER_URL}/open-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: project.id,
        pieceId: piece.id,
        path: piece.path
      })
    });
    if (!response.ok) throw new Error(await response.text());
  } catch {
    window.alert("Local helper is not running yet. Download the 3MF and open it in Bambu Studio, or start scripts/local_helper.py.");
  }
}

async function slicePieceWithHelper(project, piece) {
  try {
    const response = await fetch(`${HELPER_URL}/slice-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: project.id,
        pieceId: piece.id,
        path: piece.path
      })
    });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    window.alert(
      `G-code sliced for ${piece.filename}\n\n` +
      `${result.outputs.join("\n")}\n\n` +
      "Bambu Studio's open window will not change; this is a headless CLI slice."
    );
  } catch {
    window.alert("Local helper could not slice this piece. Check that scripts/local_helper.py is running and Bambu Studio is installed.");
  }
}

async function printPieceWithHelper(project, piece, action) {
  const confirmed = window.confirm(`Slice and send ${piece.filename} as a single-colour print with AMS off?`);
  if (!confirmed) return;

  const progress = startPrintProgress(piece);
  try {
    updateBusyAction(action, "Slicing...");
    const response = await fetch(`${HELPER_URL}/print-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: project.id,
        pieceId: piece.id,
        path: piece.path
      })
    });
    updateBusyAction(action, "Checking...");
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || "Print request failed.");
    finishPrintProgress(progress, {
      ok: true,
      message: `Sent ${piece.filename} to ${result.printerHost}. AMS is off; use the loaded single filament.`,
      stages: result.stages || []
    });
  } catch (error) {
    finishPrintProgress(progress, {
      ok: false,
      message: `Could not send print job: ${error.message}`,
      stages: []
    });
  }
}

function startPrintProgress(piece) {
  const progress = {
    index: 0,
    timer: null
  };
  els.progressTitle.textContent = piece.filename;
  els.progressMessage.textContent = "Starting local slice. Bambu Studio may take about 30 seconds here.";
  els.progressCloseButton.hidden = true;
  renderProgress(progress.index, "running");
  if (!els.progressDialog.open) els.progressDialog.showModal();

  progress.timer = window.setInterval(() => {
    if (progress.index < PRINT_PHASES.length - 2) {
      progress.index += 1;
      renderProgress(progress.index, "running");
      els.progressMessage.textContent = progressMessageForPhase(progress.index);
    }
  }, 7000);
  return progress;
}

function finishPrintProgress(progress, result) {
  window.clearInterval(progress.timer);
  const finalIndex = result.ok ? PRINT_PHASES.length - 1 : Math.min(progress.index, PRINT_PHASES.length - 2);
  renderProgress(finalIndex, result.ok ? "done" : "error");
  els.progressMessage.textContent = result.ok
    ? result.message
    : `${result.message}. Check the helper terminal and printer screen before trying again.`;
  if (result.stages.length) {
    els.progressMessage.textContent += `\n\n${result.stages.join("\n")}`;
  }
  els.progressCloseButton.hidden = false;
}

function renderProgress(activeIndex, status) {
  const phase = PRINT_PHASES[activeIndex];
  const percent = phase.percent;
  els.progressPercent.textContent = `${percent}%`;
  els.progressFill.style.width = `${percent}%`;
  els.progressSteps.innerHTML = PRINT_PHASES.map((item, index) => {
    const stateClass = index < activeIndex || status === "done" ? "done" : index === activeIndex ? status : "pending";
    return `<li class="${stateClass}"><span></span>${escapeHtml(item.label)}</li>`;
  }).join("");
}

function progressMessageForPhase(index) {
  return [
    "Reading printer config and checking LAN reachability.",
    "Slicing the 3MF headlessly. The Bambu Studio window will not visibly change.",
    "Wrapping the sliced G-code into a Bambu project package.",
    "Uploading to the printer over FTPS. This can be the slowest step.",
    "Sending the final project_file command with AMS disabled."
  ][index] || "Waiting for printer response.";
}

async function withBusyAction(button, label, task) {
  const originalText = button.textContent;
  updateBusyAction(button, label);
  try {
    await task();
  } finally {
    button.disabled = false;
    button.classList.remove("busy");
    button.textContent = originalText;
  }
}

function updateBusyAction(button, label) {
  if (!button) return;
  button.disabled = true;
  button.classList.add("busy");
  button.textContent = label;
}

function addDays(dateString, days) {
  const date = new Date(`${dateString}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatDate(dateString) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    weekday: "short"
  }).format(new Date(`${dateString}T00:00:00`));
}

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 64) || "weekly-puzzle";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (location.protocol === "file:") return;
  navigator.serviceWorker.register("service-worker.js").then((registration) => {
    registration.update();
  }).catch(() => {});
}

bootstrap();
