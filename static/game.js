// Version 4.9.2
const PHASE_LOBBY = "Lobby";
const PHASE_NIGHT = "Night";
const PHASE_ACCUSATION = "Accusation";
const PHASE_LYNCH = "Lynch_Vote";
const PHASE_GAME_OVER = "Game_Over";

const socket = io();
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
  let div = document.createElement("div");
  div.innerHTML = DOMPurify.sanitize(message);
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
      pauseBtn.textContent = timersDisabled
        ? "Resume Timers ▶️"
        : "Pause Timers ⏸️";
      pauseBtn.style.backgroundColor = timersDisabled ? orangered : "";
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

  // Clear any previous injected buttons
  if (actionArea) actionArea.innerHTML = "";

  // 1. Show Overlay
  overlay.style.display = "flex";

  // 2. Set Content
  title.innerText = "Force Next Phase";
  title.style.color = "orange";
  msg.innerHTML =
    "⚠️ <strong>Warning:</strong><br>This will skip remaining turns for this phase.<br>Are you sure?";

  // 3. Define Actions
  // UPDATED: Calls named function doForcePhase() for better reliability
  actions.innerHTML = `
                  <button class="big-btn" style="background-color: crimson;" onclick="doForcePhase()">
                      Yes, Force Next Phase
                  </button>
                  <button class="big-btn cancel" style="background-color: royalblue" onclick="closeOverlay()">
                      Cancel
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

  const phaseName = phase ? phase.replace(/_/g, " ") : "Game";
  // Ensure the h2 element exists before setting text
  const titleEl = document.querySelector("#pnp-hub h2");
  if (titleEl) {
    titleEl.textContent = `${phaseName} Phase`;

    // [ADDED] Dynamic Colors for PnP Hub
    if (phase === "Night") {
      titleEl.style.color = "lightskyblue"; // Light Blue
      titleEl.textContent += " 🌙";
      titleEl.style.textShadow =
        "0 0 5px #00bcd4, 0 0 10px #00bcd4, 0 0 20px #00bcd4, 0 0 40px #00bcd4"; // Glowing effect
    } else if (phase === "Accusation") {
      titleEl.style.color = "white";
      titleEl.textContent += " 🫵";
      titleEl.style.textShadow =
        "0 0 5px #ffb74d, 0 0 10px #ff9800, 0 0 20px #ff9800, 0 0 40px #ff9800";
    } else if (phase === "Lynch_Vote") {
      titleEl.style.color = "white";
      titleEl.textContent += " 🔥";
      titleEl.style.textShadow =
        "0 0 5px #ff5252, 0 0 10px #ff1744, 0 0 20px #d50000, 0 0 40px #b71c1c";
    } else {
      titleEl.style.color = "darkviolet"; // Standard Purple default
      titleEl.style.textShadow = "none";
    }
  }

  els.pnpGrid.innerHTML = allPlayers
    .map((p) => {
      // Show All Players, disable if acted or dead without ghost mode
      const isDay = phase === PHASE_ACCUSATION || phase === PHASE_LYNCH;
      const isGhostActive = !p.is_alive && ghostModeActive && isDay;

      // button clickable if not acted and alive, or ghost
      const isInteractive =
        !hasActed.has(p.id) && (p.is_alive || isGhostActive);
      let deadClass = "pnp-btn";
      if (!isInteractive) deadClass += " dead";

      const safeName = p.name.replace(/'/g, "\\'");
      const clickAction = isInteractive
        ? `startConfirmFlow('${p.id}', '${safeName}')`
        : "";

      let label = p.name;
      if (!p.is_alive) label += " 👻"; // Add Ghost icon for clarity
      if (hasActed.has(p.id)) label += " (Done)";

      return `<div class="${deadClass}" onclick="${clickAction}">${label}</div>`;
    })
    .join("");
}

function startConfirmFlow(pid, name) {
  const overlay = els.pnpOverlay;
  const title = document.getElementById("overlay-title");
  const msg = document.getElementById("overlay-msg");
  const actions = document.getElementById("overlay-actions");
  const actionArea = document.getElementById("overlay-action-area");

  // Reset action area so previous buttons don't persist
  if (actionArea) actionArea.innerHTML = "";

  overlay.style.display = "flex";
  title.innerText = "Identity Check";
  title.style.color = "#bb86fc";
  msg.innerHTML = `Are you <strong>${name}</strong>?`;

  actions.innerHTML = `
            <button class="big-btn" onclick="confirmLevel2('${pid}', '${name.replace(/'/g, "\\'")}')">Yes, I am ${name}</button>
            <button class="big-btn cancel" onclick="closeOverlay()">No, go back</button>
        `;
}

function closeOverlay() {
  els.pnpOverlay.style.display = "none";
}

function confirmLevel2(pid, name) {
  const title = document.getElementById("overlay-title");
  const msg = document.getElementById("overlay-msg");
  const actions = document.getElementById("overlay-actions");

  title.innerText = "Confirm Identity";
  title.style.color = "#f44336"; // Warning Red
  msg.innerHTML = `Make sure <strong>${name}</strong> has the device.<br>Don't show the screen to anyone else.`;

  actions.innerHTML = `
            <button class="big-btn" onclick="socket.emit('pnp_request_state', { player_id: '${pid}' })">I am Ready</button>
            <button class="big-btn cancel" onclick="closeOverlay()">Cancel</button>
        `;
}

socket.on("pnp_state_sync", (data) => {
  // 1. Hide Hub & Overlay
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
  els.role.textContent = displayRole.replace(/_/g, " ");
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
    team: "Unknown",
  };

  let teamName = rData.team || "Neutral";
  let teamColor = "darkgray";

  if (teamName === "Werewolves") {
    teamColor = "red";
    teamName = "🐺 Team Werewolf";
  } else if (teamName === "Villagers") {
    teamColor = "mediumblue";
    teamName = "🌻 Team Villager";
  } else if (
    teamName === "Monster" ||
    teamName === "Neutral" ||
    teamName === "Serial_Killer"
  ) {
    teamColor = "darkviolet"; // Purple
    teamName = "🎭 Solo Squad";
  }

  const tooltipEl = document.getElementById("my-role-tooltip");
  if (tooltipEl) {
    tooltipEl.innerHTML = `
                  <strong style="color: ${rData.color || "yellow"}; font-size: 1.2em; display:block; margin-bottom:8px;">
                      ${roleKey}
                  </strong>
                  <div style="text-align: left; margin-bottom: 8px; line-height: 1.4;">
                      ${rData.long}
                  </div>
                  <div style="font-size:0.85em; border-top:1px solid #444; padding-top:5px;">
                  <strong style="color: ${rData.color}; float: left">${rData.rating}</strong>
                  <span style="float: right; color: ${teamColor};">${teamName}</span></div> `;
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
  select.innerHTML = includeNobody ? `<option value="">Nobody</option>` : "";
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
    alert("Cannot select the same person twice!");
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
  els.action.innerHTML = uiData.post
    .replace("${playerPicked}", p1)
    .replace("${playerPicked2}", p2);
}

// Updated to allow rendering into a specific container (for PnP reuse)
function renderNightUI(uiData, containerId = null) {
  const container = containerId
    ? document.getElementById(containerId)
    : els.action;
  if (!container) return;

  if (myPhaseTargetId === null) {
    if (!uiData || !uiData.pre) {
      container.innerHTML = "<p>Sleeping...</p>";
      return;
    }
    container.innerHTML = uiData.pre;
    // 1st dropdown
    if (uiData.targets) {
      populateSelect("action-select", uiData.targets, uiData.can_skip, true);
      // 2nd dropdown
      if (uiData.potions)
        populateSelect("action-select-2", uiData.potions, false, false);
      else if (document.getElementById("action-select-2"))
        populateSelect(
          "action-select-2",
          uiData.targets,
          uiData.can_skip,
          true,
        );
    }
    // 4. Handle Button Click (Default standard behavior)
    const btn = container.querySelector("#action-btn");
    if (btn && !containerId) btn.onclick = () => submitNightAction(uiData);
  } else {
    // Night Action already performed
    if (lastSeerResult) {
      container.innerHTML = `<p>${lastSeerResult}</p>`;
      return;
    }
    let p2 = "Unknown";
    if (myNightMetadata && myNightMetadata.potion)
      p2 =
        myNightMetadata.potion === "heal"
          ? "Heal Potion"
          : myNightMetadata.potion === "poison"
            ? "Poison Potion"
            : "Nothing";
    // If Cupid: metadata.target_id2
    else if (myNightMetadata && myNightMetadata.target_id2)
      p2 =
        allPlayers.find((p) => p.id === myNightMetadata.target_id2)?.name ||
        "Nobody";

    const target = allPlayers.find((p) => p.id === myPhaseTargetId);
    container.innerHTML = (uiData.post || "<p>Action submitted.</p>")
      .replace("${playerPicked}", target ? target.name : "Nobody")
      .replace("${playerPicked2}", p2);
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
      html += `<h3 style="color: royalblue; font-style: italic;">👻 Your ghostly wails went unheard...</h3><p>Vote failed.</p>`;
    } else {
      const target = allPlayers.find((p) => p.id === myPhaseTargetId);
      html += `<h3>You have accused <span style="color:#ff5252">${
        target ? target.name : "Nobody"
      }</span>.</h3><p>Waiting for others...</p>`;
    }
  else {
    html += `
                <h4>Who is the Werewolf? Time for discussion!</h4>
                <select id="accuse-select"></select>
                <button id="accuse-btn">Accuse</button>`;
  }

  const timeToEnable =
    (currentDuration || totalAccusationDuration) -
    (totalAccusationDuration - 30);
  let btnState = mySleepVote ? "disabled" : timeToEnable <= 0 ? "" : "disabled";
  let btnText = mySleepVote
    ? "Voted to Sleep 💤"
    : timeToEnable <= 0
      ? "💤 Vote to Sleep"
      : `Vote to Sleep (${timeToEnable.toFixed(1)}s)`;

  html += `<hr style="border-color: #444; margin: 15px 0;">
             <div id="sleep-section"><h4>Ready for Night?</h4><button id="vote-end-day-btn" ${btnState}>${btnText}</button><span id="end-day-vote-counter" style="margin-left:10px; font-size:0.9em; color:#aaa"></span></div>`;

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
    html += "<h4 style='color: royalblue'>👻 Ghost Mode Active: ...</h4>";
  }
  if (myLynchVote === "Ghost_Fail") {
    html += `<h3 style="color: royalblue; font-style: italic;">👻 Your ghostly voice faded...</h3><p>Vote failed.</p>`;
    els.action.innerHTML = html;
  } else if (myLynchVote === "yes" || myLynchVote === "no") {
    els.action.innerHTML = `<h3>You voted: <span style="color:${
      myLynchVote === "yes" ? "green" : "red"
    }">${myLynchVote.toUpperCase()}</span></h3><p>Waiting for result...</p>`;
  } else {
    // If not voted, SHOW BUTTONS
    els.action.innerHTML = `
             <h4>Will you lynch <span style="color:#bb86fc">${currentLynchTargetName}</span>?</h4>
             <button onclick="submitLynchVote('yes')" class="vote-btn-yes">YES</button>
             <button onclick="submitLynchVote('no')" class="vote-btn-no">NO</button>`;
  }
}

function renderActionUI(phase, currentDuration = 0) {
  els.action.innerHTML = "";
  // DEAD VIEW
  if (!isAlive) {
    if (!ghostModeActive) {
      els.action.innerHTML =
        "<h3>You are dead 💀 You can observe the game in silence.</h3>";
      return;
    }
    els.action.innerHTML =
      "<h4 style='color: darkgray'>👻 Ghost Mode Active: ...</h4>";
  }
  if (phase === PHASE_NIGHT) renderNightUI(currentNightUI);
  else if (phase === PHASE_ACCUSATION) renderAccusationUI(currentDuration);
  else if (phase === PHASE_LYNCH) renderLynchVoteUI();
  else els.action.innerHTML = "<p>Please wait...</p>";
}

function startTimer(endTimeStamp) {
  if (timerInterval) clearInterval(timerInterval);
  els.timer.textContent = "";
  if (timersDisabled) {
    els.timer.textContent = "Timer ♾️";
    return;
  }
  if (!endTimeStamp) return;

  const update = () => {
    const timeLeft = Math.max(0, Math.ceil(endTimeStamp - Date.now() / 1000));
    const min = Math.floor(timeLeft / 60),
      sec = Math.floor(timeLeft % 60);
    els.timer.textContent = `Time left: ${min}:${("0" + sec).slice(-2)}`;
    if (timeLeft <= 0) {
      clearInterval(timerInterval);
      els.timer.textContent = "Time's up!";
    }
  };
  update();
  timerInterval = setInterval(update, 1000);
}

function showGameOverScreen(data, rematchInfo = {}) {
  if (timerInterval) clearInterval(timerInterval);
  els.gameContainer.style.display = "none";
  els.gameOverScreen.style.display = "flex";

  // Ensure PnP hub is hidden
  els.pnpHub.style.display = "none";

  document.getElementById("game-over-title").textContent =
    data.winning_team === "Villagers" || data.winning_team === "Werewolves"
      ? `The ${data.winning_team} Win!`
      : `${data.winning_team} Won!`;
  document.getElementById("game-over-reason").innerHTML = data.reason;

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

    list.innerHTML += `<li><strong>${p.name}</strong>${badges} was a ${p.role}</li>`;
  });

  const mainLog = document.getElementById("log-panel");
  const gameOverLog = document.getElementById("game-over-log");
  if (mainLog && gameOverLog) gameOverLog.innerHTML = mainLog.innerHTML;

  const btn = document.getElementById("return-to-lobby-btn");
  btn.onclick = (e) => {
    socket.emit("vote_for_rematch");
    e.target.disabled = true;
    e.target.textContent = "Voted!";
  };
  btn.disabled = rematchInfo.hasVoted;
  btn.textContent = rematchInfo.hasVoted ? "Voted!" : "Vote to Return to Lobby";

  const status = document.getElementById("rematch-vote-status");
  if (status && rematchInfo.count !== undefined)
    status.textContent = `${rematchInfo.count} / ${rematchInfo.total} players have voted to return.`;

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
    let phaseName = data.phase.replace(/_/g, " ");
    els.phase.textContent = `${phaseName}`;
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
    els.role.textContent = displayRole + (isAdmin ? " 👑" : "");
    if (typeof updateRoleTooltip === "function") updateRoleTooltip(displayRole);

    if (data.phase) els.phase.textContent = data.phase.replace(/_/g, " ");
    renderActionUI(data.phase, data.duration);

    setChatMode(data.admin_only_chat, data.phase);
  }

  currentPhase = data.phase;
  if (currentPhase === "Night") {
    els.phase.style.color = "lightskyblue"; // Light Blue for Night
    els.phase.textContent += " 🌙";
    els.phase.style.textShadow =
      "0 0 5px #00bcd4, 0 0 10px #00bcd4, 0 0 20px #00bcd4, 0 0 40px #00bcd4"; // Glowing effect
  } else if (currentPhase === "Accusation") {
    els.phase.style.color = "white";
    els.phase.textContent += " 🫵";
    els.phase.style.textShadow =
      "0 0 5px #ffb74d, 0 0 10px #ff9800, 0 0 20px #ff9800, 0 0 40px #ff9800";
  } else if (currentPhase === "Lynch_Vote") {
    els.phase.textContent += " 🔥";
    els.phase.style.color = "white";
    els.phase.style.textShadow =
      "0 0 5px #ff5252, 0 0 10px #ff1744, 0 0 20px #d50000, 0 0 40px #b71c1c";
  }

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
        document.getElementById("overlay-title").innerText = "Done";
        document.getElementById("overlay-title").style.color = "#4caf50";
        document.getElementById("overlay-msg").innerText = "Action Recorded.";
        document.getElementById("overlay-actions").innerHTML =
          "<p>Please pass the device...</p>";
        document.getElementById("overlay-action-area").innerHTML = "";

              setTimeout(() => requestGameSync(), 2000);
        */
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
  const msg = `🔮 Your vision reveals that <strong>${data.name}</strong> is a <strong>${data.role}</strong>.`;
  logMessage(msg, true);
  lastSeerResult = msg;
  // In Standard UI, renderActionUI handles displaying this if active.
  els.action.innerHTML = `<p>${msg}</p>`;
});

socket.on("cupid_info", (data) => {
  logMessage(data.message, true);
});

socket.on("werewolf_team_info", (data) => {
  const msg = data.teammates.length
    ? `You are a Werewolf 🐺 Your fellow Werewolves are: <strong>${data.teammates.join(", ")}</strong>.`
    : "You are the lone Werewolf 🐺";
  logMessage(msg, true);
});

socket.on("lynch_vote_result", (data) => {
  let msg =
    data.message +
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

  els.phase.textContent = "Lynch Vote";
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
  alert(`New game code set.\nYou will now be returned to the login screen.`);
  window.location.href = "/";
});

socket.on("error", (data) => alert("Error: " + data.message));

function updatePlayerListView(accusationCounts = {}) {
  els.playerList.innerHTML = "";
  const livingIds = livingPlayers.map((p) => p.id);
  allPlayers.forEach((p) => {
    const li = document.createElement("li");

    const isMe = p.id === myPlayerId;
    const nameDisplay = isMe ? `${p.name} (You)` : p.name;

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
