// Version 5.1.0
let translations = {};
const currentLang = window.userLang || "en";

// 1. Load the appropriate JSON file
async function loadTranslations() {
  try {
    const response = await fetch(`/static/${currentLang}.json`);
    translations = await response.json();
    console.log(`Loaded translations for ${currentLang}`);
    updateStaticUIText(); // Update buttons immediately
    // If roles are already loaded, re-render them with new language
    if (document.getElementById("roles-grid").children.length > 1) {
      loadRoles();
    }
  } catch (err) {
    console.error("Failed to load translations:", err);
  }
}
loadTranslations();

// 2. Translator Helper
function t(key, defaultText) {
  // Handle object input {key: "...", variables: {...}}
  if (typeof key === "object" && key.key) {
    // Reuse string logic
    let text = t(key.key, defaultText);
    if (key.variables) {
      for (const [k, v] of Object.entries(key.variables)) {
        text = text.replace(`{${k}}`, v);
      }
    }
    return text;
  }

  if (!key) return defaultText || "";
  const keys = key.split(".");
  let text = translations;
  for (let k of keys) {
    text = text ? text[k] : null;
  }
  return text || defaultText || key;
}

// 3. Update Static HTML
function updateStaticUIText() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const text = t(key);
    if (text && text !== key) {
      el.innerText = text;
    }
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    const text = t(key);
    if (text && text !== key) {
      el.placeholder = text;
    }
  });

  // Update Placeholders
  if (translations.ui && translations.ui.lobby) {
    const chatInput = document.getElementById("chat-input");
    if (chatInput)
      chatInput.placeholder = translations.ui.lobby.chat_placeholder;
  }
}

const PHASE_LOBBY = "Lobby";
const PHASE_NIGHT = "Night";
const PHASE_ACCUSATION = "Accusation";
const PHASE_LYNCH = "Lynch_Vote";
const PHASE_GAME_OVER = "Game_Over";

// Role Keys
const ROLE_ALPHA_WEREWOLF = "Alpha_Werewolf";
const ROLE_BACKLASH_WEREWOLF = "Backlash_Werewolf";
const ROLE_BODYGUARD = "Bodyguard";
const ROLE_CUPID = "Cupid";
const ROLE_DEMENTED_VILLAGER = "Demented_Villager";
const ROLE_FOOL = "Fool";
const ROLE_HONEYPOT = "Honeypot";
const ROLE_HUNTER = "Hunter";
const ROLE_LAWYER = "Lawyer";
const ROLE_MARTYR = "Martyr";
const ROLE_MAYOR = "Mayor";
const ROLE_MONSTER = "Monster";
const ROLE_PROSTITUTE = "Prostitute";
const ROLE_RANDOM_SEER = "Random_Seer";
const ROLE_REVEALER = "Revealer";
const ROLE_SEER = "Seer";
const ROLE_SERIAL_KILLER = "Serial_Killer";
const ROLE_SORCERER = "Sorcerer";
const ROLE_TOUGH_VILLAGER = "Tough_Villager";
const ROLE_TOUGH_WEREWOLF = "Tough_Werewolf";
const ROLE_VILLAGER = "Villager";
const ROLE_WEREWOLF = "Werewolf";
const ROLE_WILD_CHILD = "Wild_Child";
const ROLE_WITCH = "Witch";

// ROLE COUNT Calculation:
// CONSTANTS (Must match your Python constants)
const SPECIAL_WEREWOLVES = [
  "Backlash_Werewolf",
  "Tough_Werewolf",
  "Alpha_Werewolf",
];

const socket = io();
// Ensure backend renders 'player_id' into the template
let isPlayerAdmin = false;

// Elements
const chatMessages = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSendBtn = document.getElementById("chat-send-btn");
const disableTimersCheckbox = document.getElementById(
  "disable-timers-checkbox",
);
const timerOptionsDiv = document.getElementById("timer-options");
const setTimersButton = document.getElementById("set-timers-btn");

// --- 1. Role Loading ---
// [ADDED] Global storage for role metadata (populated from server)
let ROLE_DATA = {};

// --- 1. Role Loading ---
async function loadRoles() {
  try {
    const response = await fetch("/get_roles");
    const roles = await response.json();
    const container = document.getElementById("roles-grid"); // Target the grid directly

    container.innerHTML = ""; // Clear "Loading roles..." text

    roles.forEach((role) => {
      // The server now sends: short, long, rating, color
      const key = role.name_key.replace(/_/g, " ");

      let roleName = key;
      let roleShort = role.short;
      let roleLong = role.long;

      if (translations.roles && translations.roles[role.name_key]) {
        const rTrans = translations.roles[role.name_key];
        roleName = rTrans.name || roleName;
        roleShort = rTrans.short || roleShort;
        roleLong = rTrans.long || roleLong;
      }

      ROLE_DATA[key] = {
        short: roleShort,
        long: roleLong,
        rating: role.rating,
        color: role.color,
        team: role.team,
        priority: role.priority || 0,
        displayName: roleName,
      };

      // 2. Create the Tile
      const tile = document.createElement("div");
      tile.className = "role-tile";

      // [CHANGED] Use role object directly (it has the color now)
      tile.style.setProperty("--role-color", role.color || "#ddd");

      // 3. Create Checkbox
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "selected_roles";
      checkbox.value = role.name_key;
      checkbox.classList.add("role-checkbox");

      // Set default checks
      if (serverRoles !== null) {
        // If we already heard from the server (Rematch), use that
        if (serverRoles.includes(role.name_key)) {
          checkbox.checked = true;
          tile.classList.add("selected");
        }
      } else {
        // Fresh Load: Use Defaults
        const defaultRoles = [ROLE_VILLAGER, ROLE_WEREWOLF, ROLE_SEER];
        if (defaultRoles.includes(role.name_key)) {
          checkbox.checked = true;
          tile.classList.add("selected");
        }
      }

      // Add Event Listener for Checkbox Logic
      checkbox.addEventListener("change", (e) => {
        // Toggle visual style
        if (e.target.checked) tile.classList.add("selected");
        else tile.classList.remove("selected");

        // Admin socket update
        if (isPlayerAdmin) {
          const selected = Array.from(
            document.querySelectorAll(".role-checkbox:checked"),
          ).map((cb) => cb.value);
          socket.emit("admin_update_roles", { roles: selected });
        }
        updateRoleSummary();
      });

      // 4. Build Tile Content
      const title = document.createElement("h3");
      title.innerText = roleName;

      // Short Desc
      const shortDesc = document.createElement("p");
      shortDesc.className = "role-short-desc";
      shortDesc.innerText = roleShort;

      // Tooltip
      const tooltip = document.createElement("div");
      tooltip.className = "role-tooltip";
      const teamKey = role.team;
      const translatedTeam = t(`teams.${teamKey}`, teamKey.replace(/_/g, " "));

      tooltip.innerHTML = `
                ${roleLong}
                <span class="tooltip-rating" style="color: ${role.color}">
                    <span style="float: left; font-weight: normal; ">
                        ${translatedTeam}
                    </span>
                    <span style="color: #666; font-size: 0.9em;">Prio: ${role.priority || 0}</span>

                    ${role.rating}
                </span>
            `;

      // 5. Assemble
      tile.appendChild(checkbox);
      tile.appendChild(title);
      tile.appendChild(shortDesc);
      tile.appendChild(tooltip);

      // Make the whole tile clickable to toggle checkbox
      tile.addEventListener("click", (e) => {
        // Prevent infinite loop if clicking the checkbox itself
        if (e.target !== checkbox) {
          checkbox.checked = !checkbox.checked;
          checkbox.dispatchEvent(new Event("change"));
        }
      });

      container.appendChild(tile);
    });

    updateRoleSummary();
  } catch (err) {
    console.error("Failed to load roles", err);
    document.getElementById("roles-grid").innerHTML =
      '<p style="color:crimson">Error loading roles</p>';
  }
}
// --- 2. Socket Events ---

socket.on("connect", () => {
  loadRoles();
});

let serverRoles = null;

// Merged sync logic: Updates checkbox state AND summary
socket.on("sync_roles", function (data) {
  console.log("Received roles from server:", data.roles);
  serverRoles = data.roles;

  const checkboxes = document.querySelectorAll(".role-checkbox");
  if (checkboxes.length > 0) {
    checkboxes.forEach((cb) => {
      cb.checked = data.roles.includes(cb.value);
      // Find parent tile and update class
      if (cb.checked) cb.closest(".role-tile").classList.add("selected");
      else cb.closest(".role-tile").classList.remove("selected");
    });
    updateRoleSummary();
  }
});

// NEW: Restore Lobby Settings (Checkboxes & Timers)
socket.on("sync_settings", (settings) => {
  if (!settings || Object.keys(settings).length === 0) return;

  console.log("Restoring settings:", settings);

  // 1. Restore Mode Checkboxes
  const isPnP = settings.mode === "pass_and_play";
  document.getElementById("mode-pass-and-play").checked = isPnP;

  // Toggle Add Player Button
  const addPlayerBtn = document.getElementById("add-player-btn");
  if (addPlayerBtn) {
    addPlayerBtn.style.display = isPnP ? "inline-block" : "none";
  }

  // 2. Restore Solo Win (Logic Inverted)
  // If "continues" is TRUE, "ends-game" checkbox must be FALSE
  // If "continues" is FALSE, "ends-game" checkbox must be TRUE
  const soloEndsGameCb = document.getElementById("mode-solo-ends-game");
  if (soloEndsGameCb) {
    if (settings.solo_win_continues === true) {
      soloEndsGameCb.checked = false;
    } else if (settings.solo_win_continues === false) {
      soloEndsGameCb.checked = true;
    }
  }

  // 3. Restore Ghost Mode
  const ghostCb = document.getElementById("ghost-mode-checkbox");
  if (ghostCb) {
    ghostCb.checked = !!settings.ghost_mode;
  }

  // 4. Restore Timers
  if (settings.timers) {
    const t = settings.timers;

    // Checkbox
    const disableBox = document.getElementById("disable-timers-checkbox");
    if (disableBox) {
      disableBox.checked = !!t.timers_disabled;
      // Trigger change event to hide/show options
      disableBox.dispatchEvent(new Event("change"));
    }

    // Inputs
    if (t.night) document.getElementById("night-timer-input").value = t.night;
    if (t.accusation)
      document.getElementById("accusation-timer-input").value = t.accusation;
    if (t.lynch_vote)
      document.getElementById("lynch-vote-timer-input").value = t.lynch_vote;
  }
});

// Merged player list update: Handles list, admin check, AND summary update
socket.on("update_player_list", (data) => {
  const playerList = document.getElementById("player-list");
  const adminPanel = document.getElementById("admin-panel");
  const startGameBtn = document.getElementById("start-game-btn");
  const gameCodeArea = document.getElementById("game-code-area");

  playerList.innerHTML = "";
  const me = data.players.find((p) => p.id === currentPlayerId);

  // Update Admin Status
  if (me && me.is_admin) {
    isPlayerAdmin = true;
    adminPanel.style.display = "block";
    gameCodeArea.style.display = "block";
    document.getElementById("game-code-display").textContent = data.game_code;
  } else {
    isPlayerAdmin = false;
    adminPanel.style.display = "none";
    gameCodeArea.style.display = "none";
  }
  data.players.forEach((player) => {
    const li = document.createElement("li");
    li.textContent = player.name;
    if (player.id === currentPlayerId) {
      li.classList.add("you");
      li.textContent += " " + t("ui.lobby.you_suffix", "(You)");
    }
    if (player.is_admin) li.textContent += " 👑";

    if (isPlayerAdmin && player.id !== currentPlayerId) {
      const adminBtn = document.createElement("span");
      adminBtn.textContent = "🪄";
      adminBtn.className = "exclude-btn"; // Reuse style or add new class
      adminBtn.style.marginRight = "5px";
      adminBtn.title = "Make Admin";
      adminBtn.onclick = (e) => {
        e.stopPropagation();
        if (confirm(`Make ${player.name} the Admin?`)) {
          socket.emit("admin_transfer_admin", { target_id: player.id });
        }
      };
      li.appendChild(adminBtn);

      const excludeBtn = document.createElement("span");
      excludeBtn.textContent = t("ui.lobby.exclude_btn", "Exclude");
      excludeBtn.className = "exclude-btn";
      excludeBtn.dataset.playerId = player.id;
      li.appendChild(excludeBtn);
    }
    playerList.appendChild(li);
  });

  // Enable start button if enough players
  startGameBtn.disabled = data.players.length < 4;
  const warningEl = document.getElementById("min-players-warning");
  if (warningEl) {
    warningEl.style.display = startGameBtn.disabled ? "block" : "none";
  }
  setChatMode(data.admin_only_chat);

  // Recalculate roles based on new player count
  updateRoleSummary();
});

socket.on("game_started", () => {
  window.location.href = "/game";
});

socket.on("force_kick", () => {
  alert("You have been dropped from the lobby.");
  window.location.href = "/";
});

socket.on("admin_timers_updated", (data) => {
  const timers = data.timers;
  if (timers.night)
    document.getElementById("night-timer-input").value = timers.night;
  if (timers.accusation)
    document.getElementById("accusation-timer-input").value = timers.accusation;
  if (timers.lynch_vote)
    document.getElementById("lynch-vote-timer-input").value = timers.lynch_vote;
});

socket.on("force_relogin", (data) => {
  alert("New code set. Re-login required.");
  window.location.href = "/";
});

socket.on("message", (data) => alert(data.text));

socket.on("error", (data) => alert("Error: " + data.message));

socket.on("new_message", (data) => {
  if (data.channel === "lobby" || data.channel === "announcement") {
    const messageEl = document.createElement("div");
    messageEl.innerHTML = DOMPurify.sanitize(data.text);
    if (data.channel === "announcement")
      messageEl.classList.add("announcement");
    chatMessages.prepend(messageEl);
  }
});

socket.on("chat_mode_update", (data) => {
  setChatMode(data.admin_only);
});

// --- 3. UI Event Listeners ---

document.getElementById("start-game-btn").onclick = () => {
  // A. Get Roles
  const checkboxes = document.querySelectorAll(
    'input[name="selected_roles"]:checked',
  );
  const selectedRoles = Array.from(checkboxes).map((cb) => cb.value);

  // B. Get Mode
  const passAndPlay = document.getElementById("mode-pass-and-play").checked;
  const soloEndsGameCheckbox = document.getElementById("mode-solo-ends-game");
  const soloContinues = soloEndsGameCheckbox
    ? !soloEndsGameCheckbox.checked
    : false;

  // Handle Ghost Mode (Safe check in case element is missing)
  const ghostCheckbox = document.getElementById("ghost-mode-checkbox");
  const ghostMode = ghostCheckbox ? ghostCheckbox.checked : false;

  // C. Get Timers
  const timers = {
    timers_disabled: disableTimersCheckbox.checked,
    night: document.getElementById("night-timer-input").value,
    accusation: document.getElementById("accusation-timer-input").value,
    lynch_vote: document.getElementById("lynch-vote-timer-input").value,
  };

  socket.emit("start_game", {
    roles: selectedRoles,
    settings: {
      mode: passAndPlay ? "pass_and_play" : "standard",
      solo_win_continues: soloContinues,
      ghost_mode: ghostMode,
      timers: timers,
    },
  });
};

// Add Player Button Logic (Pass-and-Play)
document.getElementById("add-player-btn").onclick = () => {
  window.location.href = "/?add_player=1";
};

// --- Random Roles Logic ---
function selectRandomRoles() {
  console.log("Random Roles: Button clicked.");

  try {
    // 1. Determine Player Count
    const playerList = document.getElementById("player-list");
    let numPlayers = playerList ? playerList.children.length : 0;

    // Fallback for testing: If 0 or 1 players, pretend there are 5
    if (numPlayers < 4) {
      console.log(
        "Player count low (" +
          numPlayers +
          "), defaulting to 5 for calculation.",
      );
      numPlayers = 4;
    }

    // 2. Get all checkboxes
    const checkboxes = Array.from(document.querySelectorAll(".role-checkbox"));
    if (checkboxes.length === 0) {
      alert("Roles are not loaded yet. Please wait.");
      return;
    }

    let bestSet = [];
    let minDiff = Infinity; // Track the closest we get to 0 balance

    // 3. Monte Carlo Simulation: Try 100 combinations
    const maxAttempts = 100;

    for (let i = 0; i < maxAttempts; i++) {
      // A. Pick random count (Between 2 and numPlayers)
      const maxPick = Math.min(checkboxes.length, numPlayers);
      const minPick = 2;
      const countToPick =
        Math.floor(Math.random() * (maxPick - minPick + 1)) + minPick;

      // B. Shuffle and Slice
      const shuffled = checkboxes.slice().sort(() => 0.5 - Math.random());
      const currentSet = shuffled.slice(0, countToPick);

      // C. Calculate Rating Sum
      let totalRating = 0;
      currentSet.forEach((cb) => {
        const key = cb.value.replace(/_/g, " ");
        let rating = 0;
        if (typeof ROLE_DATA !== "undefined" && ROLE_DATA[key]) {
          rating = parseFloat(ROLE_DATA[key].rating);
        }
        if (isNaN(rating)) rating = 0;
        totalRating += rating;
      });

      // D. Check Balance (-0.5 to +0.5)
      const diff = Math.abs(totalRating);

      if (diff <= 0.5) {
        bestSet = currentSet;
        minDiff = diff;
        break;
      }

      if (diff < minDiff) {
        minDiff = diff;
        bestSet = currentSet;
      }
    }

    // 4. Apply the Best Selection Found
    if (bestSet.length > 0) {
      // Uncheck ALL first
      checkboxes.forEach((cb) => {
        cb.checked = false;
        if (cb.closest(".role-tile"))
          cb.closest(".role-tile").classList.remove("selected");
      });

      // Check winners
      bestSet.forEach((cb) => {
        cb.checked = true;
        if (cb.closest(".role-tile"))
          cb.closest(".role-tile").classList.add("selected");
      });

      updateRoleSummary();
      if (typeof isPlayerAdmin !== "undefined" && isPlayerAdmin) {
        const rolesPayload = bestSet.map((cb) => cb.value);
        socket.emit("admin_update_roles", { roles: rolesPayload });
      }
      console.log(
        `Roles randomized. Count: ${bestSet.length}. Balance: ${minDiff.toFixed(1)}`,
      );
    } else {
      alert("Could not generate a valid role set.");
    }
  } catch (err) {
    console.error("Error in selectRandomRoles:", err);
    alert("An error occurred generating roles. Check console.");
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (message) {
    socket.emit("send_message", { message: message });
    chatInput.value = "";
  }
});

const settingsContainer = document.querySelector(".settings-row");

if (settingsContainer) {
  settingsContainer.addEventListener("change", (e) => {
    const target = e.target;

    // Ignore clicks that aren't inputs
    if (target.tagName !== "INPUT" && target.tagName !== "SELECT") return;

    switch (target.id) {
      case "mode-pass-and-play":
        if (target.checked) {
          const timerBox = document.getElementById("disable-timers-checkbox");
          if (timerBox && !timerBox.checked) {
            timerBox.checked = true;
            // Trigger change event so the backend gets the timer update too
            timerBox.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
        socket.emit("admin_update_settings", {
          mode: target.checked ? "pass_and_play" : "standard",
        });
        break;

      case "mode-solo-ends-game":
        // Logic: Checked = "Ends Game", so solo_win_continues is FALSE
        socket.emit("admin_update_settings", {
          solo_win_continues: !target.checked,
        });
        break;

      case "ghost-mode-checkbox":
        socket.emit("admin_update_settings", {
          ghost_mode: target.checked,
        });
        break;

      case "disable-timers-checkbox":
        // Toggle UI visibility immediately
        const timerOptionsDiv = document.getElementById("timer-options");
        const setTimersButton = document.getElementById("set-timers-btn");
        if (timerOptionsDiv)
          timerOptionsDiv.style.display = target.checked ? "none" : "block";
        if (setTimersButton)
          setTimersButton.style.display = target.checked ? "none" : "block";

        // Send to server
        socket.emit("admin_set_timers", {
          timers_disabled: target.checked,
        });
        break;
    }
  });
}

// Admin Utils
document.getElementById("set-code-btn").onclick = () => {
  const newCode = document
    .getElementById("new-game-code-input")
    .value.trim()
    .toUpperCase();
  if (newCode) socket.emit("admin_set_new_code", { new_code: newCode });
  else alert("Please enter a new code.");
};

document.getElementById("toggle-chat-btn").onclick = () => {
  socket.emit("admin_toggle_chat");
};

document.getElementById("set-timers-btn").onclick = () => {
  socket.emit("admin_set_timers", {
    timers_disabled: document.getElementById("disable-timers-checkbox").checked,
    night: document.getElementById("night-timer-input").value,
    accusation: document.getElementById("accusation-timer-input").value,
    lynch_vote: document.getElementById("lynch-vote-timer-input").value,
  });
};

// Handle Exclude Click
document.getElementById("player-list").addEventListener("click", function (e) {
  if (e.target && e.target.className === "exclude-btn") {
    excludePlayer(e.target.dataset.playerId);
  }
});

// --- 4. Helpers & Utilities ---

function excludePlayer(playerId) {
  if (confirm("Exclude this player?")) {
    socket.emit("admin_exclude_player", { player_id: playerId });
  }
}

function setChatMode(isAdminOnly) {
  if (isAdminOnly && !isPlayerAdmin) {
    chatSendBtn.disabled = true;
    chatInput.placeholder = t("ui.lobby.chat_restricted", "Chat is admin-only");
  } else {
    chatSendBtn.disabled = false;
    chatInput.placeholder = t("ui.lobby.chat_placeholder", "Type a message...");
  }
}

function updateRoleSummary() {
  const playerList = document.getElementById("player-list");
  const numPlayers = playerList ? playerList.children.length : 0;
  const summaryElement = document.getElementById("role-summary-text");
  const startGameBtn = document.getElementById("start-game-btn");

  // 1. Basic Check
  if (numPlayers < 1) {
    summaryElement.textContent = t(
      "ui.lobby.waiting_text",
      "Waiting for players...",
    );
    summaryElement.style.color = "darkgray";
    return;
  }

  // 2. Get Selected Roles
  const checkboxes = document.querySelectorAll(".role-checkbox:checked");
  let selectedSpecials = [];
  checkboxes.forEach((cb) => selectedSpecials.push(cb.value));

  // 3. Calculate Required Wolf Slots
  let totalWolvesAllowed = 0;
  if (numPlayers >= 4 && numPlayers <= 6) totalWolvesAllowed = 1;
  else if (numPlayers >= 7 && numPlayers <= 8) totalWolvesAllowed = 2;
  else if (numPlayers >= 9 && numPlayers <= 11) totalWolvesAllowed = 3;
  else if (numPlayers >= 12 && numPlayers <= 16) totalWolvesAllowed = 4;
  else totalWolvesAllowed = Math.max(1, Math.floor(numPlayers * 0.25));

  // Count selected wolves
  let wolvesInSelection = 0;
  selectedSpecials.forEach((role) => {
    if (SPECIAL_WEREWOLVES.includes(role) || role === ROLE_WEREWOLF) {
      wolvesInSelection++;
    }
  });

  let extraWolvesNeeded = Math.max(0, totalWolvesAllowed - wolvesInSelection);
  const totalSlotsNeeded = selectedSpecials.length + extraWolvesNeeded;

  // Validation
  if (totalSlotsNeeded > numPlayers) {
    const diff = totalSlotsNeeded - numPlayers;

    let warningMsg = t(
      "ui.lobby.roles_warning",
      "⚠️ Too many roles selected! Deselect {count} role(s).",
    );
    warningMsg = warningMsg.replace("{count}", diff);

    summaryElement.innerHTML = `<strong>${warningMsg}</strong>`;
    summaryElement.style.color = "salmon"; // Red Warning
    startGameBtn.disabled = true; // Prevent starting
    return;
  }

  // Build Display List
  startGameBtn.disabled = numPlayers < 4;
  summaryElement.style.color = "gainsboro";

  let finalRoleCounts = {};

  // A. Add selections
  selectedSpecials.forEach((role) => {
    finalRoleCounts[role] = (finalRoleCounts[role] || 0) + 1;
  });

  // B. Add mandatory wolves
  if (extraWolvesNeeded > 0) {
    finalRoleCounts[ROLE_WEREWOLF] =
      (finalRoleCounts[ROLE_WEREWOLF] || 0) + extraWolvesNeeded;
  }

  // C. Fill remainder with Villagers
  let currentCount = 0;
  for (let r in finalRoleCounts) currentCount += finalRoleCounts[r];

  let villagersNeeded = Math.max(0, numPlayers - currentCount);
  if (villagersNeeded > 0) {
    finalRoleCounts[ROLE_VILLAGER] =
      (finalRoleCounts[ROLE_VILLAGER] || 0) + villagersNeeded;
  }

  // D. Format Text
  let outputParts = [];
  for (const [role, count] of Object.entries(finalRoleCounts)) {
    const key = role.replace(/_/g, " ");
    let displayRole = ROLE_DATA[key] ? ROLE_DATA[key].displayName : key;
    if (count > 1) displayRole += "s";
    if (count > 0)
      outputParts.push(count === 1 ? displayRole : `${count} ${displayRole}`);
  }
  summaryElement.textContent = outputParts.join(", ");
}
