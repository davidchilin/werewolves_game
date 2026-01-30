// Version 4.9.6
const PHASE_LOBBY = "Lobby";
const PHASE_NIGHT = "Night";
const PHASE_ACCUSATION = "Accusation";
const PHASE_LYNCH = "Lynch_Vote";
const PHASE_GAME_OVER = "Game_Over";

const socket = io();

let translations = {};
let currentLang = window.userLang || "en";

// 1. Load the appropriate JSON file
async function loadTranslations() {
  try {
    const response = await fetch(`/static/${currentLang}.json`);
    translations = await response.json();
    console.log(`Loaded translations for ${currentLang}`);

    // [ADDED] Trigger UI update immediately after loading
    updateStaticUIText();

    if (myRole) {
      updateRoleTooltip(myRole);
      const displayRole = myRole === "Random_Seer" ? "Seer" : myRole;
      const roleName = t({ key: `roles.${displayRole}.name` }) || displayRole;
      els.role.textContent = roleName + (isAdmin ? " 👑" : "");
    }
    if (currentPhase) updatePhaseDisplay(currentPhase);
    if (publicHistory && publicHistory.length > 0) {
      resetLog(publicHistory);
    }
  } catch (err) {
    console.error("Failed to load translations:", err);
  }
}
loadTranslations();

function t(data) {
  // If it's already a string, return it (backward compatibility)
  if (typeof data === "string") return data;
  if (!data || !data.key) return "Error: Unknown message";

  // Traverse JSON keys (e.g., "events.night_kill")
  const keys = data.key.split(".");
  let template = translations;
  for (let k of keys) {
    template = template ? template[k] : null;
  }
  if (!template || typeof template !== "string") return data.key;

  // Replace Variables
  let text = template;
  if (data.variables) {
    for (const [varName, varValue] of Object.entries(data.variables)) {
      let insertVal = varValue;

      // 1. Role Name Check (Existing)
      if (
        translations.roles &&
        translations.roles[varValue] &&
        translations.roles[varValue].name
      ) {
        insertVal = translations.roles[varValue].name;
      }

      // 2. [ADDED] Recursive Translation Check
      // If the variable looks like a key (e.g. "prompts.villager_0"), try to translate it
      else if (typeof insertVal === "string" && insertVal.includes(".")) {
        const translated = t({ key: insertVal });
        // If translation found (result != key), use it
        if (translated !== insertVal) {
          insertVal = translated;
        }
      }

      text = text.replace(`{${varName}}`, insertVal);
    }
  }
  return text;
}

function updateStaticUIText() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const text = t({ key: key });

    if (text && text !== key) {
      // Preserve icons if they exist (optional complexity),
      // simple innerText replacement is usually safest for buttons
      el.innerText = text;
    }
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    const text = t({ key: key });
    if (text && text !== key) {
      el.placeholder = text;
    }
  });

  // [ADDED] Manual Placeholder Updates (since placeholders aren't innerText)
  if (translations.ui && translations.ui.lobby) {
    const chatInput = document.getElementById("game-chat-input");
    if (chatInput)
      chatInput.placeholder = translations.ui.lobby.chat_placeholder;
  }
}

// Global State
let ROLE_DATA = {};
let myRole;
let publicHistory = [],
  isAlive = false;
let livingPlayers = [],
  allPlayers = [],
  isAdmin = false;
let ghostModeActive = false;
let timerInterval,
  timersDisabled = false;
let currentNightUI = null;

// Phase State
let isPnP = false;
let currentPhase = "";
let hasActed = new Set(),
  myPhaseTargetId = null,
  myNightMetadata = null,
  lastSeerResult = null,
  myLynchVote = null,
  currentLynchTargetName = "Unknown",
  mySleepVote = false;
let totalAccusationDuration = 90,
  sleepButtonTimeout = null;

fetch("/get_roles")
  .then((response) => response.json())
  .then((roles) => {
    roles.forEach((r) => {
      const key = r.name_key.replace(/_/g, " ");
      ROLE_DATA[key] = {
        short: r.short,
        long: r.long,
        rating: r.rating,
        color: r.color,
        team: r.team,
      };
    });
    // Refresh my tooltip if role is already set
    if (typeof myRole !== "undefined" && myRole) {
      updateRoleTooltip(myRole);
    }
  })
  .catch((err) => console.error("Error fetching role data:", err));
// --- DOM Elements ---
const els = {
  phase: document.getElementById("phase-display"),
  timer: document.getElementById("timer-display"),
  action: document.getElementById("action-area"),
  log: document.getElementById("log-panel"),
  role: document.getElementById("my-role"),
  playerList: document.getElementById("player-list"),
  sidePanel: document.getElementById("side-panel"),
  adminControls: document.getElementById("admin-controls-ingame"),
  gameChatTitle: document.getElementById("chat-title"),
  gameChatSendBtn: document.getElementById("game-chat-send-btn"),
  gameChatInput: document.getElementById("game-chat-input"),
  gameChatContainer: document.getElementById("game-chat-container"),
  gameOverScreen: document.getElementById("game-over-screen"),
  gameOverChatSendBtn: document.getElementById("game-over-chat-send-btn"),
  gameOverChatInput: document.getElementById("game-over-chat-input"),
  adminChatToggle: document.getElementById("admin-chat-toggle-btn"),
  // PnP
  pnpHub: document.getElementById("pnp-hub"),
  pnpGrid: document.getElementById("pnp-grid"),
  pnpOverlay: document.getElementById("pnp-overlay"),
  pnpReturnBtn: document.getElementById("pnp-return-btn"),
  gameContainer: document.querySelector(".game-container"),
};

// --- Helper Functions ---
function logMessage(message, isPrivate = false) {
  let text = t(message);

  let div = document.createElement("div");
  div.innerHTML = DOMPurify.sanitize(text);
  if (isPrivate) {
    div.classList.add("private-msg");
  }
  els.log.prepend(div);
}

function resetLog(history) {
  if (isPnP && els.log.children.length > 0) {
    els.log.innerHTML = "";
  }
  // Clear existing logs (including private ones from previous player)
  if (history && Array.isArray(history)) {
    history.forEach((msg) => logMessage(msg, false));
  }
  els.log.scrollTop = els.log.scrollHeight;
}

function updateAdminControls() {
  if (isAdmin && !isPnP) {
    els.adminControls.style.display = "block";
    const pauseBtn = document.getElementById("admin-pause-timer-btn");
    if (pauseBtn) {
      const resumeText =
        t({ key: "ui.game.resume_timers_btn" }) || "Resume Timers ▶️";
      const pauseText =
        t({ key: "ui.game.pause_timers_btn" }) || "Pause Timers ⏸️";
      pauseBtn.textContent = timersDisabled ? resumeText : pauseText;
      pauseBtn.style.backgroundColor = timersDisabled ? "orangered" : "";
    }
  } else {
    els.adminControls.style.display = "none";
  }
}

function setChatMode(isAdminOnly, phase) {
  // Force hide in PnP
  if (isPnP) {
    if (els.gameChatContainer)
      els.gameChatContainer.classList.add("pnp-hidden");
    return;
  } else {
    if (els.gameChatContainer)
      els.gameChatContainer.classList.remove("pnp-hidden");
  }

  let isChatDisabled = isAdminOnly && !isAdmin;
  let placeholder = "Chat is restricted.";

  if (phase === PHASE_NIGHT && !isAdmin) {
    placeholder = "sleepy quiet time...zzz";
    isChatDisabled = true;
  } else if (!isChatDisabled) {
    els.gameChatTitle.textContent = !isAlive ? "Ghost Chat 👻" : "Living Chat";
    placeholder = !isAlive
      ? "Whisper to the other side..."
      : "Type a message...";
  }

  [els.gameChatSendBtn, els.gameOverChatSendBtn].forEach(
    (btn) => (btn.disabled = isChatDisabled),
  );
  [els.gameChatInput, els.gameOverChatInput].forEach(
    (inp) => (inp.placeholder = placeholder),
  );

  els.adminChatToggle.classList.toggle("btn-active", isAdminOnly);
}

// --- Pass-and-Play (PnP) Logic ---
function doForcePhase() {
  console.log("[PnP] Forcing Next Phase via Admin command...");
  // Fallback: send simple empty payload, but we could add metadata if needed
  socket.emit("admin_next_phase", { is_pnp: true });
  closeOverlay();
}

function confirmAdvancePhase() {
  const overlay = els.pnpOverlay;
  const title = document.getElementById("overlay-title");
  const msg = document.getElementById("overlay-msg");
  const actions = document.getElementById("overlay-actions");
  const actionArea = document.getElementById("overlay-action-area");

  if (actionArea) actionArea.innerHTML = "";

  overlay.style.display = "flex";

  // [CHANGED] Use Translation Keys
  title.innerText = t({ key: "ui.pnp.force_title" });
  title.style.color = "orange";
  msg.innerHTML = t({ key: "ui.pnp.force_msg" });

  const btnYes = t({ key: "ui.pnp.force_yes" });
  const btnCancel = t({ key: "ui.pnp.btn_cancel" });

  actions.innerHTML = `
      <button class="big-btn" style="background-color: crimson;" onclick="doForcePhase()">
          ${btnYes}
      </button>
      <button class="big-btn cancel" style="background-color: royalblue" onclick="closeOverlay()">
          ${btnCancel}
      </button>
  `;
}

function requestGameSync() {
  els.gameContainer.style.display = "none";
  socket.emit("client_ready_for_game");
}

function renderHub(allPlayers, phase) {
  // Show Hub, Hide Game
  els.pnpHub.style.display = "flex";
  els.gameContainer.style.display = "none";
  els.pnpOverlay.style.display = "none";

  const pnpLogContainer = document.getElementById("pnp-log-container");
  if (els.log && pnpLogContainer) {
    resetLog(publicHistory);
    pnpLogContainer.appendChild(els.log);
  }

  let phaseKey = "ui.game.night_phase_title";
  if (phase === PHASE_ACCUSATION) phaseKey = "ui.pnp.hub_day";
  if (phase === PHASE_LYNCH) phaseKey = "ui.pnp.hub_vote";

  const titleEl = document.querySelector("#pnp-hub h2");
  if (titleEl) {
    // [CHANGED] Set text once. Do not append icons manually afterwards.
    titleEl.textContent = t({ key: phaseKey }) || phase;

    // Set Colors/Glow
    if (phase === "Night") {
      titleEl.style.color = "lightskyblue";
      titleEl.style.textShadow =
        "0 0 5px #00bcd4, 0 0 10px #00bcd4, 0 0 20px #00bcd4, 0 0 40px #00bcd4";
    } else if (phase === "Accusation") {
      titleEl.style.color = "white";
      titleEl.style.textShadow =
        "0 0 5px #ffb74d, 0 0 10px #ff9800, 0 0 20px #ff9800, 0 0 40px #ff9800";
    } else if (phase === "Lynch_Vote") {
      titleEl.style.color = "white";
      titleEl.style.textShadow =
        "0 0 5px #ff5252, 0 0 10px #ff1744, 0 0 20px #d50000, 0 0 40px #b71c1c";
    } else {
      titleEl.style.color = "darkviolet";
      titleEl.style.textShadow = "none";
    }
  }

  els.pnpGrid.innerHTML = allPlayers
    .map((p) => {
      const isDay = phase === PHASE_ACCUSATION || phase === PHASE_LYNCH;
      const isGhostActive = !p.is_alive && ghostModeActive && isDay;

      // Button clickable if not acted and alive, or ghost
      const isInteractive =
        !hasActed.has(p.id) && (p.is_alive || isGhostActive);
      let deadClass = "pnp-btn";
      if (!isInteractive) deadClass += " dead";

      const safeName = p.name.replace(/'/g, "\\'");
      const clickAction = isInteractive
        ? `startConfirmFlow('${p.id}', '${safeName}', '${p.language || "en"}')`
        : "";

      let label = p.name;
      if (!p.is_alive) label += " 👻";
      if (hasActed.has(p.id)) {
        // [CHANGED] Use translation for "(Done)"
        const doneText = t({ key: "ui.pnp.done_title" }) || "Done";
        label += ` (${doneText})`;
      }

      return `<div class="${deadClass}" onclick="${clickAction}">${label}</div>`;
    })
    .join("");
}

function closeOverlay() {
  els.pnpOverlay.style.display = "none";
}

function startConfirmFlow(pid, name, targetLang) {
  if (targetLang && targetLang !== currentLang) {
    console.log(`[PnP] Switching language to ${targetLang} for ${name}`);
    currentLang = targetLang;

    // Reload translations, THEN show the popup
    loadTranslations().then(() => {
      startConfirmFlow(pid, name, targetLang);
    });
    return;
  }
  const overlay = els.pnpOverlay;
  const title = document.getElementById("overlay-title");
  const msg = document.getElementById("overlay-msg");
  const actions = document.getElementById("overlay-actions");
  const actionArea = document.getElementById("overlay-action-area");

  if (actionArea) actionArea.innerHTML = "";

  overlay.style.display = "flex";

  // [CHANGED] Pass object {key: ...} instead of string
  title.innerText = t({ key: "ui.pnp.identity_title" });
  title.style.color = "#bb86fc";

  // [CHANGED] Pass variables object
  let msgText = t({
    key: "ui.pnp.identity_ask",
    variables: { name: name },
  });
  msg.innerHTML = msgText;

  let btnYes = t({
    key: "ui.pnp.btn_yes",
    variables: { name: name },
  });
  let btnNo = t({ key: "ui.pnp.btn_no" });

  // Escape name for the onclick handler to prevent syntax errors with quotes
  const safeName = name.replace(/'/g, "\\'");

  actions.innerHTML = `
      <button class="big-btn" onclick="confirmLevel2('${pid}', '${safeName}')">${btnYes}</button>
      <button class="big-btn cancel" onclick="closeOverlay()">${btnNo}</button>
  `;
}

function confirmLevel2(pid, name) {
  const title = document.getElementById("overlay-title");
  const msg = document.getElementById("overlay-msg");
  const actions = document.getElementById("overlay-actions");

  // [CHANGED] Correct translation calls
  title.innerText = t({ key: "ui.pnp.confirm_title" });
  title.style.color = "#f44336";

  let msgText = t({
    key: "ui.pnp.confirm_msg",
    variables: { name: name },
  });
  msg.innerHTML = msgText;

  let btnReady = t({ key: "ui.pnp.btn_ready" });
  let btnCancel = t({ key: "ui.pnp.btn_cancel" });

  actions.innerHTML = `
      <button class="big-btn" onclick="socket.emit('pnp_request_state', { player_id: '${pid}' })">${btnReady}</button>
      <button class="big-btn cancel" onclick="closeOverlay()">${btnCancel}</button>
  `;
}

socket.on("pnp_state_sync", (data) => {
  // 1. Hide Hub & Overlay
  if (data.language && data.language !== currentLang) {
    console.log(
      `[PnP] Switching language from ${currentLang} to ${data.language}`,
    );
    currentLang = data.language; // Update global variable

    // Reload translations and RE-RUN this sync handler once loaded
    loadTranslations().then(() => {
      // Recursively call this handler to render UI with new text
      socket.emit("pnp_request_state", { player_id: data.this_player_id });
    });
    return; // Stop execution here; wait for reload
  }

  const btnMain = document.getElementById("overlay-btn-main");
  if (btnMain) {
    btnMain.disabled = false;
    btnMain.innerText = "Confirm";
  }

  els.pnpHub.style.display = "none";
  els.pnpOverlay.style.display = "none";

  // 2. Show Standard Game Container
  els.gameContainer.style.display = "flex";
  const mainPanel = document.querySelector(".main-panel");
  if (els.log && mainPanel) {
    resetLog(data.message_history);
    mainPanel.appendChild(els.log);
  }
  // 3. Inject PnP specific "Back" button
  els.pnpReturnBtn.classList.remove("pnp-hidden");

  // 4. Update Variables with Specific Player Data
  myPlayerId = data.this_player_id;
  allPlayers = data.all_players;
  livingPlayers = data.living_players;
  currentNightUI = data.night_ui;
  myPhaseTargetId = data.my_phase_target_id;
  myNightMetadata = data.my_phase_metadata || {};
  myRole = data.your_role;
  isAlive = data.is_alive;
  isAdmin = data.is_admin;

  myLynchVote = data.my_lynch_vote;
  mySleepVote = data.my_sleep_vote;

  // 5. Update UI Components
  // Role Display
  const displayRole = myRole === "Random_Seer" ? "Seer" : myRole;

  const roleName =
    t({ key: `roles.${displayRole}.name` }) || displayRole.replace(/_/g, " ");
  els.role.textContent = roleName + (isAdmin ? " 👑" : "");
  if (typeof updateRoleTooltip === "function") updateRoleTooltip(myRole);

  // Action Area (Night UI)
  renderActionUI(data.phase, data.duration);

  // Player List
  updatePlayerListView(data.accusation_counts || {});

  // Hide Chat / Admin controls
  if (els.gameChatContainer) els.gameChatContainer.classList.add("pnp-hidden");
  if (els.adminControls) els.adminControls.style.display = "none";
});

// --- Standard UI Logic ---
function updateRoleTooltip(roleStr) {
  if (typeof ROLE_DATA === "undefined") return;
  if (roleStr === "Random_Seer" || roleStr === "Random Seer") {
    roleStr = "Seer";
  }

  const roleKey = roleStr.replace(/_/g, " ");
  const rData = ROLE_DATA[roleKey] || {
    long: "...",
    rating: "?",
    color: "#fff",
    team: "Neutral",
  };

  // 1. Logic uses the RAW key (e.g. "Villagers") so it works in any language
  const rawTeam = rData.team || "Neutral";
  let teamColor = "darkgray";
  let prefix = "";

  if (rawTeam === "Werewolves") {
    teamColor = "red";
    prefix = "🐺 ";
  } else if (rawTeam === "Villagers") {
    teamColor = "mediumblue";
    prefix = "🌻 ";
  } else if (
    rawTeam === "Monster" ||
    rawTeam === "Neutral" ||
    rawTeam === "Serial_Killer"
  ) {
    teamColor = "darkviolet"; // Purple
    prefix = "🎭 ";
  }

  // 2. Translate the Team Name for Display
  let displayTeamName = rawTeam;
  if (translations.teams && translations.teams[rawTeam]) {
    displayTeamName = translations.teams[rawTeam];
  }

  // Combine Prefix + Translated Name
  const finalTeamString = prefix + displayTeamName;

  // 3. Translate Role Name & Description
  const safeKey = roleKey.replace(/ /g, "_");
  const translatedDesc = t({ key: `roles.${safeKey}.long` }) || rData.long;
  const translatedName = t({ key: `roles.${safeKey}.name` }) || roleKey;

  const tooltipEl = document.getElementById("my-role-tooltip");
  if (tooltipEl) {
    tooltipEl.innerHTML = `
        <strong style="color: ${rData.color || "yellow"}; font-size: 1.2em; display:block; margin-bottom:8px;">
            ${translatedName}
        </strong>
        <div style="text-align: left; margin-bottom: 8px; line-height: 1.4;">
            ${translatedDesc}
        </div>
        <div style="font-size:0.85em; border-top:1px solid #444; padding-top:5px;">
            <strong style="color: ${rData.color}; float: left">${rData.rating}</strong>
            <span style="float: right; color: ${teamColor};">${finalTeamString}</span>
        </div> `;
  }
}

// --- Standard UI Logic ---
function submitLynchVote(vote) {
  // Check if PnP active
  let payload = { vote: vote };
  if (isPnP) payload.actor_id = myPlayerId;

  socket.emit("cast_lynch_vote", payload);
  myLynchVote = vote;
  renderActionUI(PHASE_LYNCH);
}

function populateSelect(
  elementId,
  players,
  includeNobody = false,
  includeSelf = true,
) {
  const select = document.getElementById(elementId);
  if (!select) return;
  const nobodyText = t({ key: "ui.game.nobody" }) || "Nobody";
  select.innerHTML = includeNobody
    ? `<option value="">${nobodyText}</option>`
    : "";
  [...players]
    .sort(() => 0.5 - Math.random())
    .forEach((p) => {
      if (!includeSelf && p.id === socket.id) return;
      select.innerHTML += `<option value="${p.id}">${p.name}</option>`;
    });
}

function submitNightAction(uiData) {
  const select = document.getElementById("action-select");
  const select2 = document.getElementById("action-select-2");
  const val1 = select ? select.value : null;
  const val2 = select2 ? select2.value : null;

  if (val1 && val2 && val1 === val2 && val1 !== "Nobody") {
    alert(
      t({ key: "ui.game.cannot_select_same" }) ||
        "Cannot select the same person twice!",
    );
    return;
  }

  const payload = { target_id: val1 };
  if (val2 !== null) {
    payload.metadata = uiData.potions ? { potion: val2 } : { target_id2: val2 };
  }

  // PnP Injection
  if (isPnP) {
    console.log(`[ACTION] Submitting action as Actor: ${myPlayerId}`);
    payload.actor_id = myPlayerId;
  }
  socket.emit("hero_choice", payload);

  // Optimistic UI Update
  const p1 =
    select && select.selectedIndex >= 0
      ? select.options[select.selectedIndex].text
      : "Nobody";
  const p2 =
    select2 && select2.selectedIndex >= 0
      ? select2.options[select2.selectedIndex].text
      : "Nobody";

  if (uiData.template && uiData.template.success) {
    let rawText = t({ key: uiData.template.success });
    rawText = rawText
      .replace(
        "{target}",
        `<span style="color:var(--highlight-color)">${p1}</span>`,
      )
      .replace(
        "{target2}",
        `<span style="color:var(--gold-color)">${p2}</span>`,
      )
      .replace(
        "{potion}",
        `<span style="color:var(--gold-color)">${p2}</span>`,
      );
    els.action.innerHTML = `<p>${rawText}</p>`;
  } else {
    els.action.innerHTML = "<p>Action Submitted.</p>";
  }
}

/**
 * Renders the Night Phase UI using the i18n Translation System.
 * Aligned with roles.py template structure.
 */
function renderNightUI(uiData, containerId = null) {
  const container = containerId
    ? document.getElementById(containerId)
    : els.action;
  if (!container) return;

  // ============================================================
  // CASE A: ACTION PENDING (User must select a target)
  // ============================================================
  if (myPhaseTargetId === null) {
    // 1. Sleeping / Loading State
    if (!uiData) {
      container.innerHTML = `<p>${t({ key: "ui.game.game_loading" })}</p>`; // Uses en.json value "Sleeping..."
      return;
    }

    // 2. Build Header Text
    // Use fallback "Action Required" if key missing
    let headerText =
      t({
        key: uiData.template.header,
        variables: uiData.template.variables,
      }) || "Action Required";

    let html = `<h4>${headerText}</h4>`;

    // Add Description (Optional - used by Cupid/Backlash)
    if (uiData.template.description) {
      const descText = t({
        key: uiData.template.description,
        variables: uiData.template.variables,
      });
      html += `<p class="role-desc">${descText}</p>`;
    }

    // 3. Detect Multi-Target Roles (Need 2nd Dropdown)
    const hKey = uiData.template.header || "";
    const isMultiTarget =
      uiData.potions ||
      hKey.includes("Cupid") ||
      hKey.includes("Backlash") ||
      hKey.includes("Witch");

    // 4. Build Controls
    html += `<select id="action-select"></select> `;
    if (isMultiTarget) {
      html += `<select id="action-select-2"></select> `;
    }
    const btnText = t({ key: uiData.template.button }) || "Submit";
    html += `<button id="action-btn">${btnText}</button>`;

    // Render to DOM
    container.innerHTML = html;

    // 5. Populate Dropdowns
    if (uiData.targets) {
      populateSelect("action-select", uiData.targets, uiData.can_skip, true);

      // Secondary List Logic
      if (uiData.potions) {
        // WITCH: Populate with Potion Names (Translated)
        // uiData.potions contains { id: "heal", name_key: "roles.Witch.night.potion_heal" }
        const translatedPotions = uiData.potions.map((p) => ({
          id: p.id,
          // If name_key exists, translate it. Otherwise use raw name.
          name: p.name_key ? t({ key: p.name_key }) : p.name,
        }));
        populateSelect("action-select-2", translatedPotions, false, false);
      } else if (isMultiTarget) {
        // CUPID/BACKLASH: Populate with same Player List
        populateSelect(
          "action-select-2",
          uiData.targets,
          uiData.can_skip,
          true,
        );
      }
    }

    // 6. Bind Click Event
    const btn = container.querySelector("#action-btn");
    if (btn && !containerId) {
      btn.onclick = () => submitNightAction(uiData);
    }
  }

  // ============================================================
  // CASE B: ACTION COMPLETED (Show Success/Feedback)
  // ============================================================
  else {
    // 1. Seer Results (Server sends direct HTML string sometimes)
    if (lastSeerResult) {
      container.innerHTML = `<p>${lastSeerResult}</p>`;
      return;
    }

    // 2. Resolve Variable Names for Feedback Message
    const targetObj = allPlayers.find((p) => p.id === myPhaseTargetId);
    let targetName = targetObj ? targetObj.name : "Nobody";
    let secondaryName = "Unknown";

    if (myNightMetadata) {
      if (myNightMetadata.potion) {
        // WITCH: Translate potion ID back to readable name
        // We construct the key: roles.Witch.night.potion_heal
        const roleKey = myRole || "Witch";
        const potionId = myNightMetadata.potion;
        const pKey = `roles.${roleKey}.night.potion_${potionId}`;

        // Attempt translation
        let pTrans = t({ key: pKey });

        // Fallback: If translation fails (returns key), just Capitalize ID
        if (pTrans === pKey) {
          pTrans = potionId.charAt(0).toUpperCase() + potionId.slice(1);
        }
        secondaryName = pTrans;
      } else if (myNightMetadata.target_id2) {
        // CUPID/BACKLASH: Resolve 2nd player name
        const t2 = allPlayers.find((p) => p.id === myNightMetadata.target_id2);
        secondaryName = t2 ? t2.name : "Nobody";
      }
    }

    // 3. Build & Translate Success Message
    let successMsg = `<p>${t({ key: "ui.pnp.done_msg" }) || "Action Submitted"}</p>`;

    if (uiData && uiData.template && uiData.template.success) {
      let rawText = t({ key: uiData.template.success });

      // Replace variables
      rawText = rawText
        .replace(
          "{target}",
          `<span style="color:var(--highlight-color)">${targetName}</span>`,
        )
        .replace(
          "{target2}",
          `<span style="color:var(--gold-color)">${secondaryName}</span>`,
        )
        .replace(
          "{potion}",
          `<span style="color:var(--gold-color)">${secondaryName}</span>`,
        );

      successMsg = `<p>${rawText}</p>`;
    }

    container.innerHTML = successMsg;
  }
}

function renderAccusationUI(currentDuration) {
  if (sleepButtonTimeout) clearTimeout(sleepButtonTimeout);

  let html = "";
  if (!isAlive && ghostModeActive) {
    html += "<h4 style='color: royalblue'>👻 Ghost Mode Active: ...</h4>";
  }

  if (myPhaseTargetId !== null)
    if (myPhaseTargetId === "Ghost_Fail") {
      const ghostFail = t({ key: "ui.game.ghost_fail" });
      const voteFail = t({ key: "ui.game.vote_failed" });
      html += `<h3 style="color: royalblue; font-style: italic;">${ghostFail}</h3><p>${voteFail}</p>`;
    } else {
      const target = allPlayers.find((p) => p.id === myPhaseTargetId);
      const tName = target ? target.name : "Nobody";
      // [CHANGED]
      const accusedMsg = t({
        key: "ui.game.you_accused",
        variables: { name: tName },
      });
      const waitMsg = t({ key: "ui.game.waiting_others" });
      html += `<h3>${accusedMsg}</h3><p>${waitMsg}</p>`;
    }
  else {
    const prompt = t({ key: "ui.game.accusation_prompt" });
    const btnAccuse = t({ key: "actions.accuse" }) || "Accuse";
    html += `
                <h4>${prompt}</h4>
                <select id="accuse-select"></select>
                <button id="accuse-btn">${btnAccuse}</button>`;
  }

  const timeToEnable =
    (currentDuration || totalAccusationDuration) -
    (totalAccusationDuration - 30);
  let btnState = mySleepVote ? "disabled" : timeToEnable <= 0 ? "" : "disabled";

  let btnText = "";
  if (mySleepVote) {
    btnText = t({ key: "actions.voted_sleep" });
  } else if (timeToEnable <= 0) {
    btnText = `💤 ${t({ key: "actions.vote_sleep" })}`;
  } else {
    btnText = t({
      key: "actions.vote_sleep_timer",
      variables: { time: timeToEnable.toFixed(1) },
    });
  }

  // [CHANGED] Header Translation
  const readyHeader = t({ key: "ui.game.ready_for_night" });

  html += `<hr style="border-color: #444; margin: 15px 0;">
             <div id="sleep-section"><h4>${readyHeader}</h4><button id="vote-end-day-btn" ${btnState}>${btnText}</button><span id="end-day-vote-counter" style="margin-left:10px; font-size:0.9em; color:#aaa"></span></div>`;

  els.action.innerHTML = html;

  // 3. Attach Listeners (Now that elements are stable)
  if (myPhaseTargetId === null) {
    populateSelect("accuse-select", livingPlayers, true, true);
    const accBtn = document.getElementById("accuse-btn");
    if (accBtn) {
      accBtn.onclick = () => {
        let pid = document.getElementById("accuse-select").value;
        let payload = { target_id: pid };
        if (isPnP) payload.actor_id = myPlayerId; // [ADDED]
        socket.emit("accuse_player", payload);
      };
    }
  }

  // Sleep Button Logic
  const voteBtn = document.getElementById("vote-end-day-btn");
  if (voteBtn && !mySleepVote && timeToEnable > 0) {
    sleepButtonTimeout = setTimeout(() => {
      const b = document.getElementById("vote-end-day-btn");
      if (b) {
        b.disabled = false;
        b.textContent = "💤 Vote to Sleep";
      }
    }, timeToEnable * 1000);
  }
  if (voteBtn && !mySleepVote)
    voteBtn.onclick = function () {
      let payload = {};
      if (isPnP) payload.actor_id = myPlayerId;
      socket.emit("vote_to_end_day", payload);

      this.disabled = true;
      this.textContent = "Voted to Sleep 💤";
      mySleepVote = true;
    };
}

function renderLynchVoteUI() {
  let html = "";
  if (!isAlive && ghostModeActive) {
    html += `<h4 style='color: royalblue'>${t({ key: "ui.game.ghost_active" })}</h4>`;
  }
  if (myLynchVote === "Ghost_Fail") {
    html += `<h3 style="color: royalblue; font-style: italic;">${t({ key: "ui.game.ghost_fail" })}</h3><p>${t({ key: "ui.game.vote_failed" })}</p>`;
    els.action.innerHTML = html;
  } else if (myLynchVote === "yes" || myLynchVote === "no") {
    const votedTxt = translations.ui.game.voted_btn || "Voted!";
    els.action.innerHTML = `<h3>${votedTxt} <span style="color:${myLynchVote === "yes" ? "green" : "red"}">${myLynchVote.toUpperCase()}</span></h3><p>Waiting for result...</p>`;
  } else {
    // If not voted, SHOW BUTTONS
    const yesTxt = t({ key: "actions.lynch_yes" }) || "YES";
    const noTxt = t({ key: "actions.lynch_no" }) || "NO";
    // [CHANGED]
    const prompt = t({
      key: "ui.game.lynch_prompt",
      variables: { name: currentLynchTargetName },
    });
    els.action.innerHTML = `
             <h4>${prompt}</h4>
             <button onclick="submitLynchVote('yes')" class="vote-btn-yes">${yesTxt}</button>
             <button onclick="submitLynchVote('no')" class="vote-btn-no">${noTxt}</button>`;
  }
}

function renderActionUI(phase, currentDuration = 0) {
  els.action.innerHTML = "";
  if (phase) updatePhaseDisplay(phase);

  // DEAD VIEW
  if (!isAlive) {
    if (!ghostModeActive) {
      els.action.innerHTML = t({ key: "ui.game.dead_message" });
      return;
    }
    els.action.innerHTML = `<h4 style='color: darkgray'>${t({ key: "ui.game.ghost_active" })}</h4>`;
  }
  if (phase === PHASE_NIGHT) renderNightUI(currentNightUI);
  else if (phase === PHASE_ACCUSATION) renderAccusationUI(currentDuration);
  else if (phase === PHASE_LYNCH) renderLynchVoteUI();
  else els.action.innerHTML = "<p>Please wait...</p>";
}

function updatePhaseDisplay(phase) {
  if (!phase) return;

  // Map phase ID to translation key
  let phaseKey = "ui.game.night_phase_title";
  if (phase === PHASE_ACCUSATION) phaseKey = "ui.pnp.hub_day";
  if (phase === PHASE_LYNCH) phaseKey = "ui.pnp.hub_vote";
  if (phase === PHASE_GAME_OVER) phaseKey = "ui.game.game_over_title";

  // Set Text
  els.phase.textContent = t({ key: phaseKey }) || phase.replace(/_/g, " ");

  // Set Styles
  if (phase === "Night") {
    els.phase.style.color = "lightskyblue";
    els.phase.style.textShadow = "0 0 5px #00bcd4, 0 0 10px #00bcd4";
  } else if (phase === "Accusation") {
    els.phase.style.color = "white";
    els.phase.style.textShadow = "0 0 5px #ffb74d, 0 0 10px #ff9800";
  } else if (phase === "Lynch_Vote") {
    els.phase.style.color = "white";
    els.phase.style.textShadow = "0 0 5px #ff5252, 0 0 10px #ff1744";
  }
}

function startTimer(endTimeStamp) {
  if (timerInterval) clearInterval(timerInterval);
  els.timer.textContent = "";
  if (timersDisabled) {
    els.timer.textContent = t({ key: "ui.game.timer_disabled" }) || "Timer ♾️";
    return;
  }
  if (!endTimeStamp) return;

  const update = () => {
    const timeLeft = Math.max(0, Math.ceil(endTimeStamp - Date.now() / 1000));
    const min = Math.floor(timeLeft / 60),
      sec = Math.floor(timeLeft % 60);
    const label = t({ key: "ui.game.timer_left" }) || "Time left: ";
    const done = t({ key: "ui.game.time_up" }) || "Time's up!";

    els.timer.textContent = `${label}${min}:${("0" + sec).slice(-2)}`;
    if (timeLeft <= 0) {
      clearInterval(timerInterval);
      els.timer.textContent = done;
    }
  };
  update();
  timerInterval = setInterval(update, 1000);
}

function showGameOverScreen(data, rematchInfo = {}) {
  if (timerInterval) clearInterval(timerInterval);
  els.gameContainer.style.display = "none";
  els.gameOverScreen.style.display = "flex";
  els.pnpHub.style.display = "none";

  // 1. Title
  let titleKey = "ui.game.win_generic";
  if (data.winning_team === "Villagers") titleKey = "ui.game.win_villagers";
  if (data.winning_team === "Werewolves") titleKey = "ui.game.win_werewolves";

  let titleText = t({ key: titleKey, variables: { team: data.winning_team } });
  document.getElementById("game-over-title").textContent = titleText;

  // 2. Reason (Handle Object or String)
  document.getElementById("game-over-reason").innerHTML = t(data.reason);

  // 3. Final Roles List
  const list = document.getElementById("final-roles-list");
  list.innerHTML = "";

  data.final_player_states.forEach((p) => {
    const isWinner =
      (data.winning_team === "Villagers" && p.team === "Villagers") ||
      (data.winning_team === "Werewolves" && p.team === "Werewolves") ||
      data.winning_team === p.name;
    const isSoloWinner =
      p.status_effects && p.status_effects.includes("solo_win");

    let badges = "";
    if (isWinner) badges += " 🏆";
    if (isSoloWinner) badges += " 🥇";
    if (!p.is_alive) badges += " 💀";

    // [CHANGED] Translate Role Name
    const roleKey = p.role.replace(/ /g, "_");
    const roleName = t({ key: `roles.${roleKey}.name` }) || p.role;

    // [CHANGED] Use a sentence template for "Bob was a Villager"
    // Fallback included if key is missing
    let lineText = t({
      key: "ui.game.final_role_item",
      variables: { name: p.name, role: roleName, badges: badges },
    });

    // Fallback if translation key is missing
    if (lineText === "ui.game.final_role_item") {
      lineText = `<strong>${p.name}</strong>${badges} was a ${roleName}`;
    }

    list.innerHTML += `<li>${lineText}</li>`;
  });

  const mainLog = document.getElementById("log-panel");
  const gameOverLog = document.getElementById("game-over-log");
  if (mainLog && gameOverLog) gameOverLog.innerHTML = mainLog.innerHTML;

  const btn = document.getElementById("return-to-lobby-btn");
  btn.onclick = (e) => {
    socket.emit("vote_for_rematch");
    e.target.disabled = true;
    e.target.textContent = t({ key: "ui.game.voted_btn" }) || "Voted!";
  };
  btn.disabled = rematchInfo.hasVoted;

  const btnText = t({ key: "ui.game.return_lobby_btn" }) || "Vote to Return";
  const votedText = t({ key: "ui.game.voted_btn" }) || "Voted!";
  btn.textContent = rematchInfo.hasVoted ? votedText : btnText;

  const status = document.getElementById("rematch-vote-status");
  if (status && rematchInfo.count !== undefined) {
    let statText = t({
      key: "ui.game.rematch_status",
      variables: { count: rematchInfo.count, total: rematchInfo.total },
    });
    status.textContent = statText;
  }

  document.getElementById("game-over-chat-container").style.display = isPnP
    ? "none"
    : "flex";
}

// --- Socket Events ---
socket.on("connect", () => {
  socket.emit("client_ready_for_game");
});

socket.on("force_phase_update", () => {
  // Signal that the Ghost's action was processed but failed (RNG)
  myPhaseTargetId = "Ghost_Fail";

  // Force UI refresh to show the "Ghostly wails went unheard" message
  if (currentPhase === PHASE_ACCUSATION) {
    renderActionUI(PHASE_ACCUSATION);
  }
});

socket.on("game_state_sync", (data) => {
  // 1. Detect Phase Change to Clear PnP History
  isPnP = data.mode === "pass_and_play";

  let phaseChanged = data.phase !== currentPhase;

  if (data.acted_players) {
    hasActed = new Set(data.acted_players);
  } else {
    hasActed.clear();
  }

  const isGameVisible = els.gameContainer.style.display !== "none";
  const isOverlayOpen = els.pnpOverlay.style.display === "flex";
  const overlayTitle = document.getElementById("overlay-title");
  const isDoneScreen =
    isOverlayOpen && overlayTitle && overlayTitle.innerText === "Done";

  if (!phaseChanged && isPnP) {
    if ((isGameVisible || isOverlayOpen) && !isDoneScreen) {
      console.log("Ignored sync while busy acting/confirming.");
      // Update hasActed silently so Hub stays current in background, but don't touch UI
      return;
    }
  }

  // Update Globals
  myRole = data.your_role;
  isAdmin = data.is_admin;
  isAlive = data.is_alive;
  livingPlayers = data.living_players;
  allPlayers = data.all_players;
  timersDisabled = data.timers_disabled;
  myPhaseTargetId = data.my_phase_target_id;
  myNightMetadata = data.my_phase_metadata || {};
  currentNightUI = data.night_ui;
  mySleepVote = data.my_sleep_vote;
  myLynchVote = data.my_lynch_vote;
  ghostModeActive = data.ghost_mode_active;
  currentLynchTargetName = data.lynch_target_name || "Unknown";
  if (data.total_accusation_duration)
    totalAccusationDuration = data.total_accusation_duration;

  if (data.message_history) publicHistory = data.message_history;

  if (data.message_history && els.log.innerHTML.trim() === "") {
    data.message_history.forEach((msg) => logMessage(msg, false));
    // Scroll to bottom
    els.log.scrollTop = els.log.scrollHeight;
  }

  if (myPhaseTargetId === null) lastSeerResult = null;

  if (data.phase === PHASE_GAME_OVER && data.game_over_data) {
    showGameOverScreen(data.game_over_data, {
      hasVoted: data.my_rematch_vote,
      count: data.rematch_vote_count,
      total: data.all_players.length,
    });
    setChatMode(data.admin_only_chat, data.phase);
    return;
  }

  if (
    isPnP &&
    (data.phase === PHASE_NIGHT ||
      data.phase === PHASE_ACCUSATION ||
      data.phase === PHASE_LYNCH)
  ) {
    // Force hide standard game, show Hub
    els.gameContainer.style.display = "none";
    renderHub(allPlayers, data.phase);
    updatePhaseDisplay(data.phase);
  } else {
    // Standard Game Mode OR PnP Day Phase
    els.pnpHub.style.display = "none";
    els.pnpOverlay.style.display = "none";
    els.gameContainer.style.display = "flex";

    const mainPanel = document.querySelector(".main-panel");
    if (els.log && mainPanel) {
      mainPanel.appendChild(els.log);
    }

    if (isPnP) {
      els.pnpReturnBtn.classList.remove("pnp-hidden");
    } else {
      els.pnpReturnBtn.classList.add("pnp-hidden");
    }

    const displayRole = myRole === "Random_Seer" ? "Seer" : myRole;

    const roleName = t({ key: `roles.${displayRole}.name` }) || displayRole;
    els.role.textContent = roleName + (isAdmin ? " 👑" : "");
    if (typeof updateRoleTooltip === "function") updateRoleTooltip(displayRole);

    updatePhaseDisplay(data.phase);
    renderActionUI(data.phase, data.duration);

    setChatMode(data.admin_only_chat, data.phase);
  }

  currentPhase = data.phase;

  if (data.phase === PHASE_ACCUSATION) {
    const needed =
      1 +
      Math.floor(data.living_players.length / 2) -
      (data.sleep_vote_count || 0);
    const counter = document.getElementById("end-day-vote-counter");
    if (counter && needed > 0)
      counter.innerHTML = `<strong>${needed}</strong> more votes needed to sleep!`;
  }

  updatePlayerListView(data.accusation_counts || {});
  updateAdminControls();
  startTimer(data.phase_end_time);
});

socket.on("phase_change", (data) => {
  // RESTORED: UX Alert
  const msg = `A new phase has begun: <strong>${data.phase.replace(/_/g, " ")}</strong>.`;
  publicHistory.push(msg);
  logMessage(msg, false);
  setTimeout(() => {
    socket.emit("client_ready_for_game");
  }, 500);
});

socket.on("message", (data) => {
  logMessage(data.text, false);
});

socket.on("new_message", (data) => {
  const div = document.createElement("div");
  div.innerHTML = DOMPurify.sanitize(data.text);
  const target = document.getElementById("game-chat-messages");
  const overTarget = document.getElementById("game-over-chat-messages");

  if (data.channel === "announcement") {
    div.classList.add("announcement");
    if (target) target.prepend(div.cloneNode(true));
    if (overTarget) overTarget.prepend(div.cloneNode(true));
  } else if (data.channel === "lobby" && overTarget) {
    overTarget.prepend(div);
  } else if (isAlive && data.channel === "living" && target) {
    target.prepend(div);
  } else if (!isAlive && data.channel === "ghost" && target) {
    div.classList.add("ghost-chat");
    target.prepend(div);
  }
});

socket.on("chat_mode_update", (data) => {
  setChatMode(data.admin_only_chat, data.phase);
});

socket.on("pnp_action_confirmed", () => {
  // We add the actor to 'hasActed' set to gray out button on Hub
  if (myPlayerId) hasActed.add(myPlayerId);
  // Show overlay message
  /* els.pnpOverlay.style.display = "flex";
        document.getElementById("overlay-title").innerText = t("ui.pnp.done_title", "Done");
        document.getElementById("overlay-title").style.color = "#4caf50";
        document.getElementById("overlay-msg").innerText = t("ui.pnp.done_msg", "Action Recorded");
        document.getElementById("overlay-actions").innerHTML = `<p>${t("ui.pnp.pass_device", "Pass device...")}</p>`;
        document.getElementById("overlay-action-area").innerHTML = "";
              setTimeout(() => requestGameSync(), 2000);
        */
});

socket.on("pnp_player_done", (data) => {
  if (data && data.player_id) {
    // 1. Always update the background state
    hasActed.add(data.player_id);

    // 2. SAFETY CHECK: Only refresh UI if we are actually looking at the Hub
    const isHubVisible = els.pnpHub && els.pnpHub.style.display !== "none";

    if (isPnP && isHubVisible) {
      // Pass the current global 'allPlayers' and 'currentPhase'
      renderHub(allPlayers, currentPhase);
    }
  }
});

socket.on("night_result_kill", (data) => {
  if (data.message) {
    logMessage(data.message, false);
    console.log("publicHistory add: ${data.message}");
    publicHistory.push(data.message);
  }
  // Update local state if I am the one who died
  if (data.killed_player && myPlayerId === data.killed_player.id) {
    isAlive = false;
  }
});

socket.on("seer_result", (data) => {
  // [CHANGED] Translate the role name (e.g., "Werewolf" -> "Hombre Lobo")
  const roleKey = `roles.${data.role}.name`;
  const translatedRole = t({ key: roleKey }) || data.role;

  // [CHANGED] Use translation key with variables
  const msg = t({
    key: "events.seer_result",
    variables: { name: data.name, role: translatedRole },
  });

  logMessage(msg, true);
  lastSeerResult = msg;
  els.action.innerHTML = `<p>${msg}</p>`;
});

socket.on("cupid_info", (data) => {
  logMessage(data.message, true);
});

socket.on("werewolf_team_info", (data) => {
  // [CHANGED] Use translation keys
  let msg;
  if (data.teammates.length) {
    msg = t({
      key: "events.wolf_team",
      variables: { mates: data.teammates.join(", ") },
    });
  } else {
    msg = t({ key: "events.wolf_lone" });
  }
  logMessage(msg, true);
});

socket.on("lynch_vote_result", (data) => {
  let baseMsg = t(data.message);
  let msg =
    baseMsg +
    (data.summary
      ? `<div class="vote-summary">Voted Yes: ${
          data.summary.yes.join(", ") || "None"
        }<br>Voted No: ${data.summary.no.join(", ") || "None"}</div>`
      : "");
  // Use standard logging
  publicHistory.push(msg);
  logMessage(msg, false);
  if (data.killed_id === myPlayerId) isAlive = false;
});

socket.on("accusation_made", (data) => {
  msg = `🫵 <strong>${data.accuser_name}</strong> accuses <strong>${data.accused_name}</strong>!`;
  publicHistory.push(msg);
  logMessage(msg, false);

  if (myPlayerId === data.accuser_id) {
    myPhaseTargetId =
      data.accused_id !== undefined
        ? data.accused_id
        : data.accused_name === "Nobody"
          ? ""
          : "Vote_Cast";

    if (currentPhase === PHASE_ACCUSATION) renderActionUI(PHASE_ACCUSATION);
  }
});

socket.on("accusation_update", (data) => updatePlayerListView(data));

socket.on("end_day_vote_update", (data) => {
  const c = document.getElementById("end-day-vote-counter");
  if (c)
    c.innerHTML = `<strong>${
      1 + Math.floor(data.total / 2) - data.count
    }</strong> more votes needed to sleep!`;
});

socket.on("lynch_vote_started", (data) => {
  msg = `⛓️ <strong>${data.target_name}</strong> is on trial!`;
  publicHistory.push(msg);
  logMessage(msg, false);

  currentLynchTargetName = data.target_name;
  currentPhase = PHASE_LYNCH;
  hasActed.clear();

  updatePhaseDisplay("Lynch_Vote");
  renderActionUI(PHASE_LYNCH);
  startTimer(data.phase_end_time);

  if (isPnP) renderHub(allPlayers, PHASE_LYNCH);
});

socket.on("game_over", (data) => {
  showGameOverScreen(data);
});

socket.on("rematch_vote_update", (data) => {
  const s = document.getElementById("rematch-vote-status");
  if (s)
    s.textContent = `${data.count} / ${data.total} players have voted to return.`;
});

socket.on("redirect_to_lobby", () => {
  window.location.href = "/lobby";
});

socket.on("force_relogin", (data) => {
  alert(t({ key: "ui.game.alert_relogin" }));
  window.location.href = "/";
});

socket.on("error", (data) => {
  alert(t({ key: "ui.game.alert_error", variables: { msg: data.message } }));
});

function updatePlayerListView(accusationCounts = {}) {
  els.playerList.innerHTML = "";
  const livingIds = livingPlayers.map((p) => p.id);
  allPlayers.forEach((p) => {
    const li = document.createElement("li");

    const isMe = p.id === myPlayerId;

    let youTag = isMe ? ` ${t({ key: "ui.lobby.you_suffix" }) || "(You)"}` : "";
    let nameDisplay = `${p.name}${youTag}`;

    let html = `<span>${nameDisplay}</span>`;

    if (accusationCounts[p.id]) {
      html += `<span class="accusation-count">${accusationCounts[p.id]}</span>`;
    }

    li.innerHTML = html;

    if (!livingIds.includes(p.id)) {
      li.classList.add("dead");
      li.style.opacity = "0.5"; // Fade out dead players
      li.firstChild.innerHTML = `💀 <s>${nameDisplay}</s>`;
    }
    if (isMe) {
      li.style.fontWeight = "bold";
      li.style.color = "#ffffff";
      li.style.border = "1px solid darkviolet"; // Purple border
      li.style.backgroundColor = "rgba(187, 134, 252, 0.1)";
    }

    els.playerList.appendChild(li);
  });
}

// --- Setup Handlers ---
function bindChatHandler(formId, inputId) {
  const form = document.getElementById(formId);
  const input = document.getElementById(inputId);
  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (input.value.trim())
        socket.emit("send_message", { message: input.value });
      input.value = "";
    });
  }
}
bindChatHandler("game-chat-form", "game-chat-input");
bindChatHandler("game-over-chat-form", "game-over-chat-input");

els.adminChatToggle.addEventListener("click", () =>
  socket.emit("admin_toggle_chat"),
);
document
  .getElementById("admin-next-phase-btn")
  .addEventListener("click", () => socket.emit("admin_next_phase"));
const adminPauseBtn = document.getElementById("admin-pause-timer-btn");
if (adminPauseBtn)
  adminPauseBtn.addEventListener("click", () =>
    socket.emit("admin_set_timers", { timers_disabled: !timersDisabled }),
  );
