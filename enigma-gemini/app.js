/**
 * Enigma Print — Premium Mobile Dashboard Controller
 * Target: Google Pixel 8 / Mobile Viewports
 * Based on Claude Design Mockup, May 2026.
 */

const STORAGE_KEY = "enigmaprint.projects.v2";
const HELPER_URL_KEY = "enigmaprint.helperUrl";

// Print phases for the progress modal
const PRINT_PHASES = [
  { key: "config", label: "Load printer settings", percent: 8 },
  { key: "slice", label: "Slice 3MF to G-code", percent: 28 },
  { key: "package", label: "Package printer project", percent: 50 },
  { key: "upload", label: "Upload to A1 mini", percent: 76 },
  { key: "send", label: "Send AMS-off print command", percent: 92 },
  { key: "done", label: "Printer accepted job", percent: 100 }
];

let state = {
  projects: [],
  activeProject: null,
  selectedDay: 1, // 1-indexed
  helperUrl: "http://127.0.0.1:4777",
  revealed: false
};

// 3D Oblique interactive configuration
let theta = 45; // rotation angle
let depth = 14; // extrusion thickness
let isDragging = false;
let startX = 0;
let initialTheta = 45;

// DOM Elements
const els = {
  projectSub: document.querySelector("#projectSub"),
  settingsButton: document.querySelector("#settingsButton"),
  settingsDialog: document.querySelector("#settingsDialog"),
  settingsForm: document.querySelector("#settingsForm"),
  helperUrlInput: document.querySelector("#helperUrlInput"),
  pingDot: document.querySelector("#pingDot"),
  pingStatusMsg: document.querySelector("#pingStatusMsg"),
  saveSettingsBtn: document.querySelector("#saveSettingsBtn"),
  
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

// --- BOOTSTRAP ---

async function bootstrap() {
  // Load helper URL configuration
  const savedUrl = localStorage.getItem(HELPER_URL_KEY);
  if (savedUrl) {
    state.helperUrl = savedUrl;
  } else {
    // If we're on mobile, 127.0.0.1 won't work, so try to guess from window.location if possible
    if (location.hostname && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
      // Keep localhost fallback but notify user in dialog
    }
  }
  els.helperUrlInput.value = state.helperUrl;

  // Load projects from local storage first
  state.projects = loadProjectsFromStorage();

  // Load latest manifests from projects/index.json
  await loadPublishedProjects();

  // Find active project: choose the one marked "current", or fall back to the first active/generated
  state.activeProject = state.projects.find(p => p.status === "current") || 
                        state.projects.find(p => p.status === "active") || 
                        state.projects[0] || null;

  if (state.activeProject) {
    // Default to the first unprinted day, or if all printed, default to the last day
    const nextPieceIndex = state.activeProject.pieces.findIndex(p => p.status !== "printed");
    state.selectedDay = nextPieceIndex !== -1 ? nextPieceIndex + 1 : state.activeProject.pieces.length;
  }

  attachEvents();
  updateUI();
  checkHelperConnection();
}

// --- STATE MANAGEMENT ---

function loadProjectsFromStorage() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }
  return [];
}

async function loadPublishedProjects() {
  try {
    const response = await fetch("../projects/index.json", { cache: "no-store" });
    if (!response.ok) return;
    const data = await response.json();
    if (!Array.isArray(data.projects)) return;

    const imported = data.projects.map(normalizeProjectManifest);
    
    // Merge remote manifests with local states
    const localProjects = new Map(state.projects.map(p => [p.id, p]));
    
    for (const project of imported) {
      if (localProjects.has(project.id)) {
        const local = localProjects.get(project.id);
        // Preserve printed statuses
        project.pieces.forEach((p, idx) => {
          if (local.pieces[idx] && local.pieces[idx].status === "printed") {
            p.status = "printed";
            p.printedAt = local.pieces[idx].printedAt;
          }
        });
        project.updatedAt = local.updatedAt;
      }
      localProjects.set(project.id, project);
    }
    
    state.projects = Array.from(localProjects.values());
    saveProjectsToStorage();
  } catch (err) {
    console.warn("Could not load published projects list:", err);
  }
}

function saveProjectsToStorage() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.projects));
}

function normalizeProjectManifest(manifest) {
  const slug = manifest.slug || manifest.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return {
    id: manifest.id || slug,
    name: manifest.name,
    slug,
    status: manifest.status || "generated",
    summary: manifest.summary || "Puzzle week.",
    targetPrinter: manifest.targetPrinter || "Bambu Lab A1 mini",
    createdAt: manifest.createdAt || new Date().toISOString(),
    updatedAt: manifest.updatedAt || new Date().toISOString(),
    assets: manifest.assets || {},
    files: manifest.files || [],
    pieces: manifest.pieces.map((piece, index) => ({
      id: piece.id || `${slug}-${index + 1}`,
      day: piece.day || index + 1,
      name: piece.name || `Piece ${index + 1}`,
      filename: piece.filename || `piece-${String(index + 1).padStart(2, "0")}.3mf`,
      path: piece.path || piece.url || "",
      scheduledFor: piece.scheduledFor || new Date().toISOString().slice(0, 10),
      status: piece.status || "pending",
      printedAt: piece.printedAt || null,
      note: piece.note || "Bambu-ready puzzle slab."
    }))
  };
}

// --- NETWORK HELPER LINK ---

async function checkHelperConnection() {
  updatePingStatus("pending", "Checking connection...");
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    
    const response = await fetch(`${state.helperUrl}/health`, { 
      method: "GET",
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    
    if (response.ok) {
      updatePingStatus("success", "Helper is active & connected!");
    } else {
      updatePingStatus("failed", "Helper returned error status.");
    }
  } catch (err) {
    updatePingStatus("failed", "Cannot reach helper. Check LAN IP.");
  }
}

function updatePingStatus(type, message) {
  els.pingDot.className = `status-dot ping-${type}`;
  els.pingStatusMsg.textContent = message;
}

// --- OBlique 3D VIEWER SVG DRAWING ---

/**
 * Builds a Snug fit interlocking puzzle piece curve using cubic bezier curves.
 * Creates a unique jigsaw shape clockwise starting at top-left.
 */
function getPuzzlePiecePath(p1, p2, p3, p4, topType, rightType, bottomType, leftType) {
  let path = `M ${p1.x} ${p1.y}`;
  path += getEdgePath(p1, p2, topType);
  path += getEdgePath(p2, p3, rightType);
  path += getEdgePath(p3, p4, bottomType);
  path += getEdgePath(p4, p1, leftType);
  path += " Z";
  return path;
}

function getEdgePath(p1, p2, type) {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  if (type === 0) {
    return ` L ${p2.x} ${p2.y}`;
  }
  
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  
  // Perpendicular vector pointing outwards fromclockwise path
  const px = uy;
  const py = -ux;
  
  const h = len * 0.18 * type; // Height/depth of tab (positive = out, negative = in)
  
  // Bezier control points defining a smooth puzzle bulb tab
  const c1x = p1.x + dx * 0.35 - px * (h * 0.1);
  const c1y = p1.y + dy * 0.35 - py * (h * 0.1);
  
  const n1x = p1.x + dx * 0.4 - px * (h * 0.2);
  const n1y = p1.y + dy * 0.4 - py * (h * 0.2);
  
  const b1x = p1.x + dx * 0.3 + px * h;
  const b1y = p1.y + dy * 0.3 + py * h;
  
  const m1x = p1.x + dx * 0.45 + px * h;
  const m1y = p1.y + dy * 0.45 + py * h;
  
  const m2x = p1.x + dx * 0.55 + px * h;
  const m2y = p1.y + dy * 0.55 + py * h;
  
  const b2x = p1.x + dx * 0.7 + px * h;
  const b2y = p1.y + dy * 0.7 + py * h;
  
  const n2x = p1.x + dx * 0.6 - px * (h * 0.2);
  const n2y = p1.y + dy * 0.6 - py * (h * 0.2);
  
  const c2x = p1.x + dx * 0.65 - px * (h * 0.1);
  const c2y = p1.y + dy * 0.65 - py * (h * 0.1);
  
  return ` C ${c1x} ${c1y}, ${n1x} ${n1y}, ${b1x} ${b1y}` +
         ` C ${m1x} ${m1y}, ${m2x} ${m2y}, ${b2x} ${b2y}` +
         ` C ${n2x} ${n2y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
}

// Draw the 3D Oblique piece slab
function drawOblique() {
  if (!state.activeProject) return;
  
  const piece = state.activeProject.pieces[state.selectedDay - 1];
  const isComplete = piece.status === "printed";
  const isProjectComplete = state.activeProject.pieces.every(p => p.status === "printed");
  
  // Calculate Oblique vector offsets from active drag angles
  const rad = (theta * Math.PI) / 180;
  const dxVec = depth * Math.cos(rad);
  const dyVec = depth * Math.sin(rad);
  
  // Generate deterministic tab/notch shapes depending on the day
  const d = piece.day;
  const topType = (d % 3) - 1;
  const rightType = ((d + 1) % 3) - 1;
  const bottomType = ((d + 2) % 3) - 1;
  const leftType = ((d + 3) % 3) - 1;
  
  // Set dimensions for the 2D bounding template centered inside a 200x200 canvas
  const p1 = { x: 55, y: 55 };
  const p2 = { x: 145, y: 55 };
  const p3 = { x: 145, y: 145 };
  const p4 = { x: 55, y: 145 };
  
  const path = getPuzzlePiecePath(p1, p2, p3, p4, topType, rightType, bottomType, leftType);
  
  // Dynamic color ramp mapping
  const baseTopFill = isComplete ? "#5DCAA5" : "#FAC775";
  const baseTopStroke = isComplete ? "#84e6c4" : "#ffdba3";
  
  // SVG Generation using layered extrusion (L=14 layers)
  let svgContent = `
    <svg viewBox="0 0 200 200" width="100%" height="100%" style="overflow: visible;">
      <defs>
        <!-- Shadow Blur filter -->
        <filter id="shadowBlur" x="-20%" y="-20%" width="150%" height="150%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="6" />
          <feOffset dx="${dxVec * 1.5}" dy="${dyVec * 1.5}" />
          <feComponentTransfer><feFuncA type="linear" slope="0.65"/></feComponentTransfer>
          <feMerge>
            <feMergeNode />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <clipPath id="topFaceClip">
          <path d="${path}" />
        </clipPath>
      </defs>
  `;
  
  // 1. Draw blurred projection drop-shadow
  svgContent += `
    <path d="${path}" fill="#000" filter="url(#shadowBlur)" style="opacity: 0.6; mix-blend-mode: multiply;" />
  `;
  
  // 2. Draw 3D side layers (layered extrusion with plastic gradient shading)
  const layerCount = 14;
  for (let i = layerCount; i >= 1; i--) {
    const ratio = i / layerCount;
    const tx = dxVec * ratio;
    const ty = dyVec * ratio;
    
    // Get HSL shaded plastic step
    let fill = "";
    if (isComplete) {
      fill = `hsl(161, ${69 + ratio * 10}%, ${24 - ratio * 15}%)`;
    } else {
      fill = `hsl(36, ${86 + ratio * 10}%, ${34 - ratio * 20}%)`;
    }
    
    svgContent += `
      <g transform="translate(${tx}, ${ty})">
        <path d="${path}" fill="${fill}" stroke="${fill}" stroke-width="1" />
      </g>
    `;
  }
  
  // 3. Draw top face plate at (0, 0)
  svgContent += `
    <g transform="translate(0, 0)">
      <!-- Top surface base color -->
      <path d="${path}" fill="${baseTopFill}" stroke="${baseTopStroke}" stroke-width="1.2" class="viewer-3d-piece-top" />
      
      <!-- Tactile bas-relief rings inside the clip path -->
      <g clip-path="url(#topFaceClip)">
        <circle cx="100" cy="100" r="18" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="36" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="54" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="72" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="1.5" />
        <circle cx="100" cy="100" r="90" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="1" />
        <line x1="55" y1="100" x2="145" y2="100" stroke="rgba(255,255,255,0.15)" stroke-width="1" />
        <line x1="100" y1="55" x2="100" y2="145" stroke="rgba(255,255,255,0.15)" stroke-width="1" />
      </g>
    </g>
  `;
  
  // 4. Print celebration confetti overlay if the whole week is complete!
  if (isProjectComplete) {
    const confettiColors = ["#EF9F27", "#FAC775", "#D85A30", "#1D9E75", "#5DCAA5", "#E1F5EE"];
    for (let i = 0; i < 15; i++) {
      const cx = 30 + Math.sin(i * 3) * 60 + 70;
      const cy = 20 + Math.cos(i * 1.7) * 60 + 70;
      const r = 2.5 + (i % 3);
      const fill = confettiColors[i % confettiColors.length];
      const rot = i * 25;
      svgContent += `
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" style="opacity: 0.85; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.35));" transform="rotate(${rot} ${cx} ${cy})" />
      `;
    }
  }
  
  svgContent += `</svg>`;
  els.obliqueViewer.innerHTML = svgContent;
  
  // Set badge layout status
  els.completionBadge.textContent = isProjectComplete 
    ? `${state.activeProject.pieces.length}/${state.activeProject.pieces.length} Complete`
    : `Day ${piece.day}`;
  
  if (isComplete) {
    els.completionBadge.classList.add("complete");
  } else {
    els.completionBadge.classList.remove("complete");
  }
}

// --- INTERACTIVE DRAG TO ROTATE ACTION ---

function setupObliqueDrag() {
  els.obliqueViewer.addEventListener("mousedown", (e) => {
    isDragging = true;
    startX = e.clientX;
    initialTheta = theta;
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const deltaX = e.clientX - startX;
    theta = (initialTheta + deltaX * 0.8) % 360;
    drawOblique();
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  // Touch Support for phone browsers (Pixel 8 optimization)
  els.obliqueViewer.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) return;
    isDragging = true;
    startX = e.touches[0].clientX;
    initialTheta = theta;
    e.preventDefault();
  }, { passive: false });

  els.obliqueViewer.addEventListener("touchmove", (e) => {
    if (!isDragging || e.touches.length !== 1) return;
    const deltaX = e.touches[0].clientX - startX;
    theta = (initialTheta + deltaX * 0.8) % 360;
    drawOblique();
    e.preventDefault();
  }, { passive: false });

  els.obliqueViewer.addEventListener("touchend", () => {
    isDragging = false;
  });
}

// --- INTERLOCKING JIGSAW BOARD GENERATOR ---

function drawJigsaw() {
  if (!state.activeProject) return;
  const pieces = state.activeProject.pieces;
  const count = pieces.length;
  const imageSource = state.activeProject.assets?.sourceHidden || 
                      state.activeProject.assets?.preview || 
                      "../" + (state.activeProject.assets?.preview || "");

  els.jigsawPiecesGroup.innerHTML = "";
  
  // Generate the pieces' layout and coordinate system dynamically
  // Supports N = 4 pieces (2x2 grid) or N = 7 pieces (3+3+1 grid)
  const grid = [];
  const width = 140;
  const height = 84;
  
  if (count === 4) {
    // 2x2 Snug Grid
    const w = 70;
    const h = 42;
    
    // Define the grid vertices for clean overlap matching
    const v = [
      [{x: 0, y: 0},  {x: 70, y: 0},  {x: 140, y: 0}],
      [{x: 0, y: 42}, {x: 70, y: 42}, {x: 140, y: 42}],
      [{x: 0, y: 84}, {x: 70, y: 84}, {x: 140, y: 84}]
    ];
    
    // Boundary tab specifications: 1 points out, -1 points in, 0 flat
    // [top, right, bottom, left]
    grid.push({
      p: [v[0][0], v[0][1], v[1][1], v[1][0]], // Piece 1
      t: [0, 1, -1, 0], center: {x: 35, y: 21}
    });
    grid.push({
      p: [v[0][1], v[0][2], v[1][2], v[1][1]], // Piece 2
      t: [0, 0, 1, -1], center: {x: 105, y: 21}
    });
    grid.push({
      p: [v[1][0], v[1][1], v[2][1], v[2][0]], // Piece 3
      t: [1, -1, 0, 0], center: {x: 35, y: 63}
    });
    grid.push({
      p: [v[1][1], v[1][2], v[2][2], v[2][1]], // Piece 4
      t: [-1, 0, 0, 1], center: {x: 105, y: 63}
    });
  } else {
    // Default: 7-Piece layout (3+3+1 grid layout)
    // Row heights: 28, 28, 28 = 84
    // Vertices coordinates
    const v = {
      r0: [{x: 0, y: 0},   {x: 46.6, y: 0},  {x: 93.3, y: 0},  {x: 140, y: 0}],
      r1: [{x: 0, y: 28},  {x: 46.6, y: 28}, {x: 93.3, y: 28}, {x: 140, y: 28}],
      r2: [{x: 0, y: 56},  {x: 46.6, y: 56}, {x: 93.3, y: 56}, {x: 140, y: 56}],
      r3: [{x: 0, y: 84},  {x: 35, y: 84},   {x: 105, y: 84},  {x: 140, y: 84}]
    };
    
    // Piece definitions with custom vertices to shape a snug bottom keystone
    // Piece 1: R1-C1
    grid.push({
      p: [v.r0[0], v.r0[1], v.r1[1], v.r1[0]],
      t: [0, 1, -1, 0], center: {x: 23.3, y: 14}
    });
    // Piece 2: R1-C2
    grid.push({
      p: [v.r0[1], v.r0[2], v.r1[2], v.r1[1]],
      t: [0, 1, -1, -1], center: {x: 70, y: 14}
    });
    // Piece 3: R1-C3
    grid.push({
      p: [v.r0[2], v.r0[3], v.r1[3], v.r1[2]],
      t: [0, 0, -1, -1], center: {x: 116.6, y: 14}
    });
    // Piece 4: R2-C1 + wings down left
    grid.push({
      p: [v.r1[0], v.r1[1], v.r2[1], {x: 35, y: 56}, v.r3[1], v.r3[0]],
      t: [1, -1, 0, -1, 0, 0], center: {x: 21, y: 48}
    });
    // Piece 5: R2-C2
    grid.push({
      p: [v.r1[1], v.r1[2], v.r2[2], v.r2[1]],
      t: [1, 1, -1, 1], center: {x: 70, y: 42}
    });
    // Piece 6: R2-C3 + wings down right
    grid.push({
      p: [v.r1[2], v.r1[3], v.r3[3], v.r3[2], {x: 105, y: 56}, v.r2[2]],
      t: [1, 0, 0, 1, 0, -1], center: {x: 119, y: 48}
    });
    // Piece 7 (Keystone Center Bottom):
    grid.push({
      p: [{x: 35, y: 56}, {x: 105, y: 56}, v.r3[2], v.r3[1]],
      t: [1, -1, 0, 1], center: {x: 70, y: 70}
    });
  }

  // Draw each segment and create clipped images
  let svgOut = "";
  let defsOut = "";

  grid.forEach((item, index) => {
    const p = pieces[index];
    const isPrinted = p && p.status === "printed";
    const isToday = p && p.status !== "printed" && index === (state.selectedDay - 1);
    
    // Construct clockwise jigsaw outline
    let dStr = `M ${item.p[0].x} ${item.p[0].y}`;
    for (let i = 0; i < item.p.length; i++) {
      const nextIdx = (i + 1) % item.p.length;
      const type = item.t[i] || 0;
      dStr += getEdgePath(item.p[i], item.p[nextIdx], type);
    }
    dStr += " Z";

    // Set up unique clip-paths for each piece
    const clipId = `jigsaw-clip-${index}`;
    defsOut += `
      <clipPath id="${clipId}">
        <path d="${dStr}" />
      </clipPath>
    `;

    // Visual styling rules for different states
    let pathClass = "";
    let textClass = "";
    let textFill = "";
    
    if (isPrinted) {
      pathClass = "jigsaw-piece-unrevealed";
      textClass = "jigsaw-piece-unrevealed-text";
    } else if (isToday) {
      pathClass = "jigsaw-piece-keystone";
      textClass = "jigsaw-piece-keystone-text";
    } else {
      pathClass = "jigsaw-piece-path"; // pending/default
    }

    if (state.revealed) {
      // 1. Reveal State: flood each piece with dynamic clipped AI hidden image
      svgOut += `
        <image href="${imageSource}" x="0" y="0" width="${width}" height="${height}" clip-path="url(#${clipId})" class="jigsaw-piece-path jigsaw-piece-revealed" preserveAspectRatio="none" />
        <path d="${dStr}" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="0.55" class="jigsaw-piece-path jigsaw-piece-revealed" />
        <text x="${item.center.x}" y="${item.center.y}" class="jigsaw-piece-text jigsaw-piece-revealed-text">${index + 1}</text>
      `;
    } else {
      // 2. Unrevealed State: display vector solids representing today/printed states
      let fillAttr = "";
      let strokeAttr = "";
      let strokeWidth = "";
      
      if (isPrinted) {
        fillAttr = "var(--teal-400)";
        strokeAttr = "rgba(255, 255, 255, 0.15)";
        strokeWidth = "0.6";
        textFill = "#ffffff";
      } else if (isToday) {
        fillAttr = "rgba(239, 159, 39, 0.22)";
        strokeAttr = "var(--amber-400)";
        strokeWidth = "0.85";
        textFill = "var(--amber-100)";
      } else {
        fillAttr = "#1a221d";
        strokeAttr = "rgba(255,255,255,0.04)";
        strokeWidth = "0.5";
        textFill = "var(--ink-muted)";
      }

      svgOut += `
        <path d="${dStr}" fill="${fillAttr}" stroke="${strokeAttr}" stroke-width="${strokeWidth}" class="${pathClass}" />
        <text x="${item.center.x}" y="${item.center.y}" fill="${textFill}" class="jigsaw-piece-text ${textClass}">${index + 1}</text>
      `;
    }
  });

  // Inject defs and path nodes to SVG
  const defsContainer = els.jigsawBoard.querySelector("defs");
  if (defsContainer) {
    defsContainer.innerHTML = `<clipPath id="revealClip"><rect x="0" y="0" width="140" height="84" rx="4" /></clipPath>` + defsOut;
  }
  els.jigsawPiecesGroup.innerHTML = svgOut;
}

// --- DYNAMIC DASHBOARD DATA UPDATER ---

function updateUI() {
  if (!state.activeProject) return;

  const project = state.activeProject;
  const piece = project.pieces[state.selectedDay - 1];
  const isComplete = piece.status === "printed";
  const isProjectComplete = project.pieces.every(p => p.status === "printed");

  // Header and title info
  els.projectSub.textContent = `Bambu Lab A1 mini · Week ${project.name}`;
  els.pieceDayLabel.textContent = `DAY ${piece.day} OF ${project.pieces.length}`;
  els.pieceNameLabel.textContent = piece.name;

  // Print statistics mapping
  els.statTime.textContent = isComplete ? "24m" : "28m";
  els.statFilament.textContent = isComplete ? "12g" : "14g";
  els.statStatus.textContent = piece.status.toUpperCase();
  if (isComplete) {
    els.statStatus.style.color = "var(--teal-200)";
  } else {
    els.statStatus.style.color = "var(--amber-400)";
  }

  // Draw Oblique 3D puzzle block
  drawOblique();

  // Progress dot timeline indicators
  els.progressStrip.innerHTML = project.pieces.map((p, idx) => {
    let dotClass = "strip-dot";
    if (idx === state.selectedDay - 1) {
      dotClass += " active";
    } else if (p.status === "printed") {
      dotClass += " complete";
    } else {
      dotClass += " pending";
    }
    return `<button class="${dotClass}" data-day="${idx + 1}" type="button" aria-label="Go to day ${idx + 1}"></button>`;
  }).join("");

  // Action CTA controls
  if (isProjectComplete) {
    // Screen 3: Confetti week complete celebration
    els.printCta.hidden = false;
    els.printCta.className = "amber-btn";
    els.printCta.innerHTML = `<span class="btn-icon">🧩</span> Piece it together →`;
    els.printedChip.hidden = true;
  } else if (isComplete) {
    // Screen 2: Already printed past record
    els.printCta.hidden = true;
    els.printedChip.hidden = false;
    if (piece.printedAt) {
      const dt = new Date(piece.printedAt);
      els.printedTimeLabel.textContent = dt.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    } else {
      els.printedTimeLabel.textContent = "Complete";
    }
  } else {
    // Screen 1: Queued active slice
    els.printCta.hidden = false;
    els.printCta.className = "coral-btn";
    els.printCta.innerHTML = `<span class="btn-icon">⚡</span> Send to A1 mini`;
    els.printedChip.hidden = true;
  }

  // Draw updated Jigsaw outline board
  drawJigsaw();
}

// --- NETWORK PRINTER COMMANDS (LAN FTPS / MQTT BRIDGE) ---

async function triggerPrintJob() {
  if (!state.activeProject) return;
  const project = state.activeProject;
  const piece = project.pieces[state.selectedDay - 1];

  const confirmed = window.confirm(`Ready to headlessly slice ${piece.filename} and send to A1 mini over LAN?`);
  if (!confirmed) return;

  // Open the print progress modal
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
      throw new Error(result.message || "Print bridge command failed.");
    }

    // Success! Update local manifest to printed state
    piece.status = "printed";
    piece.printedAt = new Date().toISOString();
    saveProjectsToStorage();
    
    finishProgressModal(true, `Sent ${piece.filename} successfully!\nYour A1 mini is currently pre-heating and beginning LAN bed-leveling.`);
    updateUI();
  } catch (err) {
    finishProgressModal(false, `Print request failed: ${err.message}`);
  }
}

// --- PROGRESS DIALOG VIEWER CONTROL ---

let progressTimer = null;

function startProgressModal(piece) {
  els.progressTitle.textContent = piece.filename;
  els.progressMessage.textContent = "Starting headless slicing. Bambu Studio may take up to 30s...";
  els.progressCloseButton.hidden = true;
  els.progressPercent.textContent = "0%";
  els.progressFill.style.width = "0%";
  
  renderStepsList(0, "running");
  els.printProgressDialog.showModal();

  let phaseIndex = 0;
  progressTimer = setInterval(() => {
    if (phaseIndex < PRINT_PHASES.length - 2) {
      phaseIndex++;
      const phase = PRINT_PHASES[phaseIndex];
      els.progressPercent.textContent = `${phase.percent}%`;
      els.progressFill.style.width = `${phase.percent}%`;
      renderStepsList(phaseIndex, "running");
      els.progressMessage.textContent = getProgressMsg(phaseIndex);
    }
  }, 6000);
}

function finishProgressModal(ok, message) {
  if (progressTimer) clearInterval(progressTimer);
  
  const finalIdx = ok ? PRINT_PHASES.length - 1 : 2; // stop early if error
  const finalPercent = PRINT_PHASES[finalIdx].percent;
  
  els.progressPercent.textContent = `${finalPercent}%`;
  els.progressFill.style.width = `${finalPercent}%`;
  renderStepsList(finalIdx, ok ? "done" : "error");
  
  els.progressMessage.textContent = message;
  els.progressCloseButton.hidden = false;
}

function renderStepsList(activeIndex, status) {
  els.progressSteps.innerHTML = PRINT_PHASES.map((item, index) => {
    let stateClass = "pending";
    if (index < activeIndex || status === "done") {
      stateClass = "done";
    } else if (index === activeIndex) {
      stateClass = status;
    }
    return `<li class="${stateClass}"><span></span>${item.label}</li>`;
  }).join("");
}

function getProgressMsg(index) {
  return [
    "Reading printer config and checking LAN connectivity.",
    "Executing Bambu Studio CLI headless slice.",
    "Packaging G-code into reference model 3MF container.",
    "Uploading print package to SD card over FTPS...",
    "Commanding printer head to kick off calibration via MQTT."
  ][index] || "Processing printer signals...";
}

// --- EVENT HANDLERS ---

function attachEvents() {
  // Settings Trigger
  els.settingsButton.addEventListener("click", () => {
    els.settingsDialog.showModal();
    checkHelperConnection();
  });

  // Settings Save Form
  els.settingsForm.addEventListener("submit", (e) => {
    if (e.submitter?.value === "cancel") return;
    e.preventDefault();
    state.helperUrl = els.helperUrlInput.value.trim().replace(/\/$/, "");
    localStorage.setItem(HELPER_URL_KEY, state.helperUrl);
    els.settingsDialog.close();
    checkHelperConnection();
  });

  // Navigation dots navigation
  els.progressStrip.addEventListener("click", (e) => {
    const dot = e.target.closest(".strip-dot");
    if (!dot) return;
    state.selectedDay = parseInt(dot.dataset.day, 10);
    updateUI();
  });

  // Oblique arrow navigation
  els.prevDayButton.addEventListener("click", () => {
    if (state.selectedDay > 1) {
      state.selectedDay--;
      updateUI();
    }
  });

  els.nextDayButton.addEventListener("click", () => {
    if (state.selectedDay < state.activeProject.pieces.length) {
      state.selectedDay++;
      updateUI();
    }
  });

  // Main action CTA
  els.printCta.addEventListener("click", () => {
    const isProjectComplete = state.activeProject.pieces.every(p => p.status === "printed");
    if (isProjectComplete) {
      // Transition to Screen 4 (Assembly Section)
      els.focusSection.hidden = true;
      els.assemblySection.hidden = false;
      state.revealed = false;
      els.revealLockBox.hidden = false;
      els.revealChip.hidden = true;
      drawJigsaw();
    } else {
      // Trigger slice & print job
      triggerPrintJob();
    }
  });

  // Assembly guide controls
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

  els.progressCloseButton.addEventListener("click", () => {
    els.printProgressDialog.close();
  });

  // Setup Oblique 3D rotation dragging mouse/touch event streams
  setupObliqueDrag();
}

// Run bootstrap
bootstrap();
