"""
app.py
Version: 4.4.0
"""
from collections import Counter
from dotenv import load_dotenv, find_dotenv
import os
import time
import uuid
from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    send_from_directory,
    jsonify
)
from flask_socketio import SocketIO, join_room, leave_room, emit
from game_engine import Game
from roles import AVAILABLE_ROLES

# --- App Initialization ---
load_dotenv(find_dotenv(filename=".env.werewolves"))

app = Flask(__name__)
# IMPORTANT: In production, this MUST be set as an environment variable.
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY", "omiunhbybt7vr6c53wz3523c2r445ybF4y6jmo8o8p"
)

# --- Global State ---
game_instance = Game("main_game")

# Configure CORS for Socket.IO from environment variables
# This is crucial for security in a production environment.
origins = os.environ.get("CORS_ALLOWED_ORIGINS")
socketio = SocketIO(
    app,
    cors_allowed_origins=origins.split(",") if origins else ["http://127.0.0.1:5000"],
)

if origins:
    print(f"+++> .env FILE FOUND")
else:
    print(f"---> .env FILE NOT FOUND")

# --- Game State ---
game = {
    "players": {},  # dictionary mapping player_id (UUID string) to Player objects
    "game_state": "waiting",  # started night accusation_phase lynch_vote_phase ended
    #    "phase_start_time": None,  # timestamp for the current phase
    #    "game_over_data": None,  # Stores the final game over payload
    #"timers_disabled": False,  # Admin can disable timers for manual progression
    #"players_ready_for_game": set(),  # ready player_ids
    "game_code": "W",
    "admin_sid": None,
    "admin_only_chat": False,
    #"night_wolf_choices": {},  # dictionary wolf player_ids to chosen target_id kill
    #"night_seer_choice": None,
    #"seer_investigated": False,
    #"accusations": {},  # dictionary player_ids to accused target_id for lynch_vote
    #"accusation_restarts": 0,
    #"end_day_votes": set(),  # set player_ids
    #"lynch_target_id": None,
    #"lynch_votes": {},  # dictionary player_ids to yes/no
    #"accusation_timer": None,
    #"lynch_vote_timer": None,
    #"night_timer": None,
    # dictionary storing duration (in seconds) for each game phase timer
    #"timer_durations": {"night": 90, "accusation": 90, "lynch_vote": 60},
    # A unique, incrementing ID for each timer instance to prevent old timers from firing.
    #"current_timer_id": 0,
    #"rematch_votes": set(),  # set player_ids for game_over rematch
}

class PlayerWrapper:
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.is_admin = False

# --- Player Class ---
#class Player:
#    def __init__(self, username, sid):
#        # unique, persistent identifier for the player, stored in session
#        self.id = session.get("player_id")
#        self.username = username
#        # player's current SocketIO session ID. Changes on reconnect
#        self.sid = sid
#        self.role = None  # 'villager', 'wolf', 'seer'
#        self.is_alive = True
#        self.is_admin = False


# --- Helper Functions ---
def get_player_by_sid(sid):
    for player_id, p in game["players"].items():
        if p.sid == sid:
            return player_id, p
    return None, None


def get_living_players(roles=None):
    living = [p for p in game["players"].values() if p.is_alive]
    if roles:
        if isinstance(roles, str):
            roles = [roles]
        return [p for p in living if p.role in roles]
    return living


def log_and_emit(message):
    print(message)
    socketio.emit("log_message", {"text": message}, to=game["game_code"])

def broadcast_player_list():
    player_list = []
    for pid, conn in game["players"].items():
        is_alive = True
        # Check Engine if game is running
        if pid in game_instance.players:
            is_alive = game_instance.players[pid].is_alive

        player_list.append({
            "id": pid, "username": conn.username,
            "is_admin": conn.is_admin, "is_alive": is_alive
        })

    socketio.emit("update_player_list", {
        "players": player_list,
        "game_code": game["game_code"],
        "admin_only_chat": game["admin_only_chat"]
    }, to=game["game_code"])

def broadcast_game_state():
    """Syncs the FULL Engine state to all clients."""
    # 1. Public Data
    print("DEBUG: Starting broadcast_game_state...")
    try:
        all_players = [{"id": p.id, "username": p.name} for p in game_instance.players.values()]
    except Exception as e:
        print(f"DEBUG ERROR in Public Data: {e}")
        return

    # 2. Timer Calculation
    remaining = 0
    if game_instance.phase_start_time and not game_instance.timers_disabled:
        # Map Engine Phase to Config Key
        p_map = {"NIGHT": "night", "ACCUSATION_PHASE": "accusation", "LYNCH_VOTE_PHASE": "lynch_vote"}
        key = p_map.get(game_instance.phase)
        if key and key in game_instance.timer_durations:
            elapsed = time.time() - game_instance.phase_start_time
            remaining = max(0, game_instance.timer_durations[key] - elapsed)

    print(f"DEBUG: Timer calculated: {remaining}s")

    # 3. Private Data (Sent individually)
    # todo: should we do this for all player, or only to (specific player)
    for pid, conn in game["players"].items():
        if not conn.sid:
            print(f"DEBUG: Skipping {conn.username} (No SID)")
            continue

        engine_p = game_instance.players.get(pid)
        role_str, is_alive = "villager", True

        if engine_p:
            is_alive = engine_p.is_alive
            if engine_p.role:
                # Map "role_werewolf" -> "wolf" for frontend legacy support
                raw = engine_p.role.name_key.replace("role_", "")
                role_str = "wolf" if raw == "werewolf" else raw
        else:
            print(f"DEBUG WARNING: Player {conn.username} ({pid}) not found in Engine!")

        payload = {
            "phase": game_instance.phase.lower(),
            "your_role": role_str,
            "mode": game_instance.mode, # Standard or pass_and_play
            "is_alive": is_alive,
            "is_admin": conn.is_admin,
            "living_players": [{"id": p.id, "username": p.name} for p in game_instance.get_living_players()],
            "all_players": all_players,
            "duration": remaining,
            "admin_only_chat": game["admin_only_chat"],
            "timers_disabled": game_instance.timers_disabled,
            "game_over_data": game_instance.game_over_data
        }

        print(f"DEBUG: Sending to {conn.username}: {payload}") # Uncomment if needed
        socketio.emit("game_state_sync", payload, to=conn.sid)

    print("DEBUG: Broadcast complete.")

# --- Timer System ---

def start_phase_timer(phase_name):
    """Starts a background timer for the current phase."""
    if game_instance.timers_disabled: return

    # Map Phase to Duration Key
    p_map = {"NIGHT": "night", "ACCUSATION_PHASE": "accusation", "LYNCH_VOTE_PHASE": "lynch_vote"}
    key = p_map.get(phase_name)

    if key and key in game_instance.timer_durations:
        duration = game_instance.timer_durations[key]
        tid = game_instance.current_timer_id
        socketio.start_background_task(target=timer_task, phase=phase_name, duration=duration, tid=tid)

def timer_task(phase, duration, tid):
    socketio.sleep(duration)
    with app.app_context():
        # Validate Timer (Check if phase changed or timer reset)
        if game_instance.phase == phase and tid == game_instance.current_timer_id:
            log_and_emit(f"Timer expired for {phase}.")

            if phase == "NIGHT":
                resolve_night()
            elif phase == "ACCUSATION_PHASE":
                perform_tally_accusations()
            elif phase == "LYNCH_VOTE_PHASE":
                resolve_lynch()

def full_game_reset(new_code="W", admin_to_keep=None):
    global game
    print(f"Admin has reset the game with a new code.")
    game = {
        "players": {},
        "game_state": "waiting",
        "phase_start_time": None,
        "game_over_data": None,
        "timers_disabled": False,
        "players_ready_for_game": set(),
        "admin_sid": None,
        "game_code": new_code,
        "admin_only_chat": False,
        "night_wolf_choices": {},
        "night_seer_choice": None,
        "seer_investigated": False,
        "accusations": {},
        "accusation_restarts": 0,
        "end_day_votes": set(),
        "lynch_target_id": None,
        "lynch_votes": {},
        "accusation_timer": None,
        "lynch_vote_timer": None,
        "night_timer": None,
        "timer_durations": {"night": 90, "accusation": 90, "lynch_vote": 60},
        "current_timer_id": 0,
        "rematch_votes": set(),
    }
    if admin_to_keep:
        game["players"] = {admin_to_keep.id: admin_to_keep}
        game["admin_sid"] = admin_to_keep.sid


# --- Game Logic ---
# Resets game to initial state, clearing temporary data. does NOT remove players.
def reset_game_state():
    log_and_emit("A majority voted for a new match. Get Ready!")
    game["game_state"] = "waiting"
    game["phase_start_time"] = None
    game["game_over_data"] = None
    game["timers_disabled"] = False
    game["night_wolf_choices"] = {}
    game["night_seer_choice"] = None
    game["seer_investigated"] = False
    game["accusations"] = {}
    game["end_day_votes"] = set()
    game["lynch_target_id"] = None
    game["lynch_votes"] = {}
    game["rematch_votes"] = set()
    game["admin_only_chat"] = False  # Also reset chat mode

    # Reset individual player states
    for player in game["players"].values():
        player.role = None
        player.is_alive = True


def assign_roles():
    player_ids = list(game["players"].keys())
    random.shuffle(player_ids)
    num_players = len(player_ids)
    if 4 <= num_players <= 6:
        num_wolves = 1
    elif 7 <= num_players <= 8:
        num_wolves = 2
    elif 9 <= num_players <= 11:
        num_wolves = 3
    elif 12 <= num_players <= 16:
        num_wolves = 4
    else:
        num_wolves = int(num_players * 0.25)
    num_seer = 1 if num_players >= 4 else 0
    for i, player_id in enumerate(player_ids):
        player = game["players"][player_id]
        player.is_alive = True
        if i < num_wolves:
            player.role = "wolf"
        elif i < num_wolves + num_seer:
            player.role = "seer"
        else:
            player.role = "villager"
    log_and_emit("Roles have been assigned.")


# Check for win condition. Calculates number living players for
# each faction and checks win condition. If a winner found, changes game state to "ended", and emits 'game_over' event.
#def check_win_conditions():
#    # Don't check for wins if the game isn't in a state where players can die.
#    log_and_emit(f"checking win conditions, current game_state: {game['game_state']}")
#    if game["game_state"] in [
#        "waiting",
#        "ended",
#    ]:
#        return False
#
#    num_living_wolves = len(get_living_players("wolf"))
#    num_living_non_wolves = len(get_living_players()) - num_living_wolves
#
#    winner = None
#    reason = ""
#
#    # Villager Win: No wolves left alive.
#    if num_living_wolves == 0 and num_living_non_wolves > 0:
#        winner = "Villagers"
#        reason = "All of the wolves have been eradicated."
#    # Wolf Win: number of wolves >= non-wolves.
#    elif num_living_wolves >= num_living_non_wolves and num_living_wolves > 0:
#        winner = "Wolves"
#        reason = "The wolves have taken over the village."
#
#    if winner:
#        game["game_state"] = "ended"
#        game["admin_only_chat"] = False  # reset chat mode
#        socketio.emit(
#            "chat_mode_update",
#            {"admin_only_chat": game["admin_only_chat"]},
#            to=game["game_code"],
#        )
#
#        final_player_states = [
#            {"username": p.username, "role": p.role, "is_alive": p.is_alive}
#            for p in game["players"].values()
#        ]
#        payload = {
#            "winning_team": winner,
#            "reason": reason,
#            "final_player_states": final_player_states,
#        }
#        game["game_over_data"] = payload  # Store results for refreshes
#        log_and_emit(f"Game over! The {winner} have won! {reason}")
#        socketio.sleep(6)
#        socketio.emit("game_over", payload, to=game["game_code"])
#
#        return True  # Game is over
#    return False  # Game continues


# need to fix/reorganize phase Initialization resets
#def start_new_phase(phase_name):
#    log_and_emit(f">>> Starting New Phase: {phase_name.upper()} <<<")
#    if game["game_state"] != phase_name or phase_name == "accusation_phase":
#        game["current_timer_id"] += 1
#    current_timer_id = game["current_timer_id"]
#
#    game["game_state"] = phase_name
#    game["phase_start_time"] = time.time()  # Record when the phase starts
#    game["end_day_votes"] = set()
#    game["lynch_target_id"], game["lynch_votes"] = None, {}
#
#    if not game.get("timers_disabled", False):
#        if phase_name == "accusation_phase":
#            game["accusation_timer"] = socketio.start_background_task(
#                target=accusation_timer_task, timer_id=current_timer_id
#            )
#        elif phase_name == "night":
#            game["night_timer"] = socketio.start_background_task(
#                target=night_timer_task, timer_id=current_timer_id
#            )
#
#    if phase_name == "accusation_phase":
#        game["admin_only_chat"] = False
#        game["seer_investigated"] = False  # Reset seer flag during accusation_phase
#        game["night_wolf_choices"], game["night_seer_choice"] = {}, None
#        game["accusations"] = {}
#    elif phase_name == "night":
#        game["admin_only_chat"] = True
#        game["accusation_restarts"] = 0
#        all_wolves = get_living_players("wolf")
#        wolf_names = [p.username for p in all_wolves]
#        for wolf in all_wolves:
#            teammates = [name for name in wolf_names if name != wolf.username]
#            socketio.emit("wolf_team_info", {"teammates": teammates}, to=wolf.sid)
#
#    socketio.emit(
#        "chat_mode_update",
#        {"admin_only_chat": game["admin_only_chat"]},
#        to=game["game_code"],
#    )
#
#    duration = game["timer_durations"].get(phase_name.replace("_phase", ""), 0)
#    socketio.emit(
#        "phase_change",
#        {
#            "phase": phase_name,
#            "living_players": [
#                {"id": p.id, "username": p.username} for p in get_living_players()
#            ],
#            "all_players": [
#                {"id": p.id, "username": p.username} for p in game["players"].values()
#            ],
#            "duration": duration,
#            "timers_disabled": game.get("timers_disabled", False),
#        },
#        to=game["game_code"],
#    )


def accusation_timer_task(timer_id):
    duration = game["timer_durations"]["accusation"]
    socketio.sleep(duration)
    with app.app_context():
        if (
            game["game_state"] == "accusation_phase"
            and timer_id == game["current_timer_id"]
        ):
            log_and_emit(
                f"Accusation timer ({timer_id}) expired. Tallying accusations."
            )
            tally_accusations(from_timer=True)
        else:
            log_and_emit(f"===> Old accusation timer ({timer_id}) expired. Ignoring.")


def lynch_vote_timer_task(timer_id):
    duration = game["timer_durations"]["lynch_vote"]
    socketio.sleep(duration)
    with app.app_context():
        if (
            game["game_state"] == "lynch_vote_phase"
            and timer_id == game["current_timer_id"]
        ):
            log_and_emit(f"Lynch vote timer ({timer_id}) expired. Processing votes.")
            process_lynch_vote()
        else:
            log_and_emit(f"===> Old lynch vote timer ({timer_id}) expired. Ignoring.")


def night_timer_task(timer_id):
    duration = game["timer_durations"]["night"]
    socketio.sleep(duration)
    with app.app_context():
        if game["game_state"] == "night" and timer_id == game["current_timer_id"]:
            log_and_emit(f"Night timer ({timer_id}) expired. Processing night actions.")
            process_night_actions()
        else:
            log_and_emit(f"===> Old night timer ({timer_id}) expired. Ignoring.")


def check_night_actions_complete():
    living_wolves, living_seer = get_living_players("wolf"), get_living_players("seer")
    wolves_done = all(wolf.id in game["night_wolf_choices"] for wolf in living_wolves)
    seer_done = (
        not living_seer
        or game["night_seer_choice"] is not None
        or game["seer_investigated"]
    )
    if wolves_done and seer_done:
        log_and_emit("All players have completed night actions.")
        process_night_actions()
    else:
        log_and_emit("check night actions -> night Not done yet")


#def process_night_actions():
#    killed_player = None
#    choices = list(game["night_wolf_choices"].values())
#    if (
#        choices
#        and len(choices) == len(get_living_players("wolf"))
#        and choices[0]
#        and all(c == choices[0] for c in choices)
#    ):
#        target_id = choices[0]
#        if target_id in game["players"] and game["players"][target_id].is_alive:
#            game["players"][target_id].is_alive = False
#            killed_player = game["players"][target_id]
#    if killed_player:
#        socketio.emit(
#            "night_result_kill",
#            {
#                "killed_player": {
#                    "id": killed_player.id,
#                    "username": killed_player.username,
#                    "role": killed_player.role,
#                }
#            },
#            to=game["game_code"],
#        )
#    else:
#        socketio.emit("night_result_no_kill", {}, to=game["game_code"])
#
#    if not check_win_conditions():
#        start_new_phase("accusation_phase")


def perform_tally_accusations():
    # 1. Engine Calculation
    outcome = game_instance.tally_accusations()
    res_type = outcome["result"]

    # 2. Handle Outcome
    if res_type == "trial":
        # Trial Started
        socketio.emit("lynch_vote_started", {
            "target_id": outcome["target_id"],
            "target_name": outcome["target_name"],
            "duration": game_instance.timer_durations["lynch_vote"]
        }, to=game["game_code"])
        start_phase_timer("LYNCH_VOTE_PHASE")

    elif res_type == "restart":
        # Tie - Restart Accusations
        socketio.emit("lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"])
        socketio.sleep(3)
        game_instance.set_phase("ACCUSATION_PHASE") # Engine handles internal reset
        start_phase_timer("ACCUSATION_PHASE")
        broadcast_game_state()

    elif res_type == "night":
        # No Accusations / Deadlock -> Sleep
        socketio.emit("lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"])
        socketio.sleep(3)
        game_instance.set_phase("NIGHT")
        start_phase_timer("NIGHT")
        broadcast_game_state()

def process_lynch_vote():
    for p in get_living_players():
        if p.id not in game["lynch_votes"]:
            game["lynch_votes"][p.id] = "no"
    votes, target_id = list(game["lynch_votes"].values()), game["lynch_target_id"]
    yes_votes, target_player = votes.count("yes"), game["players"][target_id]
    vote_summary = {"yes": [], "no": []}
    for voter_id, vote in game["lynch_votes"].items():
        vote_summary[vote].append(game["players"][voter_id].username)
    if yes_votes > len(votes) / 2:
        target_player.is_alive = False
        message = f"🔪 {target_player.username} has been lynched! They were a {target_player.role} ⚰️"
        socketio.emit(
            "lynch_vote_result",
            {"message": message, "killed_id": target_id, "summary": vote_summary},
            to=game["game_code"],
        )
    else:
        message = f"The village has voted to spare {target_player.username}."
        socketio.emit(
            "lynch_vote_result",
            {"message": message, "summary": vote_summary},
            to=game["game_code"],
        )
    socketio.sleep(5)
    if not check_win_conditions():
        start_new_phase("night")

# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    # returning player redirect to game or lobby
    if "player_id" in session and session["player_id"] in game["players"]:
        return (
            redirect(url_for("game_page"))
            if game["game_state"] != "waiting"
            else redirect(url_for("lobby"))
        )
    # login properly then redirect to lobby
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        code = request.form.get("game_code", "").strip().upper()
        if not username:
            return render_template("index.html", error="Username is required.")
        if code != game["game_code"]:
            return render_template("index.html", error="Invalid game code.")
        for p in game["players"].values():
            if p.username.lower() == username.lower():
                return render_template("index.html", error="Username is already taken.")
        session["player_id"], session["username"] = str(uuid.uuid4()), username
        return redirect(url_for("lobby"))
    return render_template("index.html")


@app.route("/lobby")
def lobby():
    player_id = session.get("player_id")
    # new player send to index
    if not player_id:
        return redirect(url_for("index"))
    # if game in session, send valid player to game else index
    if game["game_state"] != "waiting":
        return (
            redirect(url_for("game_page"))
            if player_id in game["players"]
            else redirect(url_for("index"))
        )
    # if no game in session, send to lobby
    return render_template("lobby.html", player_id=player_id,
                           game_code=game["game_code"])


@app.route("/game")
def game_page():
    player_id = session.get("player_id")
    # new player send to index
    if not player_id or player_id not in game["players"]:
        return redirect(url_for("index"))
    # if no game in session, send to lobby
    if game["game_state"] == "waiting":
        return redirect(url_for("lobby"))
    # returning player send to game
    role_str = "unknown"
    if player_id in game_instance.players:
        p = game_instance.players[player_id]
        if p.role:
            role_str = p.role.name_key.replace("role_", "")
            if role_str == "werewolf": role_str = "wolf"
    return render_template(
        "game.html", player_role=role_str, player_id=player_id
    )


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.root_path,
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )

@app.route('/get_roles')
def get_roles():
    """API to send available roles to the frontend to generate checkboxes."""
    # Convert the Roles Registry into a list of dicts
    #role_list = []
    #for role_name, role_class in AVAILABLE_ROLES.items():
    #    # Instantiate a temp object just to read metadata
    #    temp_role = role_class()
    #    role_list.append(temp_role.to_dict())
    #return jsonify(role_list)
    return jsonify([cls().to_dict() for cls in AVAILABLE_ROLES.values()])

# no caching for flask app
@app.after_request
def add_header(r):
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers["Cache-Control"] = "public, max-age=0"
    return r


# --- SocketIO Events ---
@socketio.on("connect")
def handle_connect():
    log_and_emit(f"===> A client connected. SID: {request.sid}")
    player_id = session.get("player_id")
    if not player_id:
        return

    # This logic handles both new players joining the lobby and existing players reconnecting.
    if player_id not in game["players"]:
        if game["game_state"] != "waiting":
            return emit("error", {"message": "Game in progress."})
        new_player = PlayerWrapper(session.get("username"), request.sid)
        # set first player in room to be admin, if no admin from previous match
        # check if error here, since possilbe game["players"] is empty, even in rematch?
        if not game["admin_sid"]:
            new_player.is_admin = True
            game["admin_sid"] = request.sid
            log_and_emit(
                f"===> +++ New player Admin {new_player.username} added to game. id: {new_player} +++"
            )
        game["players"][player_id] = new_player
        log_and_emit(
            f"===> +++ New player {new_player.username} added to game. id: {new_player} +++"
        )
    # reconnecting player
    else:
        game["players"][player_id].sid = request.sid
        log_and_emit(f"===> Player {game['players'][player_id].username} reconnected.")
        # reestablish admin for new game/rematch
        if game["players"][player_id].is_admin:
            game["admin_sid"] = request.sid
            log_and_emit(
                f"===> Admin {game['players'][player_id].username} confirmed and SID updated."
            )

    join_room(game["game_code"])

    # Sync client with the current state
    if game["game_state"] == "waiting":
        broadcast_player_list()
    else:
        player = game["players"][player_id]
        log_and_emit(
            f">>>> Game Phase: {game['game_state']}. Syncing state for {player.username}."
        )
        broadcast_game_state()

@socketio.on("disconnect")
def handle_disconnect():
    player_id, _ = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        log_and_emit(
            f"==== Player {game['players'][player_id].username} disconnected ===="
        )

# In your Flask-SocketIO handler:
@socketio.on('join_game')
def on_join(data):
    room = data['room']
    join_room(room)
    # Get current players from the Game Engine
    # Assuming game_instance is retrieved based on room ID

    if 'game_instance' in globals() and game_instance:
        current_players = [p.name for p in game_instance.players.values()]
    else:
        current_players = []

    emit('update_player_list', {'players': current_players}, to=room)

@socketio.on("send_message")
def handle_send_message(data):
    pid, p = get_player_by_sid(request.sid)
    if not p: return

    msg = data.get("message", "").strip()
    if not msg: return

    # 1. Determine Context
    # Check Phase on Engine
    phase = game_instance.phase
    is_night = (phase == "NIGHT")

    # 2. Check Restrictions (Admin Only OR Night Time)
    if game["admin_only_chat"] or is_night:
        if p.is_admin:
            # Admin overrides restriction -> Sends as Announcement
            socketio.emit("new_message", {
                "text": f"<strong>ADMIN:</strong> {msg}",
                "channel": "announcement"
            }, to=game["game_code"])
        else:
            # Non-Admins get silenced
            if is_night:
                emit("message", {"text": f"shhh...the village is sleeping quietly, <strong>{p.username}</strong>"})
            else:
                emit("message", {"text": "Chat is currently restricted."})
        return

    # 3. Determine Channel (Lobby vs Living vs Ghost)
    channel = "lobby"

    # Only separate chats if the game is actively running (Day Phases)
    # If Phase is LOBBY or GAME_OVER/ended, everyone talks in 'lobby' channel
    active_phases = ["ACCUSATION_PHASE", "LYNCH_VOTE_PHASE"]

    if phase in active_phases:
        engine_p = game_instance.players.get(pid)
        if engine_p:
            channel = "living" if engine_p.is_alive else "ghost"

    # 4. Broadcast
    socketio.emit("new_message", {
        "text": f"<strong>{p.username}:</strong> {msg}",
        "channel": channel
    }, to=game["game_code"])


@socketio.on("admin_toggle_chat")
def handle_admin_toggle_chat():
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_admin:
        return

    game["admin_only_chat"] = not game["admin_only_chat"]
    game_instance.admin_only_chat = game["admin_only_chat"] # Sync engine

    emit("chat_mode_update", {"admin_only_chat": game["admin_only_chat"]},
        to=game["game_code"],
    )


@socketio.on("admin_set_timers")
def handle_admin_set_timers(data):
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return

    game_instance.timers_disabled = data.get("timers_disabled", False)
    # Update durations
    for key in ["night", "accusation", "lynch_vote"]:
        if data.get(key): game_instance.timer_durations[key] = int(data[key])
    emit("message", {"text": "Timer settings updated."})
    log_and_emit(f"Admin set new timer durations: {game['timer_durations']}")


@socketio.on("admin_exclude_player")
def handle_admin_exclude_player(data):
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    player_id = data.get("player_id")
    if player_id in game["players"]:
        sid = game["players"][player_id].sid
        del game["players"][player_id]
        emit("force_kick", to=sid)
        #leave_room(game["game_code"], sid=sid)
        #broadcast_player_list()
    if player_id in game_instance.players:
        del game_instance.players[player_id]


@socketio.on("start_game")
def handle_start_game(data):
    if request.sid != game.get("admin_sid"):
        return emit("error", {"message": "Only the admin can start the game."})
    if len(game["players"]) < 4:
        return emit("error", {"message": "Cannot start with fewer than 4 players."})
    if game.get("game_state") != "waiting":
        return emit("error", {"message": "Game is already in progress."})

    log_and_emit("===> Admin started game. Assigning roles.")

    # conigure engine
    game_instance.mode = data.get("settings", {}).get("mode", "standard")
    game_instance.players = {}
    for pid, obj in game["players"].items():
        game_instance.add_player(pid, obj.username)

    #game["players_ready_for_game"] = set()
    log_and_emit(f"===> Game Started! Mode: {game_instance.mode}")

    game_instance.assign_roles(data.get("roles", []))
    game["game_state"] = "started"
    socketio.emit("game_started", to=game["game_code"])

    # 3. Transition to Night
    game_instance.set_phase("NIGHT")
    start_phase_timer("NIGHT")
    broadcast_game_state()

@socketio.on("admin_next_phase")
def handle_admin_next_phase():
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_admin:
        return

    current_phase = game_instance.phase
    log_and_emit(f"Admin is advancing the phase from {current_phase}.")

    if current_phase == "NIGHT":
        resolve_night()
    elif current_phase == "ACCUSATION_PHASE":
        perform_tally_accusations()
    elif current_phase == "LYNCH_VOTE_PHASE":
        resolve_lynch()

def resolve_lynch():
    # 1. Engine Calculation
    result = game_instance.resolve_lynch_vote()

    # 2. Notify
    msg = "No one was lynched."
    if result["killed_id"]:
        name = game_instance.players[result["killed_id"]].name
        role = game_instance.players[result["killed_id"]].role.name_key
        msg = f"⚖️ <strong>{name}</strong> was lynched! Role: {role} ⚰️"

    socketio.emit("lynch_vote_result", {
        "message": msg,
        "summary": result["summary"],
        "killed_id": result["killed_id"]
    }, to=game["game_code"])

    socketio.sleep(5)
    check_game_over_or_next_phase()

def check_game_over_or_next_phase():
    if game_instance.check_game_over():
        # GAME OVER
        game_instance.phase = "ended" # Manual sync string
        game["game_over_data"] = game_instance.game_over_data # Sync for refresh
        broadcast_game_state() # Will send game_over_data present in Engine
    else:
        # NEXT PHASE
        # Logic: If we just finished Night, go Day. If we finished Lynch, go Night.
        # Check engine's current phase to determine next step.
        # Actually, Engine `resolve_lynch` sets phase to NIGHT automatically.
        # Engine `resolve_night` does NOT set phase to Day automatically in our design (it returns deaths).

        if game_instance.phase == "NIGHT":
            # Night just finished -> Day
            game_instance.set_phase("ACCUSATION_PHASE")
            start_phase_timer("ACCUSATION_PHASE")
            broadcast_game_state()
        elif game_instance.phase == "NIGHT":
            # Lynch just finished -> Engine already set phase to NIGHT
            start_phase_timer("NIGHT")
            broadcast_game_state()

@socketio.on("admin_set_new_code")
def handle_admin_set_new_code(data):
    """Handles admin setting a new game code, keeping admin in lobby and kicking others."""
    if request.sid != game.get("admin_sid"):
        return
    new_code = data.get("new_code", "").strip().upper()

    if not new_code:
        return emit("error", {"message": "New code cannot be empty."})

    admin_id, admin_player = get_player_by_sid(request.sid)
    if not admin_player:
        return

    # Notify all OTHER players to re-login
    socketio.emit(
        "force_relogin",
        {"new_code": new_code},
        to=game["game_code"], skip_sid=request.sid,
    )

    global game_instance
    game_instance = Game("main_game_")
    # Reset the game, preserving only the admin
    admin_conn = game["players"][session["player_id"]]
    game["players"] = { session["player_id"]: admin_conn }
    game["game_code"] = new_code
    game["game_state"] = "waiting"

    # Update the admin's lobby view
    join_room(new_code)
    broadcast_player_list()

@socketio.on('pnp_request_state')
def handle_pnp_request(data):
    """
    Called when a player confirms identity in Pass-and-Play.
    Returns their specific role data and valid targets.
    """
    player = game_instance.players.get(data.get('player_id'))
    if player:
        targets = player.role.get_valid_targets(player, {'players': list(game_instance.players.values())})
        prompt = getattr(player.role, 'night_prompt', "Choose a target")

        emit('pnp_state_received', {
            "id": player.id,
            "role_name": player.role.name_key,
            "prompt": prompt,
            "targets": [{"id": t.id, "name": t.name} for t in targets]
        })


@socketio.on('pnp_submit_action')
def handle_pnp_action(data):
    """
    Unified action handler for Pass-and-Play.
    """
    result = game_instance.receive_night_action(data.get('actor_id'), data.get('target_id'))
    if result == "RESOLVED":
        resolve_night()
    else:
        # Confirm receipt to client so they can show "Passed" screen
        emit("action_accepted", {}, to=request.sid)

@socketio.on("client_ready_for_game")
def handle_client_ready_for_game():
    """
    Simple handler: Just sync the game state.
    We no longer wait for all players to 'ready up' before starting logic.
    """
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        return

    # Just broadcast the state so the UI updates
    broadcast_game_state()

@socketio.on("wolf_choice")
def handle_wolf_choice(data):
    player_id = session.get("player_id")
    res = game_instance.receive_night_action(player_id, data.get("target_id"))
    if res == "RESOLVED": resolve_night()

@socketio.on("seer_choice")
def handle_seer_choice(data):
    player_id = session.get("player_id")
    target_id = data.get("target_id")
    game_instance.receive_night_action(player_id, target_id)

    # Immediate Seer Feedback (Standard Mode Feature)
    target = game_instance.players.get(target_id)
    if target:
        is_wolf = (target.role.team == 'wolf' or target.role.team == 'monster')
        emit("seer_result", {"username": target.name, "role": "wolf" if is_wolf else "villager"})


@socketio.on("accuse_player")
def handle_accuse_player(data):
    pid = session.get("player_id")
    tid = data.get("target_id")

    # 1. Update Engine
    all_voted = game_instance.process_accusation(pid, tid)

    # 2. Broadcast Update
    accuser = game_instance.players[pid]
    target = game_instance.players[tid]
    emit("accusation_made", {"accuser_name": accuser.name, "accused_name": target.name}, to=game["game_code"])

    # Update badge counts
    counts = Counter(game_instance.accusations.values())
    emit("accusation_update", counts, to=game["game_code"])

    # 3. Check All Voted
    if all_voted:
        perform_tally_accusations()

@socketio.on("cast_lynch_vote")
def handle_cast_lynch_vote(data):
    pid = session.get("player_id")
    all_voted = game_instance.cast_lynch_vote(pid, data.get("vote"))
    if all_voted:
        resolve_lynch()

# --- Resolution ---

def resolve_night():
    # 1. Engine Calculation
    deaths = game_instance.resolve_night_phase()

    # 2. Notify Clients
    if deaths:
        for pid in deaths:
            p = game_instance.players[pid]
            socketio.emit("night_result_kill", {"killed_player": {"id": p.id, "username": p.name, "role": p.role.name_key}}, to=game["game_code"])
    else:
        socketio.emit("night_result_no_kill", {}, to=game["game_code"])

    check_game_over_or_next_phase()

@socketio.on("vote_to_end_day")
def handle_vote_to_end_day():
    pid = session.get("player_id")
    majority = game_instance.vote_to_sleep(pid)

    votes = len(game_instance.end_day_votes)
    living = len(game_instance.get_living_players())

    emit("end_day_vote_update", {"count": votes, "total": living}, to=game["game_code"])

    if majority:
        perform_tally_accusations()

# handle voting process after game ends. tracks votes, upon
# majority , resets game state and redirects all to lobby
@socketio.on("vote_for_rematch")
def handle_vote_for_rematch():
    global game_instance
    player_id, p = get_player_by_sid(request.sid)
    if not p or game["game_state"] != "ended":
        return

    if player_id not in game["rematch_votes"]:
        game_instance.rematch_votes.add(player_id)

        num_votes = len(game_instance.rematch_votes)
        total_players = len(game["players"])

        # Check if a majority has been reached or admin forces
        if num_votes > total_players / 2 or p.is_admin:
            old_mode = game_instance.mode
            game_instance = Game("main_game", mode=old_mode)
            game["game_state"] = "waiting"
            game["game_over_data"] = None

            socketio.emit("redirect_to_lobby", {}, to=game["game_code"])
        else:
            # Broadcast the current vote count
            payload = {"count": num_votes, "total": total_players}
            emit("rematch_vote_update", payload, to=game["game_code"])


if __name__ == "__main__":
    # This block is for local development only and will not be used by Gunicorn
    socketio.run(app, host="0.0.0.0", debug=True, allow_unsafe_werkzeug=True)
