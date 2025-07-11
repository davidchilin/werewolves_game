# Version: 1.10.0
# gemini final version phase 5
import os
import random
from collections import Counter
from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    send_from_directory,
)
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid

# --- App Initialization ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "a-very-secret-key-that-is-long-and-random"
)
socketio = SocketIO(app)

# --- Game State ---
game = {
    "players": {},  # dictionary mapping player_id (UUID string) to Player objects
    "game_state": "waiting",  # started night accusation_phase lynch_vote_phase ended
    "players_ready_for_game": set(),  # ready player_ids
    "admin_sid": None,
    "game_code": "W",
    "night_wolf_choices": {},  # dictionary wolf player_ids to chosen target_id kill
    "night_seer_choice": None,
    "seer_investigated": False,
    "accusations": {},  # dictionary player_ids to accused target_id for lynch_vote
    "accusation_restarts": 0,
    "end_day_votes": set(),  # set player_ids
    "lynch_target_id": None,
    "lynch_votes": {},  # dictionary player_ids to yes/no
    "accusation_timer": None,
    "lynch_vote_timer": None,
    "night_timer": None,
    # dictionary storing duration (in seconds) for each game phase timer
    "timer_durations": {"night": 90, "accusation": 90, "lynch_vote": 60},
    # A unique, incrementing ID for each timer instance to prevent old timers from firing.
    "current_timer_id": 0,
    "rematch_votes": set(),  # set player_ids for game_over rematch
}


# --- Player Class ---
class Player:
    def __init__(self, username, sid):
        # unique, persistent identifier for the player, stored in session
        self.id = session.get("player_id")
        self.username = username
        # player's current SocketIO session ID. Changes on reconnect
        self.sid = sid
        self.role = None  # 'villager', 'wolf', 'seer'
        self.is_alive = True
        self.is_admin = False


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
    socketio.emit("log_message", {"text": message}, room=game["game_code"])


def broadcast_player_list():
    if game["game_state"] != "waiting":
        return
    player_list = [
        {"id": p.id, "username": p.username, "is_admin": p.is_admin}
        for p in game["players"].values()
    ]
    socketio.emit(
        "update_player_list",
        {"players": player_list, "game_code": game["game_code"]},
        room=game["game_code"],
    )


def full_game_reset(new_code="W", admin_to_keep=None):
    """Resets the entire game object, optionally preserving the admin."""
    global game
    print(f"Admin has reset the game with a new code.")
    game = {
        "players": {},
        "game_state": "waiting",
        "players_ready_for_game": set(),
        "admin_sid": None,
        "game_code": new_code,
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
    game["night_wolf_choices"] = {}
    game["night_seer_choice"] = None
    game["seer_investigated"] = False
    game["accusations"] = {}
    game["end_day_votes"] = set()
    game["lynch_target_id"] = None
    game["lynch_votes"] = {}
    game["rematch_votes"] = set()

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
def check_win_conditions():
    # Don't check for wins if the game isn't in a state where players can die.
    log_and_emit(f"checking win conditions, current game_state: {game['game_state']}")
    if game["game_state"] in [
        "waiting",
        "ended",
    ]:
        return False

    num_living_wolves = len(get_living_players("wolf"))
    num_living_non_wolves = len(get_living_players()) - num_living_wolves

    winner = None
    reason = ""

    # Villager Win: No wolves left alive.
    if num_living_wolves == 0 and num_living_non_wolves > 0:
        winner = "Villagers"
        reason = "All of the wolves have been eradicated."
    # Wolf Win: number of wolves >= non-wolves.
    elif num_living_wolves >= num_living_non_wolves and num_living_wolves > 0:
        winner = "Wolves"
        reason = "The wolves have taken over the village."

    if winner:
        game["game_state"] = "ended"
        final_player_states = [
            {"username": p.username, "role": p.role, "is_alive": p.is_alive}
            for p in game["players"].values()
        ]
        payload = {
            "winning_team": winner,
            "reason": reason,
            "final_player_states": final_player_states,
        }
        log_and_emit(f"Game over! The {winner} have won! {reason}")
        socketio.sleep(6)
        socketio.emit("game_over", payload, room=game["game_code"])

        return True  # Game is over
    return False  # Game continues


# need to fix/reorganize phase Initialization resets
def start_new_phase(phase_name):
    log_and_emit(f">>> Starting New Phase: {phase_name.upper()} <<<")
    if game["game_state"] != phase_name or phase_name == "accusation_phase":
        game["current_timer_id"] += 1
    current_timer_id = game["current_timer_id"]

    game["game_state"] = phase_name
    game["end_day_votes"] = set()
    game["lynch_target_id"], game["lynch_votes"] = None, {}

    if phase_name == "accusation_phase":
        game["seer_investigated"] = False  # Reset seer flag during accusation_phase
        game["night_wolf_choices"], game["night_seer_choice"] = {}, None
        game["accusations"] = {}
        game["accusation_timer"] = socketio.start_background_task(
            target=accusation_timer_task, timer_id=current_timer_id
        )
    elif phase_name == "night":
        game["accusation_restarts"] = 0
        # game["accusations"] = {}
        game["night_timer"] = socketio.start_background_task(
            target=night_timer_task, timer_id=current_timer_id
        )
        all_wolves = get_living_players("wolf")
        wolf_names = [p.username for p in all_wolves]
        for wolf in all_wolves:
            teammates = [name for name in wolf_names if name != wolf.username]
            socketio.emit("wolf_team_info", {"teammates": teammates}, room=wolf.sid)

    duration = game["timer_durations"].get(phase_name.replace("_phase", ""), 0)
    socketio.emit(
        "phase_change",
        {
            "phase": phase_name,
            "living_players": [
                {"id": p.id, "username": p.username} for p in get_living_players()
            ],
            "all_players": [
                {"id": p.id, "username": p.username} for p in game["players"].values()
            ],
            "duration": duration,
        },
        room=game["game_code"],
    )


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
            log_and_emit(
                f"=================== Old accusation timer ({timer_id}) expired. Ignoring."
            )


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
            log_and_emit(
                f"================== Old lynch vote timer ({timer_id}) expired. Ignoring."
            )


def night_timer_task(timer_id):
    duration = game["timer_durations"]["night"]
    socketio.sleep(duration)
    with app.app_context():
        if game["game_state"] == "night" and timer_id == game["current_timer_id"]:
            log_and_emit(f"Night timer ({timer_id}) expired. Processing night actions.")
            process_night_actions()
        else:
            log_and_emit(
                f"==================== Old night timer ({timer_id}) expired. Ignoring."
            )


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


def process_night_actions():
    killed_player = None
    choices = list(game["night_wolf_choices"].values())
    if (
        choices
        and len(choices) == len(get_living_players("wolf"))
        and choices[0]
        and all(c == choices[0] for c in choices)
    ):
        target_id = choices[0]
        if target_id in game["players"] and game["players"][target_id].is_alive:
            game["players"][target_id].is_alive = False
            killed_player = game["players"][target_id]
    if killed_player:
        socketio.emit(
            "night_result_kill",
            {
                "killed_player": {
                    "id": killed_player.id,
                    "username": killed_player.username,
                    "role": killed_player.role,
                }
            },
            room=game["game_code"],
        )
    else:
        socketio.emit("night_result_no_kill", {}, room=game["game_code"])

    if not check_win_conditions():
        start_new_phase("accusation_phase")


def tally_accusations(from_timer=False):
    if from_timer:
        for p in get_living_players():
            if p.id not in game["accusations"]:
                game["accusations"][p.id] = ""
    accusation_counts = Counter(v for v in game["accusations"].values() if v)
    if not accusation_counts:
        socketio.emit(
            "lynch_vote_result",
            {"message": "No one was accused, so no trial will be held."},
        )
        socketio.sleep(3)
        start_new_phase("night")
        return
    most_common = accusation_counts.most_common(2)
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        if len(accusation_counts) == 2 and game["accusation_restarts"] == 0:
            socketio.emit(
                "lynch_vote_result",
                {
                    "message": "A tie between only two accused players means no lynching."
                },
            )
            socketio.sleep(3)
            start_new_phase("night")
            return
        elif game["accusation_restarts"] == 0:
            game["accusation_restarts"] += 1
            game["accusations"].clear()
            socketio.emit(
                "message",
                {"text": "A tie has occurred! A new round of accusations will begin."},
            )
            socketio.sleep(3)
            start_new_phase("accusation_phase")
            return
        else:  # Tie after a restart
            socketio.emit(
                "lynch_vote_result",
                {"message": "Another tie occurred. There will be no trial tonight."},
            )
            socketio.sleep(3)
            start_new_phase("night")
            return

    # No tie, proceed to lynch vote
    game["accusation_restarts"] = 0
    target_id = most_common[0][0]
    game["lynch_target_id"] = target_id
    game["game_state"] = "lynch_vote_phase"
    game["current_timer_id"] += 1  # Invalidate the old accusation timer
    game["lynch_vote_timer"] = socketio.start_background_task(
        target=lynch_vote_timer_task, timer_id=game["current_timer_id"]
    )
    socketio.emit(
        "lynch_vote_started",
        {
            "target_id": target_id,
            "target_name": game["players"][target_id].username,
            "duration": game["timer_durations"]["lynch_vote"],
        },
        room=game["game_code"],
    )


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
        message = f"{target_player.username} has been lynched! They were a {target_player.role}."
        socketio.emit(
            "lynch_vote_result",
            {"message": message, "killed_id": target_id, "summary": vote_summary},
            room=game["game_code"],
        )
    else:
        message = f"The village has voted to spare {target_player.username}."
        socketio.emit(
            "lynch_vote_result",
            {"message": message, "summary": vote_summary},
            room=game["game_code"],
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
        if any(
            p.username.lower() == username.lower() for p in game["players"].values()
        ):
            return render_template("index.html", error="Username is already taken.")
        session["player_id"], session["username"] = str(uuid.uuid4()), username
        return redirect(url_for("lobby"))
    return render_template("index.html")


@app.route("/lobby")
def lobby():
    player_id = session.get("player_id")
    if not player_id:
        return redirect(url_for("index"))
    if game["game_state"] != "waiting":
        return (
            redirect(url_for("game_page"))
            if player_id in game["players"]
            else redirect(url_for("index"))
        )
    return render_template("lobby.html", player_id=player_id)


@app.route("/game")
def game_page():
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        return redirect(url_for("index"))
    if game["game_state"] == "waiting":
        return redirect(url_for("lobby"))
    return render_template(
        "game.html", player_role=game["players"][player_id].role, player_id=player_id
    )


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        app.root_path,
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


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
def handle_connect(auth=None):
    log_and_emit(f"===> A client connected. SID: {request.sid}")
    player_id = session.get("player_id")
    if not player_id:
        return

    # This logic handles both new players joining the lobby and existing players reconnecting.
    if player_id not in game["players"]:
        if game["game_state"] != "waiting":
            return emit("error", {"message": "Game is already in progress."})
        new_player = Player(session.get("username"), request.sid)
        # set first player in room to be admin, if no admin from previous match
        # check if error here, since possilbe game["players"] is empty, even in rematch?
        if not any(p.is_admin for p in game["players"].values()):
            new_player.is_admin = True
            game["admin_sid"] = request.sid
            log_and_emit(
                f"===> +++ New player Admin {new_player.username} added to game. id: {new_player.id} +++"
            )
        game["players"][player_id] = new_player
        log_and_emit(
            f"===> +++ New player {new_player.username} added to game. id: {new_player.id} +++"
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
        emit(
            "game_state_sync",
            {
                "phase": game["game_state"],
                "your_role": player.role,
                "is_alive": player.is_alive,
                "is_admin": player.is_admin,
                "living_players": [
                    {"id": p.id, "username": p.username} for p in get_living_players()
                ],
                "all_players": [
                    {"id": p.id, "username": p.username}
                    for p in game["players"].values()
                ],
                "duration": game["timer_durations"].get(
                    game["game_state"].replace("_phase", ""), 0
                ),
            },
        )


@socketio.on("disconnect")
def handle_disconnect():
    player_id, _ = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        log_and_emit(
            f"==== Player {game['players'][player_id].username} disconnected ===="
        )
        game["players_ready_for_game"].discard(player_id)


@socketio.on("admin_set_timers")
def handle_admin_set_timers(data):
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    try:
        night_duration = max(30, int(data.get("night")))
        accusation_duration = max(30, int(data.get("accusation")))
        lynch_duration = max(30, int(data.get("lynch_vote")))

        game["timer_durations"]["night"] = night_duration
        game["timer_durations"]["accusation"] = accusation_duration
        game["timer_durations"]["lynch_vote"] = lynch_duration

        log_and_emit(f"Admin set new timer durations: {game['timer_durations']}")
        emit("message", {"text": "Timer durations have been updated."})
    except (ValueError, TypeError):
        emit("error", {"message": "Invalid timer values."})


@socketio.on("admin_exclude_player")
def handle_admin_exclude_player(data):
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    player_id = data.get("player_id")
    if player_id in game["players"]:
        sid = game["players"][player_id].sid
        del game["players"][player_id]
        socketio.emit("force_kick", room=sid)
        leave_room(game["game_code"], sid=sid)
        broadcast_player_list()


@socketio.on("admin_start_game")
def handle_admin_start_game():
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    if len(game["players"]) < 4:
        return emit("error", {"message": "Cannot start with fewer than 4 players."})
    log_and_emit("===> Admin started game. Assigning roles.")
    assign_roles()
    game["game_state"] = "started"
    game["players_ready_for_game"].clear()
    socketio.emit("game_started", room=game["game_code"])


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
        room=game["game_code"],
        skip_sid=request.sid,
    )

    # Reset the game, preserving only the admin
    full_game_reset(new_code=new_code, admin_to_keep=admin_player)

    # Update the admin's lobby view
    broadcast_player_list()


@socketio.on("client_ready_for_game")
def handle_client_ready_for_game():
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        log_and_emit(
            f" 'client_ready_for_game' from unknown player. SID: {request.sid}"
        )
        return
    game["players_ready_for_game"].add(player_id)
    log_and_emit(
        f"{game['players'][player_id].username} is ready. Total ready: {len(game['players_ready_for_game'])}/{len(game['players'])}"
    )
    if game["game_state"] == "started" and len(game["players_ready_for_game"]) == len(
        game["players"]
    ):
        start_new_phase("night")


@socketio.on("wolf_choice")
def handle_wolf_choice(data):
    player_id, p = get_player_by_sid(request.sid)
    if not p or p.role != "wolf" or not p.is_alive or game["game_state"] != "night":
        log_and_emit(f"wolf_choice do nothing but return1")
        return
    target_id = data.get("target_id")
    if target_id and (
        target_id not in game["players"] or not game["players"][target_id].is_alive
    ):
        log_and_emit(f"wolf_choice do nothing but return2")
        return
    game["night_wolf_choices"][player_id] = target_id
    check_night_actions_complete()


@socketio.on("seer_choice")
def handle_seer_choice(data):
    player_id, p = get_player_by_sid(request.sid)
    if (
        not p
        or p.role != "seer"
        or not p.is_alive
        or game["game_state"] != "night"
        or game["seer_investigated"]
    ):
        log_and_emit(f"seer_choice do nothing but return1")
        return

    target_id = data.get("target_id")
    if target_id and (
        target_id not in game["players"] or not game["players"][target_id].is_alive
    ):
        log_and_emit(f"seer_choice do nothing but return2")
        return
    game["night_seer_choice"] = target_id
    if target_id:  # this if can be removed?
        game["seer_investigated"] = True
        emit(
            "seer_result",
            {
                "username": game["players"][target_id].username,
                "role": "wolf"
                if game["players"][target_id].role == "wolf"
                else "not wolf",
            },
        )
    check_night_actions_complete()


@socketio.on("accuse_player")
def handle_accuse_player(data):
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_alive or game["game_state"] != "accusation_phase":
        return
    target_id = data.get("target_id")
    if target_id and (
        target_id not in game["players"] or not game["players"][target_id].is_alive
    ):
        return
    if player_id in game["accusations"]:
        return emit("error", {"message": "You have already made an accusation."})
    game["accusations"][player_id] = target_id
    accused_name = game["players"][target_id].username if target_id else "Nobody"
    socketio.emit(
        "accusation_made",
        {"accuser_name": p.username, "accused_name": accused_name},
        room=game["game_code"],
    )
    counts = Counter(v for v in game["accusations"].values() if v)
    socketio.emit("accusation_update", counts, room=game["game_code"])
    # Check if all living players have accused
    if len(game["accusations"]) >= len(get_living_players()):
        tally_accusations()


@socketio.on("cast_lynch_vote")
def handle_cast_lynch_vote(data):
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_alive or game["game_state"] != "lynch_vote_phase":
        return
    vote = data.get("vote")
    if player_id not in game["lynch_votes"] and vote in ["yes", "no"]:
        game["lynch_votes"][player_id] = vote
        # Check if all living players have voted
        if len(game["lynch_votes"]) >= len(get_living_players()):
            process_lynch_vote()


@socketio.on("vote_to_end_day")
def handle_vote_to_end_day():
    player_id, p = get_player_by_sid(request.sid)
    if not p or not p.is_alive or game["game_state"] != "accusation_phase":
        return

    if player_id not in game["end_day_votes"]:
        game["end_day_votes"].add(player_id)
        num_living, num_votes = len(get_living_players()), len(game["end_day_votes"])
        socketio.emit(
            "end_day_vote_update",
            {"count": num_votes, "total": num_living},
            room=game["game_code"],
        )
        if num_votes > num_living / 2:
            tally_accusations(from_timer=True)


# handle voting process after game ends. tracks votes, upon
# majority , resets game state and redirects all to lobby
@socketio.on("vote_for_rematch")
def handle_vote_for_rematch():
    player_id, p = get_player_by_sid(request.sid)
    if not p or game["game_state"] != "ended":
        return

    if player_id not in game["rematch_votes"]:
        game["rematch_votes"].add(player_id)

        num_votes = len(game["rematch_votes"])
        total_players = len(game["players"])

        # Check if a majority has been reached
        if num_votes > total_players / 2:
            reset_game_state()
            socketio.emit("redirect_to_lobby", {}, room=game["game_code"])
        else:
            # Broadcast the current vote count
            payload = {"count": num_votes, "total": total_players}
            socketio.emit("rematch_vote_update", payload, room=game["game_code"])


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", debug=True, allow_unsafe_werkzeug=True)
