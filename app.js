const STORAGE_KEY = "enigmaprint.projects.v2";
const HELPER_URL = "http://127.0.0.1:4777";

const els = {
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
  startInput: document.querySelector("#startInput")
};

let state = {
  projects: [],
  selectedProjectId: null
};

async function bootstrap() {
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
        ${piece.path ? `<button class="piece-link" type="button" data-piece-action="print" data-piece-id="${escapeHtml(piece.id)}">Print G-code</button>` : ""}
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
          <button class="piece-link" type="button" data-piece-action="print" data-piece-id="${escapeHtml(piece.id)}">Print G-code</button>
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
  const confirmed = window.confirm(`Slice and send ${piece.filename} to the configured printer?`);
  if (!confirmed) return;

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
    window.alert(
      `Print command sent for ${piece.filename}\n\n` +
      `Uploaded: ${result.remoteFilename}\n` +
      `Printer: ${result.printerHost}\n\n` +
      `${(result.stages || []).join("\n")}`
    );
  } catch (error) {
    window.alert(`Could not send print job: ${error.message}`);
  }
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
