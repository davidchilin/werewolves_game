"""
app.py
Version: 4.4.5
"""
from collections import Counter
from dotenv import load_dotenv, find_dotenv
import os
import time
import uuid
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
from flask_socketio import SocketIO, join_room, emit
from config import *
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
    "admin_sid": None,
    "game_code": "W",
    "game_state": PHASE_LOBBY,  # started night accusation_phase lynch_vote_phase ended
    "players": {},  # dictionary mapping player_id (UUID string) to Player objects
}


class PlayerWrapper:
    def __init__(self, username, sid):
        self.username = username
        self.sid = sid
        self.is_admin = False


# --- Helper Functions ---
def get_player_by_sid(sid):
    for player_id, p in game["players"].items():
        if p.sid == sid:
            return player_id, p
    return None, None


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

        player_list.append(
            {
                "id": pid,
                "username": conn.username,
                "is_admin": conn.is_admin,
                "is_alive": is_alive,
            }
        )

    socketio.emit(
        "update_player_list",
        {
            "players": player_list,
            "game_code": game["game_code"],
            "admin_only_chat": game_instance.admin_only_chat,
        },
        to=game["game_code"],
    )


def broadcast_game_state():
    """Syncs the FULL Engine state to all clients."""
    # 1. Public Data
    print("DEBUG: Starting broadcast_game_state...")
    try:
        all_players = [
            {"id": p.id, "username": p.name} for p in game_instance.players.values()
        ]
        if game_instance.phase == PHASE_ACCUSATION:
            accusation_counts = dict(Counter(game_instance.accusations.values()))
        else:
            accusation_counts = {}
    except Exception as e:
        print(f"DEBUG ERROR in Public Data: {e}")
        return

    # 2. Timer Calculation
    remaining = 0
    if game_instance.phase_start_time and not game_instance.timers_disabled:
        # Map Engine Phase to Config Key
        p_map = {
            "NIGHT": "night",
            "ACCUSATION_PHASE": "accusation",
            "LYNCH_VOTE_PHASE": "lynch_vote",
        }
        key = p_map.get(game_instance.phase)
        if key and key in game_instance.timer_durations:
            elapsed = time.time() - game_instance.phase_start_time
            remaining = max(0, game_instance.timer_durations[key] - elapsed)

    lynch_target_name = None
    if game_instance.lynch_target_id:
        t = game_instance.players.get(game_instance.lynch_target_id)
        if t:
            lynch_target_name = t.name

    # 3. Private Data (Sent individually)
    # todo: should we do this for all player, or only to (specific player)
    for pid, conn in game["players"].items():
        if not conn.sid:
            print(f"DEBUG: Skipping {conn.username} (No SID)")
            continue

        engine_p = game_instance.players.get(pid)
        role_str, is_alive = ROLE_VILLAGER, True

        if engine_p:
            is_alive = engine_p.is_alive
            role_str = engine_p.role.name_key if engine_p.role else "Unknown"
        else:
            print(f"DEBUG WARNING: Player {conn.username} ({pid}) not found in Engine!")
        # --- NEW: Retrieve Actions for ALL phases ---
        my_night_target = game_instance.get_player_night_choice(pid)
        my_accusation = game_instance.get_player_accusation(pid)
        my_lynch_vote = game_instance.get_player_lynch_vote(pid)
        my_sleep_vote = game_instance.has_player_voted_to_sleep(pid)

        my_night_target_name = None
        if my_night_target:
            t = game_instance.players.get(my_night_target)
            if t:
                my_night_target_name = t.name

        my_accusation_name = None
        if my_accusation:
            t = game_instance.players.get(my_accusation)
            if t:
                my_accusation_name = t.name

        my_rematch_vote = pid in game_instance.rematch_votes
        rematch_count = len(game_instance.rematch_votes)

        payload = {
            "accusation_counts": accusation_counts,
            "admin_only_chat": game_instance.admin_only_chat,
            "all_players": all_players,
            "duration": remaining,
            "game_over_data": game_instance.game_over_data,
            "is_admin": conn.is_admin,
            "is_alive": is_alive,
            "living_players": [
                {"id": p.id, "username": p.name}
                for p in game_instance.get_living_players()
            ],
            "lynch_target_id": game_instance.lynch_target_id,
            "lynch_target_name": lynch_target_name,
            "mode": game_instance.mode,  # Standard or pass_and_play
            "my_accusation_id": my_accusation,
            "my_accusation_name": my_accusation_name,
            "my_lynch_vote": my_lynch_vote,
            "my_night_target_id": my_night_target,
            "my_night_target_name": my_night_target_name,
            "my_rematch_vote": my_rematch_vote,
            "my_sleep_vote": my_sleep_vote,
            "phase": game_instance.phase,
            "phase_end_time": game_instance.phase_end_time,
            "rematch_vote_count": rematch_count,
            "sleep_vote_count": len(game_instance.end_day_votes),
            "timers_disabled": game_instance.timers_disabled,
            "total_accusation_duration": game_instance.timer_durations.get(
                "accusation", 90
            ),
            "your_role": role_str,
        }

        socketio.emit("game_state_sync", payload, to=conn.sid)

    print("DEBUG: Broadcast complete.")


# --- Timer System ---

game_loop_running = False


def background_game_loop():
    """Central heartbeat that ticks the engine every second."""
    global game_loop_running
    print(">>> Game Loop Started <<<")

    while game_loop_running:
        socketio.sleep(1)  # Sleep 1 second

        with app.app_context():
            # 1. Tick the Engine
            result = game_instance.tick()

            # 2. Handle Timeout Event
            if result == "TIMEOUT":
                log_and_emit(f"Timer expired for {game_instance.phase}.")

                # Logic moved from old timer_task
                if game_instance.phase == PHASE_NIGHT:
                    resolve_night()
                elif game_instance.phase == PHASE_ACCUSATION:
                    perform_tally_accusations()
                elif game_instance.phase == PHASE_LYNCH:
                    resolve_lynch()


def perform_tally_accusations():
    # 1. Engine Calculation
    outcome = game_instance.tally_accusations()
    res_type = outcome["result"]

    # 2. Handle Outcome
    if res_type == "trial":
        # Trial Started
        socketio.emit(
            "lynch_vote_started",
            {
                "target_id": outcome["target_id"],
                "target_name": outcome["target_name"],
                "duration": game_instance.timer_durations[PHASE_LYNCH],
            },
            to=game["game_code"],
        )

    elif res_type == "restart":
        # Tie - Restart Accusations
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(3)
        game_instance.set_phase(PHASE_ACCUSATION)  # Engine handles internal reset
        broadcast_game_state()

    elif res_type == "night":
        # No Accusations / Deadlock -> Sleep
        socketio.emit(
            "lynch_vote_result", {"message": outcome["message"]}, to=game["game_code"]
        )
        socketio.sleep(3)
        game_instance.set_phase(PHASE_NIGHT)
        broadcast_game_state()


# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    # returning player redirect to game or lobby
    if "player_id" in session and session["player_id"] in game["players"]:
        return (
            redirect(url_for("game_page"))
            if game["game_state"] != PHASE_LOBBY
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
        app.root_path,
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route("/get_roles")
def get_roles():
    """API to send available roles to the frontend to generate checkboxes."""
    # Convert the Roles Registry into a list of dicts
    # role_list = []
    # for role_name, role_class in AVAILABLE_ROLES.items():
    #    # Instantiate a temp object just to read metadata
    #    temp_role = role_class()
    #    role_list.append(temp_role.to_dict())
    # return jsonify(role_list)
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
        if game["game_state"] != PHASE_LOBBY:
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
    if game["game_state"] == PHASE_LOBBY:
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
@socketio.on("join_game")
def on_join(data):
    room = data["room"]
    join_room(room)
    # Get current players from the Game Engine
    # Assuming game_instance is retrieved based on room ID

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

    # 1. Determine Context
    # Check Phase on Engine
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
                        "text": f"shhh...the village is sleeping quietly, <strong>{p.username}</strong>"
                    },
                )
            else:
                emit("message", {"text": "Chat is currently restricted."})
        return

    # 3. Determine Channel (Lobby vs Living vs Ghost)
    channel = "lobby"

    # Only separate chats if the game is actively running (Day Phases)
    # If Phase is LOBBY or GAME_OVER/ended, everyone talks in 'lobby' channel
    active_phases = [PHASE_ACCUSATION, PHASE_LYNCH]

    if phase in active_phases:
        engine_p = game_instance.players.get(pid)
        if engine_p:
            channel = "living" if engine_p.is_alive else "ghost"

    # 4. Broadcast
    socketio.emit(
        "new_message",
        {"text": f"<strong>{p.username}:</strong> {msg}", "channel": channel},
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
            "timer_day": PHASE_ACCUSATION,  # Day = Accusation Phase
            "timer_night": PHASE_NIGHT,  # Night = Night Phase
            "timer_vote": PHASE_LYNCH,  # Vote = Lynch Phase
        }

        for frontend_key, engine_phase_key in key_map.items():
            val = data.get(frontend_key)
            if val:
                try:
                    new_duration = int(val)
                    final_duration = max(10, new_duration)
                    game_instance.timer_durations[engine_phase_key] = final_duration
                    updated_timers[engine_phase_key] = final_duration
                except ValueError:
                    pass

        # Update durations
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
        # leave_room(game["game_code"], sid=sid)
        # broadcast_player_list()
    if player_id in game_instance.players:
        del game_instance.players[player_id]


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

    # conigure engine
    game_instance.mode = data.get("settings", {}).get("mode", "standard")
    game_instance.players = {}
    for pid, obj in game["players"].items():
        game_instance.add_player(pid, obj.username)

    # game["players_ready_for_game"] = set()
    log_and_emit(f"===> Game Started! Mode: {game_instance.mode}")

    game_instance.assign_roles(data.get("roles", []))
    game["game_state"] = "started"
    socketio.emit("game_started", to=game["game_code"])

    # 3. Transition to Night
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
    # 1. Engine Calculation
    result = game_instance.resolve_lynch_vote()

    # 2. Notify
    msg = "No one was lynched."
    if result["killed_id"]:
        name = game_instance.players[result["killed_id"]].name
        role = game_instance.players[result["killed_id"]].role.name_key
        msg = f"⚖️ <strong>{name}</strong> was lynched! Role: {role} ⚰️"

    socketio.emit(
        "lynch_vote_result",
        {
            "message": msg,
            "summary": result["summary"],
            "killed_id": result["killed_id"],
        },
        to=game["game_code"],
    )

    socketio.sleep(5)
    check_game_over_or_next_phase()


def check_game_over_or_next_phase():
    if game_instance.check_game_over():
        # GAME OVER
        game_instance.phase = PHASE_GAME_OVER
        game["game_state"] = PHASE_GAME_OVER
        data = game_instance.game_over_data  # Sync for refresh
        if data:
            game["game_over_data"] = data
            winner = data.get("winning_team", "Unknown")
            log_and_emit(f"Game Over! The {winner} have won.")
        broadcast_game_state()  # Will send game_over_data present in Engine
    else:
        # Check engine's current phase to determine next step.
        # Actually, Engine `resolve_lynch` sets phase to NIGHT automatically.
        # Engine `resolve_night` does NOT set phase to Day automatically in our design (it returns deaths).

        if game_instance.phase == PHASE_NIGHT:
            # Night just finished -> Day
            game_instance.set_phase(PHASE_ACCUSATION)
            broadcast_game_state()
        elif game_instance.phase == PHASE_LYNCH:
            # Lynch just finished -> Engine already set phase to NIGHT
            game_instance.set_phase(PHASE_NIGHT)
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


@socketio.on("pnp_request_state")
def handle_pnp_request(data):
    """
    Called when a player confirms identity in Pass-and-Play.
    Returns their specific role data and valid targets.
    """
    player = game_instance.players.get(data.get("player_id"))
    if player:
        targets = player.role.get_valid_targets(
            player, {"players": list(game_instance.players.values())}
        )
        prompt = getattr(player.role, "night_prompt", "Choose a target")

        emit(
            "pnp_state_received",
            {
                "id": player.id,
                "role_name": player.role.name_key,
                "prompt": prompt,
                "targets": [{"id": t.id, "name": t.name} for t in targets],
            },
        )


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

    # Just broadcast the state so the UI updates
    broadcast_game_state()


@socketio.on("wolf_choice")
def handle_wolf_choice(data):
    player_id = session.get("player_id")
    result = game_instance.receive_night_action(player_id, data.get("target_id"))
    if result == "ALREADY_ACTED":
        # refresh the UI and show their previous choice.
        return broadcast_game_state()
    if result == "RESOLVED":
        resolve_night()

    # If successful (PENDING), we must update the UI to show they've submitted
    broadcast_game_state()


@socketio.on("seer_choice")
def handle_seer_choice(data):
    player_id = session.get("player_id")
    target_id = data.get("target_id")
    result = game_instance.receive_night_action(player_id, target_id)

    if result == "ALREADY_ACTED":
        return broadcast_game_state()

    # Immediate Seer Feedback (Standard Mode Feature)
    if result != "RESOLVED":
        target = game_instance.players.get(target_id)
        if target:
            is_werewolf = (
                target.role.team == "werewolf" or target.role.team == "monster"
            )
            emit(
                "seer_result",
                {
                    "username": target.name,
                    "role": ROLE_WEREWOLF if is_werewolf else ROLE_VILLAGER,
                },
            )


@socketio.on("accuse_player")
def handle_accuse_player(data):
    pid = session.get("player_id")
    tid = data.get("target_id")

    # 1. Update Engine
    all_voted = game_instance.process_accusation(pid, tid)

    # 2. Broadcast Update
    accuser = game_instance.players[pid]
    if tid:
        target = game_instance.players.get(tid)
        target_name = target.name if target else "Unknown"
    else:
        target_name = "Nobody"

    emit(
        "accusation_made",
        {"accuser_name": accuser.name, "accused_name": target_name},
        to=game["game_code"],
    )

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
            socketio.emit(
                "night_result_kill",
                {
                    "killed_player": {
                        "id": p.id,
                        "username": p.name,
                        "role": p.role.name_key,
                    }
                },
                to=game["game_code"],
            )
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
    if not p or game["game_state"] != PHASE_GAME_OVER:
        return

    if player_id not in game_instance.rematch_votes:
        game_instance.rematch_votes.add(player_id)

        num_votes = len(game_instance.rematch_votes)
        total_players = len(game["players"])

        # Check if a majority has been reached or admin forces
        if num_votes > total_players / 2 or p.is_admin:
            old_mode = game_instance.mode
            game_instance = Game("main_game", mode=old_mode)
            game["game_state"] = PHASE_GAME_OVER
            game["game_over_data"] = None

            socketio.emit("redirect_to_lobby", {}, to=game["game_code"])
        else:
            # Broadcast the current vote count
            payload = {"count": num_votes, "total": total_players}
            emit("rematch_vote_update", payload, to=game["game_code"])


if __name__ == "__main__":
    # This block is for local development only and will not be used by Gunicorn
    socketio.run(app, host="0.0.0.0", debug=True, allow_unsafe_werkzeug=True)
