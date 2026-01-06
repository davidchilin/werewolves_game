"""
app.py
Version: 4.8.4
"""
import logging
import os
import time
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

from config import *
from game_engine import *
from roles import *

# --- App Initialization ---
load_dotenv(find_dotenv(filename=".env.werewolves"))

app = Flask(__name__)
# IMPORTANT: In production, this MUST be set as an environment variable.
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY", "omiunhbybt7vr6c53wz3523c2r445ybF4y6jmo8o8p"
)
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

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

# Game Dictionary stores connection/wrapper info
game = {
    "admin_sid": None,
    "game_code": "W",
    "game_state": PHASE_LOBBY,
    "players": {},  # Dict[player_id(uuid), PlayerWrapper_Obj]
}

lobby_state = {
    "selected_roles": ["Villager", "Werewolf", "Seer"],
    "settings": {},
}


class PlayerWrapper:
    def __init__(self, name, sid):
        self.name = name
        self.sid = sid
        self.is_admin = False


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


def generate_player_payload(player_id, player_wrapper=None):
    """
    Generates the specific game state payload for a given player ID.
    Used for both standard broadcasts and PnP impersonation.
    """
    # 1. Global Public Data
    try:
        all_players_data = [
            {"id": p.id, "name": p.name, "is_alive": p.is_alive}
            for p in game_instance.players.values()
        ]
        accusation_counts = {}
        if game_instance.phase == PHASE_ACCUSATION:
            accusation_counts = dict(Counter(game_instance.accusations.values()))
    except Exception as e:
        print(f"DEBUG ERROR in Public Data: {e}")
        return None

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

    # 2. Private Data (Specific to the requested player_id)
    engine_player_obj = game_instance.players.get(player_id)
    if not engine_player_obj:
        return None

    role_str = "Unknown"
    is_alive = engine_player_obj.is_alive
    night_ui = None

    if engine_player_obj.role:
        role_str = engine_player_obj.role.name_key

    if (
        game_instance.phase == PHASE_NIGHT
        and engine_player_obj.role
        and engine_player_obj.is_alive
    ):
        ctx = {
            "players": list(game_instance.players.values()),
            "villager_promt_index": game_instance.get_current_prompt_index(),
        }
        night_ui = engine_player_obj.role.get_night_ui_schema(engine_player_obj, ctx)


    acted_ids = []
    if game_instance.phase == PHASE_NIGHT:
        acted_ids = list(game_instance.turn_history)
    elif game_instance.phase == PHASE_ACCUSATION:
        # In Accusation, acting = Accusing someone OR Voting to sleep
        acted_ids = list(set(game_instance.accusations.keys()) | game_instance.end_day_votes)
    elif game_instance.phase == PHASE_LYNCH:
        acted_ids = list(game_instance.lynch_votes.keys())

    # Retrieve Player Actions
    my_night_target_id = game_instance.get_player_night_choice(player_id)
    my_night_metadata = game_instance.get_player_night_metadata(player_id)
    my_accusation_id = game_instance.get_player_accusation(player_id)
    my_lynch_vote = game_instance.get_player_lynch_vote(player_id)
    my_sleep_vote = game_instance.has_player_voted_to_sleep(player_id)

    # Resolve Names
    my_night_target_name = None
    if my_night_target_id:
        target_obj = game_instance.players.get(my_night_target_id)
        if target_obj:
            my_night_target_name = target_obj.name

    my_accusation_name = None
    if my_accusation_id:
        target_obj = game_instance.players.get(my_accusation_id)
        if target_obj:
            my_accusation_name = target_obj.name

    valid_targets_data = []
    if engine_player_obj.role:
        targets = engine_player_obj.role.get_valid_targets(
            {"players": list(game_instance.players.values())}
        )
        valid_targets_data = [{"id": t.id, "name": t.name} for t in targets]

    # 3. Admin Status
    # If a wrapper was passed (broadcast), use it. If not (PnP request), check global dict
    is_admin = False
    if player_wrapper:
        is_admin = player_wrapper.is_admin
    else:
        # Fallback look up
        wrapper = game["players"].get(player_id)
        if wrapper:
            is_admin = wrapper.is_admin

    return {
        "accusation_counts": accusation_counts,
        "acted_players": acted_ids,
        "admin_only_chat": game_instance.admin_only_chat,
        "all_players": all_players_data,
        "duration": remaining_time,
        "game_over_data": game_instance.game_over_data,
        "ghost_mode_active": game_instance.is_ghost_mode_active(),
        "is_admin": is_admin,
        "is_alive": is_alive,
        "living_players": [
            {"id": p.id, "name": p.name} for p in game_instance.get_living_players()
        ],
        "lynch_target_id": game_instance.lynch_target_id,
        "lynch_target_name": lynch_target_name,
        "message_history": game_instance.message_history,
        "mode": game_instance.mode,
        "my_accusation_id": my_accusation_id,
        "my_accusation_name": my_accusation_name,
        "my_lynch_vote": my_lynch_vote,
        "my_night_target_id": my_night_target_id,
        "my_night_metadata": my_night_metadata,
        "my_night_target_name": my_night_target_name,
        "my_rematch_vote": player_id in game_instance.rematch_votes,
        "my_sleep_vote": my_sleep_vote,
        "night_ui": night_ui,
        "phase": game_instance.phase,
        "phase_end_time": game_instance.phase_end_time,
        "rematch_vote_count": len(game_instance.rematch_votes),
        "sleep_vote_count": len(game_instance.end_day_votes),
        "this_player_id": player_id,
        "timers_disabled": game_instance.timers_disabled,
        "total_accusation_duration": game_instance.timer_durations.get(
            PHASE_ACCUSATION, 90
        ),
        "valid_targets": valid_targets_data,
        "your_role": role_str,
    }


def broadcast_game_state():
    """Syncs the FULL Engine state to all clients."""
    for player_id, player_wrapper in game["players"].items():
        if not player_wrapper.sid:
            continue
        payload = generate_player_payload(player_id, player_wrapper)
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
            socketio.emit("message", {"text": outcome["message"]}, to=game["game_code"])
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
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(4)
        game_instance.set_phase(PHASE_ACCUSATION)
        broadcast_game_state()
    elif result_type == "night":
        # No Accusations / Deadlock -> Sleep
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(4)
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
        name = request.form.get("name", "").strip()
        code = request.form.get("game_code", "").strip().upper()
        if not name:
            return render_template("index.html", error="name is required.")
        if code != game["game_code"]:
            return render_template("index.html", error="Invalid game code.")
        for p in game["players"].values():
            if p.name.lower() == name.lower():
                return render_template("index.html", error="Name is already taken.")
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


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.root_path, "favicon.ico", mimetype="image/vnd.microsoft.icon"
    )


@app.route("/get_roles")
def get_roles():
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
    log_and_emit(f"===> A client connected. SID: {request.sid}")
    player_id = session.get("player_id")
    if not player_id:
        return

    # This logic handles both new players joining the lobby and existing players reconnecting.
    if player_id not in game["players"]:
        if game["game_state"] != PHASE_LOBBY:
            return emit("error", {"message": "Game in progress."})
        new_player = PlayerWrapper(session.get("name"), request.sid)
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


@socketio.on("send_message")
def handle_send_message(data):
    pid, p = get_player_by_sid(request.sid)
    if not p:
        return
    msg = data.get("message", "").strip()
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
                emit(
                    "message",
                    {
                        "text": f"shhh...the village is sleeping quietly, <strong>{p.name}</strong>"
                    },
                )
            else:
                emit("message", {"text": "Chat is currently restricted."})
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


@socketio.on("admin_set_timers")
def handle_admin_set_timers(data):
    if request.sid != game["admin_sid"]:
        return
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
    if request.sid != game.get("admin_sid"):
        return emit("error", {"message": "Only the admin can start the game."})
    if len(game["players"]) < 4:
        return emit("error", {"message": "Cannot start with fewer than 4 players."})
    if game.get("game_state") != PHASE_LOBBY:
        return emit("error", {"message": "Game is already in progress."})
    log_and_emit("===> Admin started game. Assigning roles.")
    global game_loop_running
    if not game_loop_running:
        game_loop_running = True
        socketio.start_background_task(background_game_loop)
    # configure engine
    settings = data.get("settings", {})
    lobby_state["settings"] = settings
    lobby_state["selected_roles"] = data.get("roles", [])
    game_instance.settings = settings
    game_instance.ghost_mode = settings.get("ghost_mode", False)
    game_instance.mode = settings.get("mode", "standard")
    game_instance.isPassAndPlay = game_instance.mode == "pass_and_play"

    # Optional: Apply timer settings immediately if they exist
    timers_settings = settings.get("timers", {})
    game_instance.timer_durations = {
        "Night": int(timers_settings.get("night", 90)),
        "Accusation": int(timers_settings.get("accusation", 90)),
        "Lynch_Vote": int(timers_settings.get("lynch_vote", 30)),
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
def handle_admin_next_phase():
    player_id, p = get_player_by_sid(request.sid)
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
    if result.get("announcements"):
        for ann in result["announcements"]:
            game_instance.message_history.append(ann)
            socketio.emit("message", {"text": ann}, to=game["game_code"])
    msg = "No one was lynched 🕊️"
    if result.get("armor_save"):
        msg = "⚖️ The village voted to lynch, but... <strong>strangely, nobody dies.</strong>"
    elif result["killed_id"]:
        name = game_instance.players[result["killed_id"]].name
        role = game_instance.players[result["killed_id"]].role.name_key
        msg = f"⚖️ <strong>{name}</strong> was lynched! They were a <strong>{role}</strong> ⚰️"
    socketio.emit(
        "lynch_vote_result",
        {
            "message": msg,
            "summary": result["summary"],
            "killed_id": result["killed_id"],
        },
        to=game["game_code"],
    )
    if result.get("secondary_deaths"):
        for d in result["secondary_deaths"]:
            print(
                "%%%%%%%%%%%%%%%%%%%%%%%%%%% secondary_deaths game loop %%%%%%%%%%%%%%%%%%%"
            )
            sec_msg = f"☠️ <strong>{d['name']}</strong> died as well! Reason: {d['reason']} ⚰️"
            if "Honeypot" in d["reason"]:
                clean_reason = d["reason"].replace("Honeypot retaliation: ", "")
                # Clean up UUIDs if present in the message
                sec_msg = f"🍯 <strong>{d['name']}</strong> was dragged down by the Honeypot! {clean_reason} 🐝"
            elif d["reason"] == "Love Pact":
                sec_msg = f"💔 <strong>{d['name']}</strong> died of a broken heart!"
            game_instance.message_history.append(sec_msg)
            socketio.emit("message", {"text": sec_msg}, to=game["game_code"])

    # Message werewolves teammates names
    living_wolves = game_instance.get_living_players("Werewolves")
    for werewolf in living_wolves:
        send_werewolf_info(werewolf.id)
    socketio.sleep(5)
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


def send_werewolf_info(player_id):
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
    player_wrapper = game["players"].get(player_id)
    if player_wrapper and player_wrapper.sid:
        socketio.emit(
            "werewolf_team_info", {"teammates": teammate_names}, to=player_wrapper.sid
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


@socketio.on("pnp_submit_action")
def handle_pnp_action(data):
    """
    Unified action handler for Pass-and-Play.
    """
    result = game_instance.receive_night_action(
        data.get("actor_id"), data.get("target_id")
    )
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
    broadcast_game_state()


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
    recorded_vote = game_instance.accusations.get(pid)
    if recorded_vote == "Ghost_Fail":
        # update ghost to "wails went unheard"
        emit("force_phase_update", to=request.sid)
    elif recorded_vote:
        accuser = game_instance.players[pid]
        accuser_name = accuser.name
        if not accuser.is_alive:
            accuser_name = "👻Ghost"
        if tid:
            target = game_instance.players.get(tid)
            target_name = target.name if target else "Unknown"
        else:
            target_name = "Nobody"
        emit(
            "accusation_made",
            {
                "accuser_id": pid,
                "accuser_name": accuser_name,
                "accused_name": target_name,
            },
            to=game["game_code"],
        )
    counts = Counter(game_instance.accusations.values())
    emit("accusation_update", counts, to=game["game_code"])
    if all_voted:
        perform_tally_accusations()
    elif game_instance.mode == "pass_and_play":
        emit("pnp_action_confirmed", {})


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


# --- Resolution ---


def resolve_night():
    events = game_instance.resolve_night_deaths()

    # Notify Lovers
    for player_id, player_obj in game_instance.players.items():
        if player_obj.linked_partner_id:
            partner_obj = game_instance.players.get(player_obj.linked_partner_id)
            if partner_obj:
                player_wrapper = game["players"].get(player_id)
                if player_wrapper and player_wrapper.sid:
                    status_msg = ""
                    if not player_obj.is_alive:
                        status_msg = "You died, but you should know... "
                    socketio.emit(
                        "message",
                        {
                            "text": f"{status_msg}💘 You are in love with <strong>{partner_obj.name}</strong>! If one dies, you both die.",
                            "channel": "living",
                        },
                        to=player_wrapper.sid,
                    )

    # since deaths may also contain "armor_save"
    actual_death = False
    if events:
        for event in events:
            event_type = event.get("type", "death")

            if event_type == "armor_save":
                msg = "<strong>Strangely, nobody dies...</strong>"
                game_instance.message_history.append(msg)
                socketio.emit("message", {"text": msg}, to=game["game_code"])

            elif event_type == "blocked":
                player_wrapper = game["players"].get(event["id"])
                if player_wrapper and player_wrapper.sid:
                    socketio.emit(
                        "message",
                        {"text": f"{event['message']}", "channel": "living"},
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
                hist_msg = reason
                if reason == "Werewolf meat":
                    hist_msg = f"🐾 Remnants of a body were found! <strong>{name}</strong> was killed 🫀 They were a <strong>{role}</strong> ⚰️"
                if reason == "Witch Poison":
                    hist_msg = f"☣️ A dissolving body was found! ☠ <strong>{name}</strong> was killed. Role: {role} ⚰️"
                elif reason == "Love Pact":
                    hist_msg = f"💕 <strong>{name}</strong> died of a broken heart! 😈 Role: {role} ⚰️"
                elif reason == "Retaliation":
                    hist_msg = f"☠ <strong>{name}</strong> fucked with the wrong person! They were a <strong>{role}</strong> ⚰️"
                elif reason == "revealed_werewolf":
                    hist_msg = f"☠ <strong>{name}</strong> was revealed to be a <strong>{role}</strong> and strung up! ⚰️"
                elif reason == "revealed_wrongly":
                    hist_msg = f"☠ <strong>{name}</strong> revealed a <strong>Villager</strong> and died of embarrassment! ⚰️"
                elif reason == "Serial Killer":
                    hist_msg = f"🔪 A mutilated body was found! <strong>{name}</strong> was the victim of a <strong>Serial Killer</strong>! 🩸 They were a <strong>{role}</strong> ⚰️"
                elif "Honeypot" in reason:
                    # Clean up prefix for display if needed
                    clean_reason = reason.replace("Honeypot retaliation: ", "")
                    hist_msg = f"🍯 <strong>{role} {name}</strong> fell into a trap! {clean_reason} 🐝"

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

                living_wolves = game_instance.get_living_players("Werewolves")
                for werewolf in living_wolves:
                    send_werewolf_info(werewolf.id)
    # todo delete game.html night_result_no_kill function
    if not actual_death:
        msg = "🌞 The sun rises, and no one was killed."
        socketio.emit("message", {"text": msg}, to=game["game_code"])

    socketio.sleep(4)  # Short pause for effect
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


if __name__ == "__main__":
    # This block is for local development only and will not be used by Gunicorn
    socketio.run(app, host="0.0.0.0", debug=True, allow_unsafe_werkzeug=True)
