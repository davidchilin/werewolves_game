import os
import random
from collections import Counter
from flask import Flask, render_template, request, session, redirect, url_for
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
    "players": {},
    "game_state": "waiting",
    "admin_sid": None,
    "game_code": "WEREWOLF",
    "night_wolf_choices": {},
    "night_seer_choice": None,
    "accusations": {},
    "end_day_votes": set(),
    "lynch_target_id": None,
    "lynch_votes": {},
    "day_timer": None,
}


# --- Player Class ---
class Player:
    def __init__(self, username, sid):
        self.id = session.get("player_id")
        self.username = username
        self.sid = sid
        self.is_admin = False
        self.is_alive = True
        self.role = None


# --- Helper Functions ---
def get_player_by_sid(sid):
    for player_id, player_obj in game["players"].items():
        if player_obj.sid == sid:
            return player_id
    return None


def get_living_players(roles=None):
    living = [p for p in game["players"].values() if p.is_alive]
    if roles:
        if isinstance(roles, str):
            roles = [roles]
        return [p for p in living if p.role in roles]
    return living


def broadcast_player_list():
    if game["game_state"] != "waiting":
        return
    player_list = [
        {"id": p.id, "username": p.username, "is_admin": p.is_admin}
        for p in game["players"].values()
    ]
    socketio.emit(
        "update_player_list", {"players": player_list}, room=game["game_code"]
    )


# --- Game Logic ---
def assign_roles():
    player_ids = list(game["players"].keys())
    random.shuffle(player_ids)
    num_players, num_wolves = len(player_ids), max(1, len(player_ids) // 4)
    num_seer = 1 if num_players >= 4 else 0
    for i, player_id in enumerate(player_ids):
        player = game["players"][player_id]
        if i < num_wolves:
            player.role = "wolf"
        elif i < num_wolves + num_seer:
            player.role = "seer"
        else:
            player.role = "villager"


def start_new_phase(phase_name):
    print(f"--- Starting new phase: {phase_name.upper()} ---")
    game["game_state"] = phase_name
    game["night_wolf_choices"], game["night_seer_choice"] = {}, None
    game["accusations"], game["end_day_votes"] = {}, set()
    game["lynch_target_id"], game["lynch_votes"] = None, {}

    if phase_name == "day_discussion":
        game["day_timer"] = socketio.start_background_task(target=day_timer_task)

    living_player_data = [
        {"id": p.id, "username": p.username} for p in get_living_players()
    ]
    all_player_data = [
        {"id": p.id, "username": p.username} for p in game["players"].values()
    ]
    duration = 120 if phase_name == "day_discussion" else 0
    socketio.emit(
        "phase_change",
        {
            "phase": phase_name,
            "living_players": living_player_data,
            "all_players": all_player_data,
            "duration": duration,
        },
        room=game["game_code"],
    )


def day_timer_task():
    """Background task that waits 2 minutes then acts."""
    print("Day discussion timer started (120s).")
    socketio.sleep(120)
    print("Day discussion timer finished.")
    with app.app_context():
        # Only proceed if the game is still in the discussion phase
        if game["game_state"] == "day_discussion":
            print("Timer is proceeding to tally votes.")
            tally_and_start_lynch_vote()
        else:
            print("Timer expired, but game has already moved on. No action taken.")


def check_night_actions_complete():
    living_wolves, living_seer = get_living_players("wolf"), get_living_players("seer")
    wolves_done = all(wolf.id in game["night_wolf_choices"] for wolf in living_wolves)
    seer_done = not living_seer or game["night_seer_choice"] is not None
    if wolves_done and seer_done:
        socketio.sleep(1)
        process_night_actions()


def process_night_actions():
    killed_player = None
    choices = list(game["night_wolf_choices"].values())
    if (
        choices
        and len(choices) == len(get_living_players("wolf"))
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
    start_new_phase("day_discussion")


def tally_and_start_lynch_vote():
    accusation_counts = Counter(v for v in game["accusations"].values() if v)
    if not accusation_counts:
        socketio.emit(
            "lynch_vote_result",
            {"message": "No one was accused, so no trial will be held."},
            room=game["game_code"],
        )
        socketio.sleep(3)
        start_new_phase("night")
        return
    most_common = accusation_counts.most_common(2)
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        socketio.emit(
            "lynch_vote_result",
            {"message": "There was a tie in accusations. No trial will be held."},
            room=game["game_code"],
        )
        socketio.sleep(3)
        start_new_phase("night")
        return
    target_id = most_common[0][0]
    game["lynch_target_id"], game["game_state"] = target_id, "day_voting"
    target_player = game["players"][target_id]
    socketio.emit(
        "lynch_vote_started",
        {"target_id": target_id, "target_name": target_player.username},
        room=game["game_code"],
    )


def process_lynch_vote():
    if len(game["lynch_votes"]) != len(get_living_players()):
        return
    votes, target_id = list(game["lynch_votes"].values()), game["lynch_target_id"]
    yes_votes, target_player = votes.count("yes"), game["players"][target_id]
    if yes_votes > len(votes) / 2:
        target_player.is_alive = False
        message = f"{target_player.username} has been lynched! They were a {target_player.role}."
        socketio.emit(
            "lynch_vote_result",
            {"message": message, "killed_id": target_id},
            room=game["game_code"],
        )
    else:
        message = f"The village has voted to spare {target_player.username}."
        socketio.emit("lynch_vote_result", {"message": message}, room=game["game_code"])
    socketio.sleep(4)
    start_new_phase("night")


# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    if "player_id" in session and session["player_id"] in game["players"]:
        return (
            redirect(url_for("game_page"))
            if game["game_state"] != "waiting"
            else redirect(url_for("lobby"))
        )
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
    player = game["players"][player_id]
    return render_template("game.html", player_role=player.role, player_id=player.id)


# --- SocketIO Events ---
@socketio.on("connect")
def handle_connect():
    player_id = session.get("player_id")
    if not player_id:
        return
    is_reconnecting = player_id in game["players"]
    if not is_reconnecting:
        if game["game_state"] != "waiting":
            return emit("error", {"message": "Game is already in progress."})
        new_player = Player(session.get("username"), request.sid)
        if not get_living_players():
            new_player.is_admin = True
            game["admin_sid"] = request.sid
        game["players"][player_id] = new_player
    else:
        game["players"][player_id].sid = request.sid
    join_room(game["game_code"])
    if game["game_state"] == "waiting":
        broadcast_player_list()
    else:
        player = game["players"][player_id]
        emit(
            "reconnect_state",
            {
                "role": player.role,
                "is_alive": player.is_alive,
                "is_admin": player.is_admin,
            },
        )


@socketio.on("disconnect")
def handle_disconnect():
    player_id = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        print(f"Player {game['players'][player_id].username} disconnected.")


@socketio.on("admin_exclude_player")
def admin_exclude_player(data):
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    player_to_exclude_id = data.get("player_id")
    if player_to_exclude_id in game["players"]:
        excluded_player_sid = game["players"][player_to_exclude_id].sid
        del game["players"][player_to_exclude_id]
        socketio.emit("force_kick", room=excluded_player_sid)
        leave_room(game["game_code"], sid=excluded_player_sid)
        broadcast_player_list()


@socketio.on("admin_start_game")
def admin_start_game():
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    if len(game["players"]) < 4:
        return emit("error", {"message": "Cannot start with fewer than 4 players."})
    assign_roles()
    game["game_state"] = "night"
    socketio.emit("game_started", room=game["game_code"])


@socketio.on("client_ready_for_game_state")
def on_client_ready():
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        return
    player = game["players"][player_id]
    emit(
        "your_role",
        {"role": player.role, "is_alive": player.is_alive, "is_admin": player.is_admin},
    )
    if request.sid == game["admin_sid"] and game["game_state"] == "night":
        start_new_phase("night")
    elif game["game_state"] != "waiting":
        duration = 120 if game["game_state"] == "day_discussion" else 0
        living_player_data = [
            {"id": p.id, "username": p.username} for p in get_living_players()
        ]
        all_player_data = [
            {"id": p.id, "username": p.username} for p in game["players"].values()
        ]
        emit(
            "phase_change",
            {
                "phase": game["game_state"],
                "living_players": living_player_data,
                "all_players": all_player_data,
                "duration": duration,
            },
        )


@socketio.on("wolf_choice")
def handle_wolf_choice(data):
    player_id, p = get_player_by_sid(request.sid), None
    if player_id:
        p = game["players"].get(player_id)
    if not p or p.role != "wolf" or not p.is_alive or game["game_state"] != "night":
        return
    target_id = data.get("target_id")
    if (
        not target_id
        or target_id not in game["players"]
        or not game["players"][target_id].is_alive
    ):
        return
    game["night_wolf_choices"][player_id] = target_id
    emit(
        "wolf_pack_update",
        game["night_wolf_choices"],
        to=[w.sid for w in get_living_players("wolf")],
    )
    check_night_actions_complete()


@socketio.on("seer_choice")
def handle_seer_choice(data):
    player_id, p = get_player_by_sid(request.sid), None
    if player_id:
        p = game["players"].get(player_id)
    if not p or p.role != "seer" or not p.is_alive or game["game_state"] != "night":
        return
    target_id = data.get("target_id")
    if (
        not target_id
        or target_id not in game["players"]
        or not game["players"][target_id].is_alive
    ):
        return
    game["night_seer_choice"] = target_id
    emit(
        "seer_result",
        {
            "username": game["players"][target_id].username,
            "role": game["players"][target_id].role,
        },
    )
    check_night_actions_complete()


@socketio.on("accuse_player")
def handle_accusation(data):
    player_id, player = get_player_by_sid(request.sid), None
    if player_id:
        player = game["players"].get(player_id)
    if not player or not player.is_alive or game["game_state"] != "day_discussion":
        return
    target_id = data.get("target_id")
    if target_id and (
        target_id not in game["players"] or not game["players"][target_id].is_alive
    ):
        return
    if player_id in game["accusations"]:
        return emit(
            "error", {"message": "You have already made an accusation this day."}
        )
    game["accusations"][player_id] = target_id
    accused_name = game["players"][target_id].username if target_id else "Nobody"
    socketio.emit(
        "accusation_made",
        {
            "accuser_id": player_id,
            "accuser_name": player.username,
            "accused_name": accused_name,
        },
        room=game["game_code"],
    )
    if len(game["accusations"]) == len(get_living_players()):
        print("All players have accused. Proceeding to tally.")
        tally_and_start_lynch_vote()


@socketio.on("vote_to_end_day")
def handle_vote_to_end_day():
    player_id, p = get_player_by_sid(request.sid), None
    if player_id:
        p = game["players"].get(player_id)
    if not p or not p.is_alive or game["game_state"] != "day_discussion":
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
            print("Majority vote to end day reached.")
            start_new_phase("night")


@socketio.on("admin_initiate_lynch")
def handle_admin_initiate_lynch():
    if request.sid != game["admin_sid"] or game["game_state"] != "day_discussion":
        return
    tally_and_start_lynch_vote()


@socketio.on("cast_lynch_vote")
def handle_cast_lynch_vote(data):
    player_id, p = get_player_by_sid(request.sid), None
    if player_id:
        p = game["players"].get(player_id)
    if not p or not p.is_alive or game["game_state"] != "day_voting":
        return
    vote = data.get("vote")
    if player_id not in game["lynch_votes"] and vote in ["yes", "no"]:
        game["lynch_votes"][player_id] = vote
        process_lynch_vote()


# --- Main Execution ---
if __name__ == "__main__":
    socketio.run(app, debug=True)
