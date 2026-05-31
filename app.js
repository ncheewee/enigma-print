/**
 * Enigma Print mobile dashboard.
 *
 * This keeps the proven local generation/print flow from the original app:
 * generated manifests -> 3MF pieces -> local helper slice/package/upload/print.
 * The view layer uses Gemini's four-screen mobile concept.
 */

const STORAGE_KEY = "enigmaprint.projects.v2";
const HELPER_URL_KEY = "enigmaprint.helperUrl";
const APP_VERSION = "v0.5.0-mobile";

const PRINT_PHASES = [
  { key: "config", label: "Load printer settings", percent: 8 },
  { key: "slice", label: "Slice 3MF to G-code", percent: 28 },
  { key: "package", label: "Package printer project", percent: 50 },
  { key: "upload", label: "Upload to A1 mini", percent: 76 },
  { key: "send", label: "Send AMS-off print command", percent: 92 },
  { key: "done", label: "Printer accepted job", percent: 100 }
];

const els = {
  projectSub: document.querySelector("#projectSub"),
  settingsButton: document.querySelector("#settingsButton"),
  settingsDialog: document.querySelector("#settingsDialog"),
  settingsForm: document.querySelector("#settingsForm"),
  helperUrlInput: document.querySelector("#helperUrlInput"),
  pingDot: document.querySelector("#pingDot"),
  pingStatusMsg: document.querySelector("#pingStatusMsg"),
  cancelSettingsBtn: document.querySelector("#cancelSettingsBtn"),
  projectList: document.querySelector("#projectList"),
  newProjectButton: document.querySelector("#newProjectButton"),
  importButton: document.querySelector("#importButton"),
  importInput: document.querySelector("#importInput"),
  exportButton: document.querySelector("#exportButton"),
  resetButton: document.querySelector("#resetButton"),
  projectDialog: document.querySelector("#projectDialog"),
  projectForm: document.querySelector("#projectForm"),
  nameInput: document.querySelector("#nameInput"),
  hintInput: document.querySelector("#hintInput"),
  piecesInput: document.querySelector("#piecesInput"),
  startInput: document.querySelector("#startInput"),

  obliqueViewer: document.querySelector("#obliqueViewer"),
  completionBadge: document.querySelector("#completionBadge"),
  prevDayButton: document.querySelector("#prevDayButton"),
  nextDayButton: document.querySelector("#nextDayButton"),
  pieceDayLabel: document.querySelector("#pieceDayLabel"),
  pieceNameLabel: document.querySelector("#pieceNameLabel"),
  progressStrip: document.querySelector("#progressStrip"),
  actionPanel: document.querySelector("#actionPanel"),
  printCta: document.querySelector("#printCta"),
  printedChip: document.querySelector("#printedChip"),
  printedTimeLabel: document.querySelector("#printedTimeLabel"),
  statTime: document.querySelector("#statTime"),
  statFilament: document.querySelector("#statFilament"),
  statStatus: document.querySelector("#statStatus"),

  focusSection: document.querySelector("#focusSection"),
  assemblySection: document.querySelector("#assemblySection"),
  jigsawBoard: document.querySelector("#jigsawBoard"),
  jigsawContainer: document.querySelector(".jigsaw-container"),
  jigsawPiecesGroup: document.querySelector("#jigsawPiecesGroup"),
  revealLockBox: document.querySelector("#revealLockBox"),
  revealChip: document.querySelector("#revealChip"),
  hideRevealBtn: document.querySelector("#hideRevealBtn"),
  backToTodayBtn: document.querySelector("#backToTodayBtn"),

  printProgressDialog: document.querySelector("#printProgressDialog"),
  progressTitle: document.querySelector("#progressTitle"),
  progressPercent: document.querySelector("#progressPercent"),
  progressFill: document.querySelector("#progressFill"),
  progressSteps: document.querySelector("#progressSteps"),
  progressMessage: document.querySelector("#progressMessage"),
  progressCloseButton: document.querySelector("#progressCloseButton")
};

let state = {
  projects: [],
  selectedProjectId: null,
  selectedDay: 1,
  helperUrl: "http://127.0.0.1:4777",
  revealed: false
};

let theta = 45;
let depth = 14;
let isDragging = false;
let startX = 0;
let initialTheta = 45;
let progressTimer = null;
let currentPhaseIndex = 0;

async function bootstrap() {
  state.helperUrl = localStorage.getItem(HELPER_URL_KEY) || state.helperUrl;
  els.helperUrlInput.value = state.helperUrl;
  els.startInput.value = new Date().toISOString().slice(0, 10);

  state.projects = loadProjectsFromStorage();
  await loadPublishedProjects();
  state.selectedProjectId = state.projects[0]?.id || null;
  setSelectedDayToNextPrint();

  attachEvents();
  updateUI();
  checkHelperConnection();
}

function attachEvents() {
  els.settingsButton.addEventListener("click", () => {
    renderProjectList();
    els.settingsDialog.showModal();
    checkHelperConnection();
  });

  els.cancelSettingsBtn.addEventListener("click", () => els.settingsDialog.close());

  els.settingsForm.addEventListener("submit", (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    state.helperUrl = els.helperUrlInput.value.trim().replace(/\/$/, "");
    localStorage.setItem(HELPER_URL_KEY, state.helperUrl);
    els.settingsDialog.close();
    checkHelperConnection();
  });

  els.newProjectButton.addEventListener("click", () => {
    els.settingsDialog.close();
    els.projectDialog.showModal();
  });

  els.projectForm.addEventListener("submit", (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const project = createProjectFromForm(new FormData(els.projectForm));
    state.projects = [project, ...state.projects.filter((item) => item.id !== project.id)];
    state.selectedProjectId = project.id;
    state.selectedDay = 1;
    saveProjectsToStorage();
    els.projectForm.reset();
    els.startInput.value = new Date().toISOString().slice(0, 10);
    els.projectDialog.close();
    updateUI();
  });

  els.importButton.addEventListener("click", () => els.importInput.click());
  els.importInput.addEventListener("change", importManifest);
  els.exportButton.addEventListener("click", exportSelectedProject);
  els.resetButton.addEventListener("click", resetPublishedData);

  els.progressStrip.addEventListener("click", (event) => {
    const dot = event.target.closest(".strip-dot");
    if (!dot) return;
    state.selectedDay = Number(dot.dataset.day);
    updateUI();
  });

  els.prevDayButton.addEventListener("click", () => {
    if (state.selectedDay <= 1) return;
    state.selectedDay -= 1;
    updateUI();
  });

  els.nextDayButton.addEventListener("click", () => {
    const project = getSelectedProject();
    if (!project || state.selectedDay >= project.pieces.length) return;
    state.selectedDay += 1;
    updateUI();
  });

  els.printCta.addEventListener("click", () => {
    const project = getSelectedProject();
    if (!project) {
      renderProjectList();
      els.settingsDialog.showModal();
      return;
    }
    if (project.pieces.every((piece) => piece.status === "printed")) {
      openAssemblyScreen();
    } else {
      triggerPrintJob();
    }
  });

  els.backToTodayBtn.addEventListener("click", () => {
    els.assemblySection.hidden = true;
    els.focusSection.hidden = false;
  });

  els.revealLockBox.addEventListener("click", () => {
    state.revealed = true;
    els.revealLockBox.hidden = true;
    els.revealChip.hidden = false;
    drawJigsaw();
  });

  els.hideRevealBtn.addEventListener("click", () => {
    state.revealed = false;
    els.revealLockBox.hidden = false;
    els.revealChip.hidden = true;
    drawJigsaw();
  });

  els.progressCloseButton.addEventListener("click", () => els.printProgressDialog.close());
  els.printProgressDialog.addEventListener("cancel", (event) => {
    if (els.progressCloseButton.hidden) event.preventDefault();
  });

  setupObliqueDrag();
}

function loadProjectsFromStorage() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return [];
  try {
    const projects = JSON.parse(saved);
    return Array.isArray(projects) ? projects : [];
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return [];
  }
}

async function loadPublishedProjects() {
  try {
    const response = await fetch("projects/index.json", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (!Array.isArray(data.projects)) return;

    const imported = data.projects.map(normalizeProjectManifest);
    const existing = new Map(state.projects.map((project) => [project.id, project]));
    for (const project of imported) {
      const local = existing.get(project.id);
      if (local) {
        project.pieces.forEach((piece, index) => {
          const localPiece = local.pieces[index];
          if (localPiece?.status === "printed") {
            piece.status = "printed";
            piece.printedAt = localPiece.printedAt;
          }
        });
      }
      existing.set(project.id, project);
    }

    state.projects = [
      ...imported,
      ...state.projects.filter((project) => !imported.some((item) => item.id === project.id))
    ];
    saveProjectsToStorage();
  } catch {
    // Opening index.html directly may not expose projects/index.json.
  }
}

function saveProjectsToStorage() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.projects));
}

function getSelectedProject() {
  return state.projects.find((project) => project.id === state.selectedProjectId) || state.projects[0] || null;
}

function setSelectedDayToNextPrint() {
  const project = getSelectedProject();
  if (!project) {
    state.selectedDay = 1;
    return;
  }
  const nextIndex = project.pieces.findIndex((piece) => piece.status !== "printed");
  state.selectedDay = nextIndex === -1 ? project.pieces.length : nextIndex + 1;
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
      name: piece.name || `Piece ${index + 1}`,
      filename: piece.filename || `piece-${String(index + 1).padStart(2, "0")}.3mf`,
      path: piece.path || piece.url || "",
      gcode3mfPath: piece.gcode3mfPath || "",
      scheduledFor: piece.scheduledFor || addDays(new Date().toISOString().slice(0, 10), index),
      status: piece.status || "pending",
      printedAt: piece.printedAt || null,
      printTimeMinutes: piece.printTimeMinutes || null,
      filamentWeightG: piece.filamentWeightG || null,
      note: piece.note || "Generated puzzle piece."
    }))
  };
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
    summary: `A ${pieceCount}-day AI generated puzzle queued from the hint: ${hint}. Generate the 3MF pieces locally, then import the manifest.`,
    targetPrinter: "A1 mini",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    assets: {},
    files: [
      { name: `${slug}.manifest.json`, type: "JSON", description: "Project metadata for generated pieces" },
      { name: `${slug}-source.png`, type: "PNG", description: "Hidden source image" },
      { name: `${slug}-plate.3mf`, type: "3MF", description: "Reference plate" }
    ],
    pieces: Array.from({ length: pieceCount }, (_, index) => {
      const day = index + 1;
      return {
        id: crypto.randomUUID(),
        day,
        name: `Mystery piece ${day}`,
        filename: `${slug}-day-${String(day).padStart(2, "0")}.3mf`,
        path: "",
        scheduledFor: addDays(startDate, index),
        status: "pending",
        printedAt: null,
        note: "Generate this piece locally, import the manifest, then print overnight."
      };
    })
  };
}

async function importManifest(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const project = normalizeProjectManifest(JSON.parse(await file.text()));
    state.projects = [project, ...state.projects.filter((item) => item.id !== project.id)];
    state.selectedProjectId = project.id;
    setSelectedDayToNextPrint();
    saveProjectsToStorage();
    updateUI();
  } catch (error) {
    window.alert(`Could not import manifest: ${error.message}`);
  } finally {
    event.target.value = "";
  }
}

function exportSelectedProject() {
  const project = getSelectedProject();
  if (!project) return;
  const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${project.slug}.manifest.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function resetPublishedData() {
  localStorage.removeItem(STORAGE_KEY);
  state.projects = [];
  loadPublishedProjects().then(() => {
    state.selectedProjectId = state.projects[0]?.id || null;
    setSelectedDayToNextPrint();
    updateUI();
    renderProjectList();
  });
}

function updateUI() {
  const project = getSelectedProject();
  if (!project) {
    renderEmptyState();
    return;
  }

  state.selectedProjectId = project.id;
  state.selectedDay = Math.min(Math.max(state.selectedDay, 1), project.pieces.length);
  const piece = project.pieces[state.selectedDay - 1];
  const printedCount = project.pieces.filter((item) => item.status === "printed").length;
  const isComplete = piece.status === "printed";
  const isProjectComplete = printedCount === project.pieces.length;

  els.focusSection.hidden = false;
  els.assemblySection.hidden = true;
  els.projectSub.textContent = `${project.targetPrinter} · ${project.name}`;
  els.pieceDayLabel.textContent = `DAY ${piece.day} OF ${project.pieces.length}`;
  els.pieceNameLabel.textContent = piece.name;
  els.statTime.textContent = piece.printTimeMinutes ? `${piece.printTimeMinutes}m` : "TBD";
  els.statFilament.textContent = piece.filamentWeightG ? `${piece.filamentWeightG}g` : "TBD";
  els.statStatus.textContent = getPieceStatusLabel(piece);
  els.statStatus.style.color = isComplete ? "var(--teal-200)" : "var(--amber-400)";

  els.prevDayButton.disabled = state.selectedDay <= 1;
  els.nextDayButton.disabled = state.selectedDay >= project.pieces.length;

  drawOblique();
  renderProgressStrip(project);
  renderActionPanel(project, piece, isComplete, isProjectComplete);
  drawJigsaw();
  renderProjectList();
}

function renderEmptyState() {
  els.projectSub.textContent = `No project loaded · ${APP_VERSION}`;
  els.pieceDayLabel.textContent = "READY";
  els.pieceNameLabel.textContent = "Import a generated manifest";
  els.obliqueViewer.innerHTML = `<div class="empty-viewer">E</div>`;
  els.completionBadge.textContent = "Empty";
  els.progressStrip.innerHTML = "";
  els.printCta.hidden = false;
  els.printCta.className = "amber-btn";
  els.printCta.innerHTML = `<span class="btn-icon">+</span> Load puzzle`;
  els.printedChip.hidden = true;
  els.statTime.textContent = "--";
  els.statFilament.textContent = "--";
  els.statStatus.textContent = "EMPTY";
}

function renderProjectList() {
  if (!els.projectList) return;
  els.projectList.innerHTML = state.projects.map((project) => {
    const printed = project.pieces.filter((piece) => piece.status === "printed").length;
    const active = project.id === state.selectedProjectId ? " active" : "";
    return `
      <button class="project-picker${active}" type="button" data-project-id="${escapeHtml(project.id)}">
        <span>
          <strong>${escapeHtml(project.name)}</strong>
          <small>${printed}/${project.pieces.length} pieces · ${escapeHtml(getProjectStatus(project))}</small>
        </span>
      </button>
    `;
  }).join("") || `<p class="dialog-explain">No generated manifests loaded yet.</p>`;

  els.projectList.querySelectorAll("[data-project-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedProjectId = button.dataset.projectId;
      setSelectedDayToNextPrint();
      els.settingsDialog.close();
      updateUI();
    });
  });
}

function renderProgressStrip(project) {
  els.progressStrip.innerHTML = project.pieces.map((piece, index) => {
    let dotClass = "strip-dot";
    if (index === state.selectedDay - 1) dotClass += " active";
    else if (piece.status === "printed") dotClass += " complete";
    else dotClass += " pending";
    return `<button class="${dotClass}" data-day="${index + 1}" type="button" aria-label="Go to day ${index + 1}"></button>`;
  }).join("");
}

function renderActionPanel(project, piece, isComplete, isProjectComplete) {
  if (isProjectComplete) {
    els.printCta.hidden = false;
    els.printCta.className = "amber-btn";
    els.printCta.innerHTML = `<span class="btn-icon">+</span> Piece it together`;
    els.printedChip.hidden = true;
  } else if (isComplete) {
    els.printCta.hidden = true;
    els.printedChip.hidden = false;
    els.printedTimeLabel.textContent = piece.printedAt ? formatDate(piece.printedAt) : "Complete";
  } else {
    els.printCta.hidden = false;
    els.printCta.className = "coral-btn";
    els.printCta.innerHTML = `<span class="btn-icon">⚡</span> Send to A1 mini`;
    els.printedChip.hidden = true;
  }

  let tools = document.querySelector("#pieceTools");
  if (!tools) {
    tools = document.createElement("div");
    tools.id = "pieceTools";
    tools.className = "piece-tool-row";
    els.actionPanel.append(tools);
  }

  tools.innerHTML = `
    ${piece.path ? `<a class="tool-chip" href="${escapeHtml(piece.path)}">Download</a>` : ""}
    ${piece.path ? `<button class="tool-chip" type="button" data-tool-action="open">Open</button>` : ""}
    ${piece.path ? `<button class="tool-chip" type="button" data-tool-action="slice">Slice</button>` : ""}
    <button class="tool-chip" type="button" data-tool-action="mark">${isComplete ? "Undo printed" : "Mark printed"}</button>
  `;

  tools.querySelectorAll("[data-tool-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.toolAction === "open") await openPieceWithHelper(project, piece);
      if (button.dataset.toolAction === "slice") await slicePieceWithHelper(project, piece, button);
      if (button.dataset.toolAction === "mark") togglePrinted(project, piece);
    });
  });
}

async function checkHelperConnection() {
  updatePingStatus("pending", "Checking local helper...");
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    const response = await fetch(`${state.helperUrl}/health`, {
      method: "GET",
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    updatePingStatus(response.ok ? "success" : "failed", response.ok ? "Local helper is active." : "Helper returned an error.");
  } catch {
    updatePingStatus("failed", "Local helper is offline.");
  }
}

function updatePingStatus(type, message) {
  els.pingDot.className = `status-dot ping-${type}`;
  els.pingStatusMsg.textContent = message;
}

async function triggerPrintJob() {
  const project = getSelectedProject();
  const piece = project?.pieces[state.selectedDay - 1];
  if (!project || !piece) return;
  if (!piece.path) {
    window.alert("This queued piece does not have a generated 3MF path yet. Generate the puzzle locally, then import the manifest.");
    return;
  }

  const confirmed = window.confirm(`Slice and send ${piece.filename} as a single-colour print with AMS off?`);
  if (!confirmed) return;

  startProgressModal(piece);
  try {
    const response = await fetch(`${state.helperUrl}/print-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: project.id,
        pieceId: piece.id,
        path: piece.path
      })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.message || "Print request failed.");
    }

    piece.status = "printed";
    piece.printedAt = new Date().toISOString();
    project.updatedAt = new Date().toISOString();
    saveProjectsToStorage();
    finishProgressModal(true, `Sent ${piece.filename} to ${result.printerHost}. AMS is off; use the loaded single filament.`, result.stages || []);
    updateUI();
  } catch (error) {
    finishProgressModal(false, `Could not send print job: ${error.message}. Check scripts/local_helper.py and the printer screen before trying again.`, []);
  }
}

async function openPieceWithHelper(project, piece) {
  try {
    const response = await fetch(`${state.helperUrl}/open-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId: project.id, pieceId: piece.id, path: piece.path })
    });
    if (!response.ok) throw new Error(await response.text());
  } catch {
    window.alert("Local helper is not running. Start scripts/local_helper.py, or download the 3MF and open it in Bambu Studio.");
  }
}

async function slicePieceWithHelper(project, piece, button) {
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Slicing...";
  try {
    const response = await fetch(`${state.helperUrl}/slice-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId: project.id, pieceId: piece.id, path: piece.path })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || "Slice failed.");
    window.alert(`G-code sliced for ${piece.filename}\n\n${result.outputs.join("\n")}`);
  } catch (error) {
    window.alert(`Local helper could not slice this piece: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function togglePrinted(project, piece) {
  if (piece.status === "printed") {
    piece.status = "pending";
    piece.printedAt = null;
  } else {
    piece.status = "printed";
    piece.printedAt = new Date().toISOString();
  }
  project.updatedAt = new Date().toISOString();
  saveProjectsToStorage();
  updateUI();
}

function startProgressModal(piece) {
  els.progressTitle.textContent = piece.filename;
  els.progressMessage.textContent = "Starting local slice. Bambu Studio may take about 30 seconds here.";
  els.progressCloseButton.hidden = true;
  currentPhaseIndex = 0;
  renderStepsList(0, "running");
  if (!els.printProgressDialog.open) els.printProgressDialog.showModal();
  resumeProgressTimer();
}

function resumeProgressTimer() {
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(() => {
    if (currentPhaseIndex < PRINT_PHASES.length - 2) {
      currentPhaseIndex += 1;
      renderStepsList(currentPhaseIndex, "running");
      els.progressMessage.textContent = progressMessageForPhase(currentPhaseIndex);
    }
  }, 7000);
}

function finishProgressModal(ok, message, stages = []) {
  if (progressTimer) clearInterval(progressTimer);
  const finalIndex = ok ? PRINT_PHASES.length - 1 : Math.min(currentPhaseIndex, PRINT_PHASES.length - 2);
  renderStepsList(finalIndex, ok ? "done" : "error");
  els.progressMessage.textContent = stages.length ? `${message}\n\n${stages.join("\n")}` : message;
  els.progressCloseButton.hidden = false;
}

function renderStepsList(activeIndex, status) {
  const phase = PRINT_PHASES[activeIndex];
  els.progressPercent.textContent = `${phase.percent}%`;
  els.progressFill.style.width = `${phase.percent}%`;
  els.progressSteps.innerHTML = PRINT_PHASES.map((item, index) => {
    const stateClass = index < activeIndex || status === "done" ? "done" : index === activeIndex ? status : "pending";
    return `<li class="${stateClass}">${escapeHtml(item.label)}</li>`;
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

function openAssemblyScreen() {
  els.focusSection.hidden = true;
  els.assemblySection.hidden = false;
  state.revealed = false;
  els.revealLockBox.hidden = false;
  els.revealChip.hidden = true;
  drawJigsaw();
}

function getPieceStatusLabel(piece) {
  if (piece.status === "printed") return "PRINTED";
  if (piece.status === "sliced") return "SLICED";
  if (piece.path) return "READY";
  return "QUEUED";
}

function getProjectStatus(project) {
  const printed = project.pieces.filter((piece) => piece.status === "printed").length;
  if (printed === project.pieces.length) return "complete";
  if (printed > 0) return "active";
  return project.status || "generated";
}

function drawOblique() {
  const project = getSelectedProject();
  if (!project) return;
  const piece = project.pieces[state.selectedDay - 1];
  const isComplete = piece.status === "printed";
  const isProjectComplete = project.pieces.every((item) => item.status === "printed");
  const rad = (theta * Math.PI) / 180;
  const dxVec = depth * Math.cos(rad);
  const dyVec = depth * Math.sin(rad);
  const d = piece.day;
  const topType = (d % 3) - 1;
  const rightType = ((d + 1) % 3) - 1;
  const bottomType = ((d + 2) % 3) - 1;
  const leftType = ((d + 3) % 3) - 1;
  const p1 = { x: 55, y: 55 };
  const p2 = { x: 145, y: 55 };
  const p3 = { x: 145, y: 145 };
  const p4 = { x: 55, y: 145 };
  const path = getPuzzlePiecePath(p1, p2, p3, p4, topType, rightType, bottomType, leftType);
  const baseTopFill = isComplete ? "#5DCAA5" : "#FAC775";
  const baseTopStroke = isComplete ? "#84e6c4" : "#ffdba3";

  let svgContent = `
    <svg viewBox="0 0 200 200" width="100%" height="100%" style="overflow: visible;">
      <defs>
        <filter id="shadowBlur" x="-20%" y="-20%" width="150%" height="150%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="6" />
          <feOffset dx="${dxVec * 1.5}" dy="${dyVec * 1.5}" />
          <feComponentTransfer><feFuncA type="linear" slope="0.65"/></feComponentTransfer>
          <feMerge><feMergeNode /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <clipPath id="topFaceClip"><path d="${path}" /></clipPath>
      </defs>
      <path d="${path}" fill="#000" filter="url(#shadowBlur)" style="opacity: 0.6; mix-blend-mode: multiply;" />
  `;

  for (let i = 14; i >= 1; i -= 1) {
    const ratio = i / 14;
    const tx = dxVec * ratio;
    const ty = dyVec * ratio;
    const fill = isComplete
      ? `hsl(161, ${69 + ratio * 10}%, ${24 - ratio * 15}%)`
      : `hsl(36, ${86 + ratio * 10}%, ${34 - ratio * 20}%)`;
    svgContent += `<g transform="translate(${tx}, ${ty})"><path d="${path}" fill="${fill}" stroke="${fill}" stroke-width="1" /></g>`;
  }

  svgContent += `
      <path d="${path}" fill="${baseTopFill}" stroke="${baseTopStroke}" stroke-width="1.2" class="viewer-3d-piece-top" />
      <g clip-path="url(#topFaceClip)">
        <circle cx="100" cy="100" r="18" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="36" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="54" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="72" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <line x1="55" y1="100" x2="145" y2="100" stroke="rgba(255,255,255,0.15)" stroke-width="1" />
        <line x1="100" y1="55" x2="100" y2="145" stroke="rgba(255,255,255,0.15)" stroke-width="1" />
      </g>
  `;

  if (isProjectComplete) {
    ["#EF9F27", "#FAC775", "#D85A30", "#1D9E75", "#5DCAA5"].forEach((fill, i) => {
      const cx = 48 + i * 26;
      const cy = 36 + Math.sin(i) * 24;
      svgContent += `<circle cx="${cx}" cy="${cy}" r="${3 + (i % 2)}" fill="${fill}" style="opacity: 0.85;" />`;
    });
  }

  els.obliqueViewer.innerHTML = `${svgContent}</svg>`;
  els.completionBadge.textContent = isProjectComplete ? `${project.pieces.length}/${project.pieces.length} Complete` : `Day ${piece.day}`;
  els.completionBadge.classList.toggle("complete", isComplete);
}

function drawJigsaw() {
  const project = getSelectedProject();
  if (!project) return;
  const pieces = project.pieces;
  const count = pieces.length;
  const imageSource = project.assets?.sourceHidden || project.assets?.preview || "";
  if (project.assets?.preview) {
    drawGeneratedPreviewJigsaw(project, pieces);
    return;
  }

  els.jigsawBoard.setAttribute("viewBox", "0 0 140 84");
  els.jigsawContainer.classList.remove("preview-mode");
  const width = 140;
  const height = 84;
  const grid = makeJigsawGrid(count);
  let svgOut = "";
  let defsOut = "";

  grid.forEach((item, index) => {
    const piece = pieces[index];
    if (!piece) return;
    const isPrinted = piece.status === "printed";
    const isToday = piece.status !== "printed" && index === state.selectedDay - 1;
    let dStr = `M ${item.p[0].x} ${item.p[0].y}`;
    for (let i = 0; i < item.p.length; i += 1) {
      dStr += getEdgePath(item.p[i], item.p[(i + 1) % item.p.length], item.t[i] || 0);
    }
    dStr += " Z";

    const clipId = `jigsaw-clip-${index}`;
    defsOut += `<clipPath id="${clipId}"><path d="${dStr}" /></clipPath>`;

    if (state.revealed && imageSource) {
      svgOut += `
        <image href="${escapeHtml(imageSource)}" x="0" y="0" width="${width}" height="${height}" clip-path="url(#${clipId})" preserveAspectRatio="none" />
        <path d="${dStr}" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="0.55" />
        <text x="${item.center.x}" y="${item.center.y}" class="jigsaw-piece-text jigsaw-piece-revealed-text">${index + 1}</text>
      `;
    } else {
      const fill = isPrinted ? "var(--teal-400)" : isToday ? "rgba(239, 159, 39, 0.22)" : "#1a221d";
      const stroke = isPrinted ? "rgba(255,255,255,0.15)" : isToday ? "var(--amber-400)" : "rgba(255,255,255,0.04)";
      const textFill = isPrinted ? "#ffffff" : isToday ? "var(--amber-100)" : "var(--ink-muted)";
      svgOut += `
        <path d="${dStr}" fill="${fill}" stroke="${stroke}" stroke-width="0.7" class="jigsaw-piece-path" />
        <text x="${item.center.x}" y="${item.center.y}" fill="${textFill}" class="jigsaw-piece-text">${index + 1}</text>
      `;
    }
  });

  const defs = els.jigsawBoard.querySelector("defs");
  defs.innerHTML = `<clipPath id="revealClip"><rect x="0" y="0" width="${width}" height="${height}" rx="4" /></clipPath>${defsOut}`;
  els.jigsawPiecesGroup.innerHTML = svgOut;
}

function drawGeneratedPreviewJigsaw(project, pieces) {
  els.jigsawBoard.setAttribute("viewBox", "0 0 100 100");
  els.jigsawContainer.classList.add("preview-mode");
  const defs = els.jigsawBoard.querySelector("defs");
  defs.innerHTML = "";
  const previewClass = state.revealed ? "generated-preview-image revealed" : "generated-preview-image hidden-reveal";

  els.jigsawPiecesGroup.innerHTML = `
    <image href="${escapeHtml(project.assets.preview)}" x="0" y="0" width="100" height="100" preserveAspectRatio="xMidYMid meet" class="${previewClass}" />
    ${state.revealed ? "" : '<rect x="0" y="0" width="100" height="100" rx="5" class="generated-preview-veil" />'}
  `;
}

function makeJigsawGrid(count) {
  if (count <= 4) {
    const v = [
      [{ x: 0, y: 0 }, { x: 70, y: 0 }, { x: 140, y: 0 }],
      [{ x: 0, y: 42 }, { x: 70, y: 42 }, { x: 140, y: 42 }],
      [{ x: 0, y: 84 }, { x: 70, y: 84 }, { x: 140, y: 84 }]
    ];
    return [
      { p: [v[0][0], v[0][1], v[1][1], v[1][0]], t: [0, 1, -1, 0], center: { x: 35, y: 21 } },
      { p: [v[0][1], v[0][2], v[1][2], v[1][1]], t: [0, 0, 1, -1], center: { x: 105, y: 21 } },
      { p: [v[1][0], v[1][1], v[2][1], v[2][0]], t: [1, -1, 0, 0], center: { x: 35, y: 63 } },
      { p: [v[1][1], v[1][2], v[2][2], v[2][1]], t: [-1, 0, 0, 1], center: { x: 105, y: 63 } }
    ];
  }

  const v = {
    r0: [{ x: 0, y: 0 }, { x: 46.6, y: 0 }, { x: 93.3, y: 0 }, { x: 140, y: 0 }],
    r1: [{ x: 0, y: 28 }, { x: 46.6, y: 28 }, { x: 93.3, y: 28 }, { x: 140, y: 28 }],
    r2: [{ x: 0, y: 56 }, { x: 46.6, y: 56 }, { x: 93.3, y: 56 }, { x: 140, y: 56 }],
    r3: [{ x: 0, y: 84 }, { x: 35, y: 84 }, { x: 105, y: 84 }, { x: 140, y: 84 }]
  };
  return [
    { p: [v.r0[0], v.r0[1], v.r1[1], v.r1[0]], t: [0, 1, -1, 0], center: { x: 23.3, y: 14 } },
    { p: [v.r0[1], v.r0[2], v.r1[2], v.r1[1]], t: [0, 1, -1, -1], center: { x: 70, y: 14 } },
    { p: [v.r0[2], v.r0[3], v.r1[3], v.r1[2]], t: [0, 0, -1, -1], center: { x: 116.6, y: 14 } },
    { p: [v.r1[0], v.r1[1], v.r2[1], { x: 35, y: 56 }, v.r3[1], v.r3[0]], t: [1, -1, 0, -1, 0, 0], center: { x: 21, y: 48 } },
    { p: [v.r1[1], v.r1[2], v.r2[2], v.r2[1]], t: [1, 1, -1, 1], center: { x: 70, y: 42 } },
    { p: [v.r1[2], v.r1[3], v.r3[3], v.r3[2], { x: 105, y: 56 }, v.r2[2]], t: [1, 0, 0, 1, 0, -1], center: { x: 119, y: 48 } },
    { p: [{ x: 35, y: 56 }, { x: 105, y: 56 }, v.r3[2], v.r3[1]], t: [1, -1, 0, 1], center: { x: 70, y: 70 } }
  ];
}

function getPuzzlePiecePath(p1, p2, p3, p4, topType, rightType, bottomType, leftType) {
  return `M ${p1.x} ${p1.y}${getEdgePath(p1, p2, topType)}${getEdgePath(p2, p3, rightType)}${getEdgePath(p3, p4, bottomType)}${getEdgePath(p4, p1, leftType)} Z`;
}

function getEdgePath(p1, p2, type) {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  if (type === 0) return ` L ${p2.x} ${p2.y}`;
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  const px = uy;
  const py = -ux;
  const h = len * 0.18 * type;
  return ` C ${p1.x + dx * 0.35 - px * h * 0.1} ${p1.y + dy * 0.35 - py * h * 0.1}, ${p1.x + dx * 0.4 - px * h * 0.2} ${p1.y + dy * 0.4 - py * h * 0.2}, ${p1.x + dx * 0.3 + px * h} ${p1.y + dy * 0.3 + py * h}` +
    ` C ${p1.x + dx * 0.45 + px * h} ${p1.y + dy * 0.45 + py * h}, ${p1.x + dx * 0.55 + px * h} ${p1.y + dy * 0.55 + py * h}, ${p1.x + dx * 0.7 + px * h} ${p1.y + dy * 0.7 + py * h}` +
    ` C ${p1.x + dx * 0.6 - px * h * 0.2} ${p1.y + dy * 0.6 - py * h * 0.2}, ${p1.x + dx * 0.65 - px * h * 0.1} ${p1.y + dy * 0.65 - py * h * 0.1}, ${p2.x} ${p2.y}`;
}

function setupObliqueDrag() {
  els.obliqueViewer.addEventListener("mousedown", (event) => {
    isDragging = true;
    startX = event.clientX;
    initialTheta = theta;
    event.preventDefault();
  });
  window.addEventListener("mousemove", (event) => {
    if (!isDragging) return;
    theta = (initialTheta + (event.clientX - startX) * 0.8) % 360;
    drawOblique();
  });
  window.addEventListener("mouseup", () => {
    isDragging = false;
  });
  els.obliqueViewer.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 1) return;
    isDragging = true;
    startX = event.touches[0].clientX;
    initialTheta = theta;
    event.preventDefault();
  }, { passive: false });
  els.obliqueViewer.addEventListener("touchmove", (event) => {
    if (!isDragging || event.touches.length !== 1) return;
    theta = (initialTheta + (event.touches[0].clientX - startX) * 0.8) % 360;
    drawOblique();
    event.preventDefault();
  }, { passive: false });
  els.obliqueViewer.addEventListener("touchend", () => {
    isDragging = false;
  });
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
  }).format(new Date(dateString.includes("T") ? dateString : `${dateString}T00:00:00`));
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

bootstrap();
