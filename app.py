"""
app.py
Version: 5.2.3 android app working
"""
import json
import logging
import html
import os
from os.path import join, dirname, exists
import time
import traceback # for debugging
import uuid
from collections import Counter
from dotenv import find_dotenv, load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_socketio import SocketIO, emit, join_room

from config import GAME_DEFAULTS
from game_engine import *
from roles import *

# --- App Initialization ---
# android web config
internal_path = join(dirname(__file__), '.env.werewolves')
external_path = "/storage/emulated/0/Android/data/io.github.davidchilin.werewolves_game/files/config.env"

# android Load external first (overrides), then internal
if exists(external_path):
    print(f"Loading custom config from: {external_path}")
    load_dotenv(external_path, override=True)
elif exists(internal_path):
    print(f"Loading internal config from: {internal_path}")
    load_dotenv(internal_path)
else:
    # If neither exists, find_dotenv will try to locate a generic .env
    print("No specific .env.werewolves found. Searching for default .env...")
    load_dotenv(find_dotenv())

app = Flask(__name__)
# IMPORTANT: In production, this MUST be set as an environment variable in .env.werewolves
raw_key = os.environ.get("FLASK_SECRET_KEY")
if not raw_key:
    print("WARNING: FLASK_SECRET_KEY not found in environment. Generating a random key for this session.")
    app.config["SECRET_KEY"] = str(uuid.uuid4())
else:
    app.config["SECRET_KEY"] = raw_key

# 1. Block JavaScript from reading the cookie (Mitigates XSS)
app.config["SESSION_COOKIE_HTTPONLY"] = True

# 2. Only send cookies over HTTPS (Requires SSL setup mentioned above)
# Set this to True in production, False if testing locally without SSL
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("USE_HTTPS", "False").lower() == "true"

# 3. Prevent Cross-Site Request Forgery (CSRF) on login
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

def flatten_dict(d, parent_key='', sep='.'):
    """Recursively flattens a nested dictionary."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

# Load and Flatten Translations immediately on startup
TRANSLATIONS = {}
for lang in ["en", "es", "de"]:
    # Create the full path: /.../app/src/main/python/static/en.json
    file_path = join(dirname(__file__), "static", f"{lang}.json")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            TRANSLATIONS[lang] = flatten_dict(raw_data)
            print(f"Loaded server translations for: {lang}")
    except FileNotFoundError:
        print(f"Warning: {lang}.json not found at {file_path}")

def t_server(key, lang="en"):
    # 1. Select Dictionary (Fallback to EN if language missing)
    dataset = TRANSLATIONS.get(lang, TRANSLATIONS.get("en", {}))

    # 2. Direct Lookup (No splitting, no looping)
    return dataset.get(key, key)

# --- Global State ---
game_instance = Game("main_game")

join_attempts = {} # for rate limiting

# Configure CORS for Socket.IO from environment variables
# This is crucial for security in a production environment.
game_port = os.environ.get("GAME_PORT")
print(f"GAME_PORT: ", game_port)
nginx_port = os.environ.get("NGINX_PORT", "5000")

# Default to allowing all origins (*) if CORS_ALLOWED_ORIGINS is missing
origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "*")

if origins_raw == "*":
    origins = "*"
else:
    # If a specific origin exists, handle the port replacement logic
    if game_port and nginx_port:
        origins_raw = origins_raw.replace(f":{nginx_port}", f":{game_port}")
    origins = origins_raw.split(",")

# 2. Set Async Mode dynamically
# Android MUST use 'threading' to avoid crashes.
# Computer (Gunicorn) should use None (Auto-detect), which will find 'gevent' automatically.
try:
    from java import jclass # type: ignore # pylint: disable=import-error
    IS_ANDROID = True
except ImportError:
    IS_ANDROID = False

if IS_ANDROID:
    socketio_async_mode = 'threading'
    print(f"Detected Android environment. Forcing async_mode: {socketio_async_mode}.")
    origins = "*"
else:
    socketio_async_mode = None
    print(f"Detected PC environment. async_mode: {socketio_async_mode}")

print(f"Origins: ", origins)

# 3. Initialize SocketIO with the variable
socketio = SocketIO(
    app,
    cors_allowed_origins=origins,
    async_mode=socketio_async_mode # type: ignore
)

# Game Dictionary stores connection/wrapper info
game = {
    "admin_sid": None,
    "game_code": "W",
    "game_state": PHASE_LOBBY,
    "players": {},  # Dict[player_id(uuid), PlayerWrapper_Obj]
}

lobby_state = {
    "selected_roles": GAME_DEFAULTS["DEFAULT_ROLES"],
    "settings": {},
}


class PlayerWrapper:
    def __init__(self, name, sid, language="en"):
        self.name = name
        self.sid = sid
        self.is_admin = False
        self.language = language


# --- Helper Functions ---
def get_player_by_sid(sid):
    for player_id, player_wrapper in game["players"].items():
        if player_wrapper.sid == sid:
            return player_id, player_wrapper
    return None, None


def log_and_emit(message):
    print(message)
    socketio.emit("log_message", {"text": message}, to=game["game_code"])


def broadcast_player_list():
    player_list_data = []
    for player_id, player_wrapper in game["players"].items():
        is_alive = True
        if player_id in game_instance.players:
            is_alive = game_instance.players[player_id].is_alive

        player_list_data.append(
            {
                "id": player_id,
                "name": player_wrapper.name,
                "is_admin": player_wrapper.is_admin,
                "is_alive": is_alive,
            }
        )
    socketio.emit(
        "update_player_list",
        {
            "players": player_list_data,
            "game_code": game["game_code"],
            "admin_only_chat": game_instance.admin_only_chat,
        },
        to=game["game_code"],
    )


def get_public_game_state():
    """
    Generates the game state data common to ALL players.
    Optimization: Calculated once per tick/broadcast.
    """
    try:
        all_players_data = []
        for p in game_instance.players.values():
            lang = "en"
            if p.id in game["players"]:
                lang = game["players"][p.id].language

            all_players_data.append(
                {"id": p.id, "name": p.name, "is_alive": p.is_alive, "language": lang}
            )

        accusation_counts = {}
        if game_instance.phase == PHASE_ACCUSATION:
            accusation_counts = dict(Counter(game_instance.pending_actions.values()))

        remaining_time = 0
        if game_instance.phase_start_time and not game_instance.timers_disabled:
            key = game_instance.phase
            if key in game_instance.timer_durations:
                elapsed = time.time() - game_instance.phase_start_time
                remaining_time = max(0, game_instance.timer_durations[key] - elapsed)

        lynch_target_name = None
        if game_instance.lynch_target_id:
            target_obj = game_instance.players.get(game_instance.lynch_target_id)
            if target_obj:
                lynch_target_name = target_obj.name

        acted_ids = []
        if game_instance.phase == PHASE_NIGHT:
            acted_ids = list(game_instance.turn_history)
        elif game_instance.phase == PHASE_ACCUSATION:
            acted_ids = list(
                set(game_instance.pending_actions.keys()) | game_instance.end_day_votes
            )
        elif game_instance.phase == PHASE_LYNCH:
            acted_ids = list(game_instance.pending_actions.keys())

        return {
            "accusation_counts": accusation_counts,
            "acted_players": acted_ids,
            "admin_only_chat": game_instance.admin_only_chat,
            "all_players": all_players_data,
            "duration": remaining_time,
            "game_over_data": game_instance.game_over_data,
            "ghost_mode_active": game_instance.is_ghost_mode_active(),
            "living_players": [
                {"id": p.id, "name": p.name} for p in game_instance.get_living_players()
            ],
            "lynch_target_id": game_instance.lynch_target_id,
            "lynch_target_name": lynch_target_name,
            "message_history": game_instance.message_history,
            "mode": game_instance.mode,
            "phase": game_instance.phase,
            "phase_end_time": game_instance.phase_end_time,
            "rematch_vote_count": len(game_instance.rematch_votes),
            "sleep_vote_count": len(game_instance.end_day_votes),
            "timers_disabled": game_instance.timers_disabled,
            "total_accusation_duration": game_instance.timer_durations.get(
                PHASE_ACCUSATION, 90
            ),
        }
    except Exception as e:
        print(f"DEBUG ERROR in Public Data: {e}")
        return None


def generate_player_payload(player_id, player_wrapper=None, public_data=None):
    """
    Generates the specific game state payload for a given player ID.
    Accepts pre-calculated public_data for optimization.
    """
    # 1. Use provided Public Data or generate it (CPU Optimization)
    if public_data is None:
        public_data = get_public_game_state()
    if not public_data:
        return None

    # 2. Private Data (Specific to the requested player_id)
    engine_player_obj = game_instance.players.get(player_id)
    if not engine_player_obj:
        return None

    role_str = engine_player_obj.role.name_key if engine_player_obj.role else "Unknown"
    is_alive = engine_player_obj.is_alive
    night_ui = None

    if (
        game_instance.phase == PHASE_NIGHT
        and engine_player_obj.role
        and engine_player_obj.is_alive
    ):
        ctx = {
            "players": list(game_instance.players.values()),
            "villager_prompt_index": game_instance.get_current_prompt_index(),
        }
        night_ui = engine_player_obj.role.get_night_ui_schema(engine_player_obj, ctx)

    # Retrieve Player Actions
    my_phase_target_id = game_instance.get_player_phase_choice(player_id)
    my_phase_metadata = game_instance.get_player_phase_choice(player_id, True)
    my_sleep_vote = game_instance.has_player_voted_to_sleep(player_id)

    # Resolve Target Names for UI feedback
    my_phase_target_name = None
    if my_phase_target_id:
        target_obj = game_instance.players.get(my_phase_target_id)
        if target_obj:
            my_phase_target_name = target_obj.name

    valid_targets_data = []
    if engine_player_obj.role:
        targets = engine_player_obj.role.get_valid_targets(
            {"players": list(game_instance.players.values())}
        )
        valid_targets_data = [{"id": t.id, "name": t.name} for t in targets]

    # 3. Admin Status
    is_admin = False
    if player_wrapper:
        is_admin = player_wrapper.is_admin
    else:
        wrapper = game["players"].get(player_id)
        if wrapper:
            is_admin = wrapper.is_admin

    target_wrapper = player_wrapper
    if not target_wrapper:
        target_wrapper = game["players"].get(player_id)

    # Default to 'en' if missing
    player_lang = "en"
    if target_wrapper and hasattr(target_wrapper, "language"):
        player_lang = target_wrapper.language
    # 4. Merge Private Data with Public Data
    # We copy public_data to avoid modifying the cached dictionary
    payload = public_data.copy()

    payload.update(
        {
            "is_admin": is_admin,
            "is_alive": is_alive,
            "my_lynch_vote": my_phase_target_id,
            "my_phase_target_id": my_phase_target_id,
            "my_phase_metadata": my_phase_metadata,
            "my_phase_target_name": my_phase_target_name,
            "my_rematch_vote": player_id in game_instance.rematch_votes,
            "my_sleep_vote": my_sleep_vote,
            "night_ui": night_ui,
            "this_player_id": player_id,
            "valid_targets": valid_targets_data,
            "language": player_lang,
            "your_role": role_str,
        }
    )

    return payload


def broadcast_game_state():
    """Syncs the FULL Engine state to all clients efficiently."""
    # 1. Generate Public Data Once (CPU Optimization)
    public_data = get_public_game_state()
    if not public_data:
        return

    for player_id, player_wrapper in game["players"].items():
        if not player_wrapper.sid:
            continue

        # 2. Generate private payload using cached public data
        payload = generate_player_payload(
            player_id, player_wrapper, public_data=public_data
        )
        if payload:
            socketio.emit("game_state_sync", payload, to=player_wrapper.sid)


# --- Timer System ---
game_loop_running = False


def background_game_loop():
    """Central heartbeat that ticks the engine every second."""
    global game_loop_running
    print(">>> Game Loop Started <<<")
    while game_loop_running:
        socketio.sleep(1)
        with app.app_context():
            result = game_instance.tick()
            if result == "TIMEOUT":
                log_and_emit(f"Timer expired for {game_instance.phase}.")
                if game_instance.phase == PHASE_NIGHT:
                    resolve_night()
                elif game_instance.phase == PHASE_ACCUSATION:
                    perform_tally_accusations()
                elif game_instance.phase == PHASE_LYNCH:
                    resolve_lynch()


def perform_tally_accusations():
    outcome = game_instance.tally_accusations()
    result_type = outcome["result"]
    if result_type == "trial":
        if outcome.get("message"):
            print(f"perform_tally_accusations message: {outcome.get('message')}")
            socketio.emit("message", {"text": outcome["message"]}, to=game["game_code"])

        trial_msg = {
            "key": "events.trial_started",
            "variables": {"target": outcome["target_name"]},
        }
        game_instance.message_history.append(trial_msg)

        socketio.emit(
            "lynch_vote_started",
            {
                "target_id": outcome["target_id"],
                "target_name": outcome["target_name"],
                "phase_end_time": game_instance.phase_end_time,
            },
            to=game["game_code"],
        )
    elif result_type == "restart":
        game_instance.message_history.append(outcome["message"])
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(GAME_DEFAULTS["PAUSE_DURATION"])
        game_instance.set_phase(PHASE_ACCUSATION)
        broadcast_game_state()

    elif result_type == "night":
        game_instance.message_history.append(outcome["message"])
        # No Accusations / Deadlock -> Sleep
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(GAME_DEFAULTS["PAUSE_DURATION"])
        broadcast_game_state()


# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    # allow bypass if adding a player in PnP mode
    bypass_redirect = request.args.get("add_player")

    # returning player redirect to game or lobby
    if (
        not bypass_redirect
        and "player_id" in session
        and session["player_id"] in game["players"]
    ):
        return (
            redirect(url_for("game_page"))
            if game["game_state"] != PHASE_LOBBY
            else redirect(url_for("lobby"))
        )
    # login properly then redirect to lobby
    if request.method == "POST":
        lang = request.form.get("language", "en")
        # join rate limiting
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        current_time = time.time()
        last_attempt_time = join_attempts.get(client_ip, 0)
        if current_time - last_attempt_time < 2.0:
            return render_template("index.html", error="Too many attempts. Please wait.")
        # Update the timestamp for this IP
        join_attempts[client_ip] = current_time

        raw_name = request.form.get("name", "").strip()
        name = html.escape(raw_name)

        code = request.form.get("game_code", "").strip().upper()
        if not name:
            return render_template("index.html", error=t_server("ui.login.error_name_required", lang))
        if len(name) > 20:
            return render_template("index.html", error=t_server("ui.login.error_name_length", lang))
        if not code:
            return render_template("index.html", error=t_server("ui.login.error_code_required", lang))
        if not code.isalnum():
            return render_template("index.html", error=t_server("ui.login.error_code_alnum", lang))
        if len(code) > 20:
            return render_template("index.html", error=t_server("ui.login.error_code_length", lang))
        if code != game["game_code"]:
            return render_template("index.html", error=t_server("ui.login.error_code_invalid", lang))
        if len(game["players"]) >= 24:
             return render_template("index.html", error=t_server("ui.login.error_lobby_full", lang))

        for p in game["players"].values():
            if p.name.lower() == name.lower():
                return render_template("index.html", error=t_server("ui.login.error_name_taken", lang))

        session["language"] = lang
        session["player_id"], session["name"] = str(uuid.uuid4()), name
        return redirect(url_for("lobby"))
    return render_template("index.html")


@app.route("/lobby")
def lobby():
    player_id = session.get("player_id")
    # new player send to index
    if not player_id:
        return redirect(url_for("index"))
    # if game in session, send valid player to game else index
    if game["game_state"] != PHASE_LOBBY:
        return (
            redirect(url_for("game_page"))
            if player_id in game["players"]
            else redirect(url_for("index"))
        )
    # if no game in session, send to lobby
    return render_template(
        "lobby.html", player_id=player_id, game_code=game["game_code"]
    )


@app.route("/game")
def game_page():
    player_id = session.get("player_id")
    # new player send to index
    if not player_id or player_id not in game["players"]:
        return redirect(url_for("index"))
    # if no game in session, send to lobby
    if game["game_state"] == PHASE_LOBBY:
        return redirect(url_for("lobby"))
    # returning player send to game
    role_str = "unknown"
    if player_id in game_instance.players:
        p = game_instance.players[player_id]
        if p.role:
            role_str = p.role.name_key
    return render_template("game.html", player_role=role_str, player_id=player_id)


@app.route("/img/favicon.ico")
def favicon():
    return send_from_directory(
        app.root_path, "favicon.ico", mimetype="image/vnd.microsoft.icon"
    )


@app.route("/get_roles")
def get_roles():
    return jsonify([cls().to_dict() for cls in AVAILABLE_ROLES.values()])

@app.route('/shutdown', methods=['POST'])
def shutdown():
    socketio.stop()
    return "Server shutting down...", 200

# Only disable caching for HTML and JSON (Game Data)
@app.after_request
def add_header(response):
    if (
        "text/html" in response.content_type
        or "application/json" in response.content_type
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- SocketIO Events ---
@socketio.on("admin_update_roles")
def handle_admin_update_roles(data):
    if request.sid != game["admin_sid"]:
        return
    # 1. Update Server State
    lobby_state["selected_roles"] = data.get("roles", [])

    # 2. Broadcast to ALL clients so their checkboxes update
    emit("sync_roles", {"roles": lobby_state["selected_roles"]}, to=game["game_code"])


@socketio.on("admin_update_settings")
def handle_admin_update_settings(data):
    if request.sid != game["admin_sid"]:
        return

    # Update lobby settings state
    if "settings" not in lobby_state:
        lobby_state["settings"] = {}
    for k, v in data.items():
        lobby_state["settings"][k] = v

    # Broadcast updates to all clients in lobby
    emit("sync_settings", lobby_state["settings"], to=game["game_code"])


@socketio.on("connect")
def handle_connect(auth=None):
    player_id = session.get("player_id")
    if not player_id:
        return

    # This logic handles both new players joining the lobby and existing players reconnecting.
    if player_id not in game["players"]:
        if game["game_state"] != PHASE_LOBBY:
            return emit("error", {"message": "Game in progress."})
        lang = session.get("language", "en")
        new_player = PlayerWrapper(session.get("name"), request.sid, language=lang)
        # set first player in room to be admin, if no admin from previous match
        # OR if we are in Pass-and-Play mode, grant admin to the newly added player
        # so they can control the lobby from the single device
        is_pnp = lobby_state.get("settings", {}).get("mode") == "pass_and_play"
        if not game["admin_sid"] or is_pnp:
            new_player.is_admin = True
            game["admin_sid"] = request.sid
            log_and_emit(f"===> +++ New player Admin {new_player.name} added to game.")
        game["players"][player_id] = new_player
        log_and_emit(f"===> +++ New player {new_player.name} added to game.")
    # reconnecting player
    else:
        game["players"][player_id].sid = request.sid
        log_and_emit(f"===> Player {game['players'][player_id].name} reconnected.")
        # reestablish admin for new game/rematch
        if game["players"][player_id].is_admin:
            game["admin_sid"] = request.sid
            log_and_emit(
                f"===> Admin {game['players'][player_id].name} confirmed and SID updated."
            )
    join_room(game["game_code"])

    # Sync client with the current state
    if game["game_state"] == PHASE_LOBBY:
        emit("sync_roles", {"roles": lobby_state["selected_roles"]}, to=request.sid)
        emit("sync_settings", lobby_state.get("settings", {}), to=request.sid)
        broadcast_player_list()
    else:
        player = game["players"][player_id]
        log_and_emit(
            f">>>> Game Phase: {game['game_state']}. Syncing state for {player.name}."
        )
        broadcast_game_state()
        send_werewolf_info(player_id)
        send_cupid_info(player_id)


@socketio.on("disconnect")
def handle_disconnect():
    player_id, _ = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        log_and_emit(f"==== Player {game['players'][player_id].name} disconnected ====")


@socketio.on("join_game")
def on_join(data):
    room = data["room"]
    join_room(room)
    if "game_instance" in globals() and game_instance:
        current_players = [p.name for p in game_instance.players.values()]
    else:
        current_players = []
    emit("update_player_list", {"players": current_players}, to=room)


last_message_time = {}


@socketio.on("send_message")
def handle_send_message(data):
    current_time = time.time()
    last_time = last_message_time.get(request.sid, 0)

    # Enforce 0.5 second cooldown
    if current_time - last_time < 0.5:
        return  # Silently ignore spam

    last_message_time[request.sid] = current_time

    pid, p = get_player_by_sid(request.sid)
    if not p:
        return
    raw_msg = data.get("message", "").strip()
    msg = html.escape(raw_msg)
    if len(msg) > 500:
        return emit("error", {"message": "Message too long."})
    if not msg:
        return
    phase = game_instance.phase
    is_night = phase == PHASE_NIGHT

    # 2. Check Restrictions (Admin Only OR Night Time)
    if game_instance.admin_only_chat or is_night:
        if p.is_admin:
            # Admin overrides restriction -> Sends as Announcement
            socketio.emit(
                "new_message",
                {"text": f"<strong>ADMIN:</strong> {msg}", "channel": "announcement"},
                to=game["game_code"],
            )
        else:
            # Non-Admins get silenced
            if is_night:
                msg = {
                    "key": "events.chat_night_shh",
                    "variables": {"name": p.name}
                }
                emit("message", {"text": msg})
            else:
                msg = {"key": "events.chat_restricted", "variables": {}}
                emit("message", {"text": msg})
        return
    channel = "lobby"

    # Only separate chats if the game is actively running (Day Phases)
    # If Phase is LOBBY or GAME_OVER/ended, everyone talks in 'lobby' channel
    active_phases = [PHASE_ACCUSATION, PHASE_LYNCH]
    if phase in active_phases:
        engine_p = game_instance.players.get(pid)
        if engine_p:
            channel = "living" if engine_p.is_alive else "ghost"
    socketio.emit(
        "new_message",
        {"text": f"<strong>{p.name}:</strong> {msg}", "channel": channel},
        to=game["game_code"],
    )


@socketio.on("admin_toggle_chat")
def handle_admin_toggle_chat():
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_admin:
        return
    game_instance.admin_only_chat = not game_instance.admin_only_chat
    emit(
        "chat_mode_update",
        {"admin_only_chat": game_instance.admin_only_chat},
        to=game["game_code"],
    )

@socketio.on("admin_transfer_admin")
def handle_admin_transfer(data):
    if request.sid != game["admin_sid"]:
        return

    target_id = data.get("target_id")
    if not target_id or target_id not in game["players"]:
        return

    current_admin_id = session.get("player_id")

    # 1. Update wrappers
    game["players"][current_admin_id].is_admin = False
    game["players"][target_id].is_admin = True

    # 2. Update Global SID
    game["admin_sid"] = game["players"][target_id].sid

    log_and_emit(f"===> Admin transferred from {game['players'][current_admin_id].name} to {game['players'][target_id].name}")

    # 3. Broadcast updates
    if game["game_state"] == PHASE_LOBBY:
        broadcast_player_list()
        # Also need to send settings to new admin so their UI updates
        emit("sync_settings", lobby_state.get("settings", {}), to=game["admin_sid"])
    else:
        broadcast_game_state()

@socketio.on("admin_set_timers")
def handle_admin_set_timers(data):
    if request.sid != game["admin_sid"]:
        return

    if "settings" not in lobby_state:
        lobby_state["settings"] = {}

    # Save disabled state if present
    if "timers_disabled" in data:
        if "timers" not in lobby_state["settings"]:
            lobby_state["settings"]["timers"] = {}
        lobby_state["settings"]["timers"]["timers_disabled"] = data["timers_disabled"]

    # Save durations if present
    key_map = {
        "accusation": PHASE_ACCUSATION,
        "night": PHASE_NIGHT,
        "lynch_vote": PHASE_LYNCH,
    }

    # Check if we are updating specific durations (from the 'Set Timers' button)
    # If so, save them to lobby_state too
    has_duration_update = any(k in data for k in key_map.keys())
    if has_duration_update:
        if "timers" not in lobby_state["settings"]:
            lobby_state["settings"]["timers"] = {}

        for frontend_key in key_map.keys():
            if frontend_key in data:
                lobby_state["settings"]["timers"][frontend_key] = data[frontend_key]

    if "timers_disabled" in data:
        game_instance.timers_disabled = data["timers_disabled"]
        status = "Paused" if game_instance.timers_disabled else "Resumed"
        log_and_emit(f"Admin has {status} the timers.")
        # Broadcast the new state so UI updates immediately
        broadcast_game_state()

    # The numeric duration settings should generally only be changed in Lobby/Waiting
    if game["game_state"] == PHASE_LOBBY:
        updated_timers = {}
        key_map = {
            "accusation": PHASE_ACCUSATION,
            "night": PHASE_NIGHT,
            "lynch_vote": PHASE_LYNCH,
        }
        for frontend_key, engine_phase_key in key_map.items():
            val = data.get(frontend_key)
            if val:
                try:
                    new_duration = int(val)
                    final_duration = max(10, new_duration)
                    game_instance.timer_durations[engine_phase_key] = final_duration
                    updated_timers[frontend_key] = final_duration
                except ValueError:
                    pass
        if updated_timers:
            emit("admin_timers_updated", {"timers": updated_timers})
            log_and_emit(f"Admin set new timer durations: {updated_timers}")


@socketio.on("admin_exclude_player")
def handle_admin_exclude_player(data):
    if request.sid != game["admin_sid"] or game["game_state"] != PHASE_LOBBY:
        return
    player_id = data.get("player_id")
    if player_id in game["players"]:
        sid = game["players"][player_id].sid
        del game["players"][player_id]
        emit("force_kick", to=sid)
    if player_id in game_instance.players:
        del game_instance.players[player_id]
    broadcast_player_list()


@socketio.on("start_game")
def handle_start_game(data):
    settings = data.get("settings", {})
    is_pnp = settings.get("mode") == "pass_and_play"

    if request.sid != game.get("admin_sid") and not is_pnp:
        return emit("error", {"message": "Only the admin can start the game."})
    if len(game["players"]) < GAME_DEFAULTS["MIN_PLAYERS"]:
        return emit(
            "error",
            {
                "message": "Cannot start with fewer than {GAME_DEFAULTS['MIN_PLAYERS']} players."
            },
        )
    if game.get("game_state") != PHASE_LOBBY:
        return emit("error", {"message": "Game is already in progress."})
    log_and_emit("===> Admin started game. Assigning roles.")
    global game_loop_running
    if not game_loop_running:
        game_loop_running = True
        socketio.start_background_task(background_game_loop)
    # configure engine
    lobby_state["settings"] = settings
    lobby_state["selected_roles"] = data.get("roles", [])
    game_instance.settings = settings
    game_instance.ghost_mode = settings.get("ghost_mode", False)
    game_instance.mode = settings.get("mode", "standard")
    game_instance.isPassAndPlay = game_instance.mode == "pass_and_play"

    # Optional: Apply timer settings immediately if they exist
    timers_settings = settings.get("timers", {})
    game_instance.timer_durations = {
        "Night": int(timers_settings.get("night", GAME_DEFAULTS["TIME_NIGHT"])),
        "Accusation": int(
            timers_settings.get("accusation", GAME_DEFAULTS["TIME_ACCUSATION"])
        ),
        "Lynch_Vote": int(
            timers_settings.get("lynch_vote", GAME_DEFAULTS["TIME_LYNCH"])
        ),
    }
    game_instance.timers_disabled = timers_settings.get("timers_disabled", False)
    game_instance.players = {}
    for pid, obj in game["players"].items():
        game_instance.add_player(pid, obj.name)
    log_and_emit(f"===> Game Started! Mode: {game_instance.mode}")
    game_instance.assign_roles(data.get("roles", []))
    game["game_state"] = "started"
    socketio.emit("game_started", to=game["game_code"])
    game_instance.set_phase(PHASE_NIGHT)
    broadcast_game_state()


@socketio.on("admin_next_phase")
def handle_admin_next_phase(data=None):
    player_id, p = get_player_by_sid(request.sid)
    is_pnp = data.get("is_pnp", None) if data else None
    if not is_pnp:
        if not p or not p.is_admin:
            return

    current_phase = game_instance.phase
    log_and_emit(f"Admin is advancing the phase from {current_phase}.")
    if current_phase == PHASE_NIGHT:
        resolve_night()
    elif current_phase == PHASE_ACCUSATION:
        perform_tally_accusations()
    elif current_phase == PHASE_LYNCH:
        resolve_lynch()

def resolve_lynch():
    result = game_instance.resolve_lynch_vote()

    # 1. Handle Announcements (if any)
    if result.get("announcements"):
        for ann in result["announcements"]:
            game_instance.message_history.append(ann)
            socketio.emit("message", {"text": ann}, to=game["game_code"])

    # 2. Determine Primary Lynch Result
    msg = {"key": "events.lynch_fail", "variables": {}}
    if result.get("armor_save"):
        msg = {"key": "events.lynch_armor", "variables": {}}
    elif result["killed_id"]:
        name = game_instance.players[result["killed_id"]].name
        role = game_instance.players[result["killed_id"]].role.name_key
        msg = {
            "key": "events.lynch_success",
            "variables": {"name": name, "role": role}
        }

    # Attach summary (Voted Yes/No) to the message object
    if result.get("summary"):
        msg["summary"] = result["summary"]

    game_instance.message_history.append(msg)

    socketio.emit(
        "lynch_vote_result",
        {
            "message": msg,
            "summary": result["summary"],
            "killed_id": result["killed_id"],
        },
        to=game["game_code"],
    )

    # 3. Handle Secondary Deaths (Honeypot, Lovers, etc.)
    if result.get("secondary_deaths"):
        for d in result["secondary_deaths"]:
            # Attempt to find the role for the translation key (game engine might not send it in 'd')
            role_key = "Unknown"
            if "id" in d and d["id"] in game_instance.players:
                r = game_instance.players[d["id"]].role
                if r: role_key = r.name_key
            elif "role" in d:
                role_key = d["role"]

            reason_raw = d.get("reason", "")
            sec_msg = {}

            # Case A: Engine sent a ready-made Translation Object
            if isinstance(reason_raw, dict):
                sec_msg = reason_raw

            # Case B: Lovers Pact (Detect String -> Convert to Key)
            elif reason_raw == "Love Pact":
                sec_msg = {
                    "key": "events.death_love",
                    "variables": {"name": d["name"], "role": role_key}
                }

            # Case C: Honeypot (Detect String -> Convert to Key)
            elif "Honeypot" in str(reason_raw):
                # Remove the English prefix so we just display the mechanic/name if possible
                clean_reason = str(reason_raw).replace("Honeypot retaliation: ", "")
                sec_msg = {
                    "key": "events.death_honey",
                    "variables": {"name": d["name"], "role": role_key, "reason": clean_reason}
                }

            # Case D: Fallback (Generic Secondary Death)
            else:
                sec_msg = {
                    "key": "events.death_secondary",
                    "variables": {"name": d["name"], "reason": str(reason_raw)}
                }

            game_instance.message_history.append(sec_msg)
            socketio.emit("message", {"text": sec_msg}, to=game["game_code"])

    # 4. Update Wolf Team & Check Game Over
    living_wolves = game_instance.get_living_players("Werewolves")
    for werewolf in living_wolves:
        send_werewolf_info(werewolf.id)

    socketio.sleep(GAME_DEFAULTS["PAUSE_DURATION"])
    check_game_over_or_next_phase()

def check_game_over_or_next_phase():
    if game_instance.check_game_over():
        game_instance.phase = PHASE_GAME_OVER
        game["game_state"] = PHASE_GAME_OVER
        data = game_instance.game_over_data
        if data:
            game["game_over_data"] = data
            winner = data.get("winning_team", "Unknown")
            log_and_emit(f"Game Over! The {winner} have won.")
    else:
        game_instance.advance_phase()
    broadcast_game_state()


@socketio.on("admin_set_new_code")
def handle_admin_set_new_code(data):
    """Handles admin setting a new game code, keeping admin in lobby and kicking others."""
    if request.sid != game.get("admin_sid"):
        return
    new_code = data.get("new_code", "").strip().upper()
    if not new_code:
        return emit("error", {"message": "New code cannot be empty."})
    if not new_code.isalnum():
        return emit(
            "error", {"message": "Code must be alphanumeric (Letters/Numbers only)."}
        )
    if len(new_code) > 20:
        return emit("error", {"message": "Code must be 20 characters or fewer."})
    admin_id, admin_player = get_player_by_sid(request.sid)
    if not admin_player:
        return

    # Notify all OTHER players to re-login
    socketio.emit(
        "force_relogin",
        {"new_code": new_code},
        to=game["game_code"],
        skip_sid=request.sid,
    )
    global game_instance
    game_instance = Game("main_game_")
    # Reset the game, preserving only the admin
    admin_conn = game["players"][session["player_id"]]
    game["players"] = {session["player_id"]: admin_conn}
    game["game_code"] = new_code
    game["game_state"] = PHASE_LOBBY

    # Update the admin's lobby view
    join_room(new_code)
    broadcast_player_list()


def send_cupid_info(player_id, specific_sid=None):
    """
    Checks if the player has a lover and sends the cupid_info event.
    Can send to a specific SID (for PnP/Reconnects) or look up the current SID.
    """
    # 1. Get Engine Object
    engine_player_obj = game_instance.players.get(player_id)
    if not engine_player_obj or not engine_player_obj.linked_partner_id:
        return

    # 2. Get Partner Object
    partner_obj = game_instance.players.get(engine_player_obj.linked_partner_id)
    if not partner_obj:
        return

    # 3. Determine Target SID
    target_sid = specific_sid
    if not target_sid:
        player_wrapper = game["players"].get(player_id)
        if player_wrapper:
            target_sid = player_wrapper.sid

    # 4. Emit Event
    if target_sid:
        if not engine_player_obj.is_alive:
             msg = {
                "key": "events.cupid_info_dead",
                "variables": {"name": partner_obj.name}
            }
        else:
            msg = {
                "key": "events.cupid_info",
                "variables": {"name": partner_obj.name}
            }

        socketio.emit("cupid_info", {"message": msg}, to=target_sid)


def send_werewolf_info(player_id, specific_sid=None):
    """Sends the list of werewolf teammates to a specific player."""
    engine_player_obj = game_instance.players.get(player_id)
    if (
        not engine_player_obj
        or not engine_player_obj.role
        or engine_player_obj.role.team != "Werewolves"
    ):
        return

    living_werewolves = game_instance.get_living_players("Werewolves")
    teammate_names = [w.name for w in living_werewolves if w.id != player_id]

    target_sid = specific_sid
    if not target_sid:
        player_wrapper = game["players"].get(player_id)
        if player_wrapper:
            target_sid = player_wrapper.sid

    if target_sid:
        socketio.emit(
            "werewolf_team_info", {"teammates": teammate_names}, to=target_sid
        )


# --- PnP Specific Listeners ---
@socketio.on("pnp_request_state")
def handle_pnp_request(data):
    """
    Called when PnP device clicks a player button.
    Sends that specific player's FULL private state (using generator).
    """
    target_id = data.get("player_id")
    payload = generate_player_payload(target_id)
    if payload:
        emit("pnp_state_sync", payload)
        send_werewolf_info(target_id, specific_sid=request.sid)
        send_cupid_info(target_id, specific_sid=request.sid)


@socketio.on("pnp_submit_action")
def handle_pnp_action(data):
    """
    Unified action handler for Pass-and-Play.
    """
    print(f"handle_pnp_action")
    result = game_instance.receive_night_action(
        data.get("actor_id"), data.get("target_id")
    )
    if result == "RESOLVED":
        socketio.sleep(GAME_DEFAULTS["PAUSE_DURATION"])
        resolve_night()
    else:
        # Confirm receipt to client so they can show "Passed" screen
        emit("action_accepted", {}, to=request.sid)


@socketio.on("client_ready_for_game")
def handle_client_ready_for_game():
    """
    Syncs the game state for the specific client requesting it.
    """
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        return

    # OPTIMIZATION: Only update the requester, not the whole server
    player_wrapper = game["players"][player_id]
    payload = generate_player_payload(player_id, player_wrapper)

    if payload:
        emit("game_state_sync", payload, to=player_wrapper.sid)


@socketio.on("hero_choice")
def handle_hero_choice(data):
    player_id = session.get("player_id")
    # PnP Override
    if game_instance.mode == "pass_and_play" and "actor_id" in data:
        player_id = data["actor_id"]
    target_id = data.get("target_id")
    if target_id == "Nobody":
        result = game_instance.receive_night_action(player_id, "Nobody")
    else:
        result = game_instance.receive_night_action(player_id, data)
    if result == "ALREADY_ACTED":
        # In PnP, refresh the specific actor, otherwise broadcast
        if game_instance.mode == "pass_and_play":
            payload = generate_player_payload(player_id)
            if payload:
                return emit("pnp_state_sync", payload)
        return broadcast_game_state()
    if result == "IGNORED":
        return emit("error", {"message": "Action ignored."})
    if result == "RESOLVED":
        return resolve_night()
    player_obj = game_instance.players.get(player_id)
    if player_obj and player_obj.role.name_key in [
        ROLE_SEER,
        ROLE_RANDOM_SEER,
        ROLE_SORCERER,
    ]:
        # Immediate Seer Feedback (Standard Mode Feature)
        target_player_obj = game_instance.players.get(target_id)
        if target_player_obj and hasattr(player_obj.role, "investigate"):
            emit(
                "seer_result",
                {
                    "name": target_player_obj.name,
                    "role": player_obj.role.investigate(target_player_obj),
                },
            )
    if game_instance.mode == "pass_and_play":
        emit("pnp_action_confirmed", {})
        socketio.emit("pnp_player_done", {"player_id": player_id}, to=game["game_code"])
    else:
        broadcast_game_state()


@socketio.on("accuse_player")
def handle_accuse_player(data):
    pid = session.get("player_id")
    if game_instance.mode == "pass_and_play" and "actor_id" in data:
        pid = data["actor_id"]
    tid = data.get("target_id")
    all_voted = game_instance.process_accusation(pid, tid)
    # 2. Check what was recorded
    recorded_vote = game_instance.pending_actions.get(pid)
    if recorded_vote == "Ghost_Fail":
        # update ghost to "wails went unheard"
        emit("force_phase_update", to=request.sid)
    elif recorded_vote is not None:
        accuser = game_instance.players[pid]
        accuser_name = accuser.name
        if not accuser.is_alive:
            accuser_name = "👻Ghost"
        if tid:
            target = game_instance.players.get(tid)
            target_name = target.name if target else "Unknown"
        else:
            target_name = "Nobody"

        hist_msg = {
            "key": "events.accusation_made",
            "variables": {"accuser": accuser_name, "target": target_name},
        }
        game_instance.message_history.append(hist_msg)
        emit(
            "accusation_made",
            {
                "accuser_id": pid,
                "accuser_name": accuser_name,
                "accused_name": target_name,
                "accused_id": tid,
            },
            to=game["game_code"],
        )
    counts = Counter(game_instance.pending_actions.values())
    emit("accusation_update", counts, to=game["game_code"])
    if all_voted:
        perform_tally_accusations()
    elif game_instance.mode == "pass_and_play":
        emit("pnp_action_confirmed", {})
        socketio.emit("pnp_player_done", {"player_id": pid}, to=game["game_code"])


@socketio.on("cast_lynch_vote")
def handle_cast_lynch_vote(data):
    pid = session.get("player_id")
    if game_instance.mode == "pass_and_play" and "actor_id" in data:
        pid = data["actor_id"]
    all_voted = game_instance.cast_lynch_vote(pid, data.get("vote"))
    if all_voted:
        resolve_lynch()
    elif game_instance.mode == "pass_and_play":
        emit("pnp_action_confirmed", {})
        socketio.emit("pnp_player_done", {"player_id": pid}, to=game["game_code"])


# --- Resolution ---


def resolve_night():
    events = game_instance.resolve_night_deaths()

    # Notify Lovers
    for player_id in game_instance.players:
        send_cupid_info(player_id)

    # since deaths may also contain "armor_save"
    actual_death = False
    if events:
        for event in events:
            event_type = event.get("type", "death")

            if event_type == "armor_save":
                msg = {"key": "events.strangely", "variables": {}}
                game_instance.message_history.append(msg)
                socketio.emit("message", {"text": msg}, to=game["game_code"])

            elif event_type == "blocked":
                player_wrapper = game["players"].get(event["id"])
                if player_wrapper and player_wrapper.sid:
                    socketio.emit(
                        "message",
                        {"text": event['message'], "channel": "living"},
                        to=player_wrapper.sid,
                    )
            elif event_type == "announcement":
                msg = event["message"]
                game_instance.message_history.append(msg)
                socketio.emit(
                    "message",
                    {"text": msg},
                    to=game["game_code"],
                )
            elif event_type == "death":
                actual_death = True
                reason = event.get("reason", "Unknown")
                name = event.get("name", "Unknown")
                role = event.get("role", "Unknown")
                hist_msg = {
                    "key": "events.death_wolf",
                    "variables": {"name": name, "role": role},
                }
                if isinstance(reason, dict):
                    hist_msg = reason
                elif reason == "Werewolf meat":
                    hist_msg["key"] = "events.death_wolf"
                elif reason == "Witch Poison":
                    hist_msg["key"] = "events.death_witch"
                elif reason == "Love Pact":
                    hist_msg["key"] = "events.death_love"
                elif reason == "Retaliation":
                    hist_msg["key"] = "events.death_retaliation"
                elif reason == "revealed_werewolf":
                    hist_msg["key"] = "events.death_reveal_wolf"
                elif reason == "revealed_wrongly":
                    hist_msg["key"] = "events.death_reveal_human"
                elif reason == "Serial Killer":
                    hist_msg["key"] = "events.death_serial"
                elif "Honeypot" in reason:
                    hist_msg["key"] = "events.death_honey"
                    hist_msg["variables"]["reason"] = reason.replace(
                        "Honeypot retaliation: ", ""
                    )
                game_instance.message_history.append(hist_msg)

                socketio.emit(
                    "night_result_kill",
                    {
                        "killed_player": event,
                        "admin_only_chat": game_instance.admin_only_chat,
                        "phase": game_instance.phase,
                        "message": hist_msg,
                    },
                    to=game["game_code"],
                )
                # msg werewolf teamates in case Wild_Child joined
                living_wolves = game_instance.get_living_players("Werewolves")
                for werewolf in living_wolves:
                    send_werewolf_info(werewolf.id)

    if not actual_death:
        msg = {"key": "events.sun_rise_safe", "variables": {}}
        game_instance.message_history.append(msg)
        socketio.emit("message", {"text": msg}, to=game["game_code"])

    socketio.sleep(GAME_DEFAULTS["PAUSE_DURATION"])
    check_game_over_or_next_phase()


@socketio.on("vote_to_end_day")
def handle_vote_to_end_day(data=None):
    pid = session.get("player_id")
    # PnP Override
    if data and game_instance.mode == "pass_and_play" and "actor_id" in data:
        pid = data["actor_id"]

    # 1. Get the Engine Player Object
    engine_player = game_instance.players.get(pid)
    if not engine_player:
        return

    # 2. Strict Liveness Check
    # Only ALIVE players should control the day/night cycle speed.
    if not engine_player.is_alive:
        return
    if game_instance.phase != PHASE_ACCUSATION:
        return

    # 4. Add Vote (Manually add to the set)
    game_instance.end_day_votes.add(pid)
    living_count = len(game_instance.get_living_players())
    votes_count = len(game_instance.end_day_votes)
    majority = votes_count > (living_count / 2)
    emit(
        "end_day_vote_update",
        {"count": votes_count, "total": living_count},
        to=game["game_code"],
    )
    if majority:
        perform_tally_accusations()
    elif game_instance.mode == "pass_and_play":
        emit("pnp_action_confirmed", {})


# handle voting process after game ends. tracks votes, upon
# majority , resets game state and redirects all to lobby
@socketio.on("vote_for_rematch")
def handle_vote_for_rematch():
    global game_instance
    player_id, p = get_player_by_sid(request.sid)
    if not p or game["game_state"] != PHASE_GAME_OVER:
        return
    if player_id not in game_instance.rematch_votes:
        game_instance.rematch_votes.add(player_id)
        num_votes = len(game_instance.rematch_votes)
        total_players = len(game["players"])
        if num_votes > total_players / 2 or p.is_admin:
            old_settings = getattr(game_instance, "settings", {})
            game_instance = Game("main_game", settings=old_settings)
            game_instance.players = {}
            for pid, obj in game["players"].items():
                game_instance.add_player(pid, obj.name)
            game["game_state"] = PHASE_LOBBY
            game["game_over_data"] = None
            socketio.emit("redirect_to_lobby", {}, to=game["game_code"])
            broadcast_player_list()
        else:
            # Broadcast the current vote count
            payload = {"count": num_votes, "total": total_players}
            emit("rematch_vote_update", payload, to=game["game_code"])


# for android
def run_server(port_number):
    try:
        port = int(port_number) if port_number else 5000
    except (ValueError, TypeError):
        port = 5000

    print(f"Starting server on port {port}...")

    try:
        # Keep debug=False to avoid the process reloader crash
        socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True, debug=False)
    except Exception as e:
        # This will show up in 'adb logcat -s python.stdout python.stderr'
        print("-" * 30)
        print(f"PYTHON SERVER CRASHED: {e}")
        traceback.print_exc()
        print("-" * 30)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", debug=False, allow_unsafe_werkzeug=True)
