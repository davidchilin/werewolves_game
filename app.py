import os
import random
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid

# --- App Initialization ---
app = Flask(__name__)
# A secret key is required for Flask sessions to work.
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "a-very-secret-key-that-is-long-and-random"
)
socketio = SocketIO(app)

# --- Game State ---
# This dictionary acts as our simple in-memory database for the game.
game = {
    "players": {},  # Key: player_id, Value: Player object
    "game_state": "waiting",  # waiting, night, day_discussion, day_voting, ended
    "admin_sid": None,
    "game_code": "WEREWOLF",  # Default game code
    # State for night phase
    "night_wolf_choices": {},  # Maps wolf's player_id to their target's player_id
    "night_seer_choice": None,  # Stores the seer's target for the night
}


# --- Player Class ---
# Represents a player in the game.
class Player:
    def __init__(self, username, sid):
        self.id = session.get("player_id")
        self.username = username
        self.sid = sid  # The temporary SocketIO session ID, updated on reconnect
        self.is_admin = False
        self.is_alive = True
        self.role = None  # 'villager', 'wolf', or 'seer'


# --- Helper Functions ---
def get_player_by_sid(sid):
    """Finds a player's ID by their current SocketIO SID."""
    for player_id, player_obj in game["players"].items():
        if player_obj.sid == sid:
            return player_id
    return None


def get_living_players(roles=None):
    """Returns a list of Player objects who are alive. Can be filtered by role(s)."""
    living = [p for p in game["players"].values() if p.is_alive]
    if roles:
        if isinstance(roles, str):  # If a single role string is passed
            roles = [roles]
        return [p for p in living if p.role in roles]
    return living


def broadcast_player_list():
    """Emits the updated player list to all clients in the lobby."""
    if game["game_state"] != "waiting":
        return
    player_list = [
        {"id": p.id, "username": p.username, "is_admin": p.is_admin}
        for p in game["players"].values()
    ]
    socketio.emit(
        "update_player_list", {"players": player_list}, room=game["game_code"]
    )


# --- Game Logic Functions ---


def assign_roles():
    """Assigns roles to all players at the start of the game."""
    player_ids = list(game["players"].keys())
    random.shuffle(player_ids)

    # Define role distribution logic.
    num_players = len(player_ids)
    num_wolves = max(1, num_players // 4)  # Ensures at least 1 wolf.
    num_seer = 1 if num_players >= 4 else 0  # Seer only in games of 4+

    # Assign roles based on the shuffled list
    for i, player_id in enumerate(player_ids):
        player = game["players"][player_id]
        if i < num_wolves:
            player.role = "wolf"
        elif i < num_wolves + num_seer:
            player.role = "seer"
        else:
            player.role = "villager"

    print("Roles have been assigned:")
    for p in game["players"].values():
        print(f"- {p.username}: {p.role}")


def start_new_phase(phase_name):
    """
    Central function to handle all phase transitions.
    This ensures state is always set correctly before notifying clients.
    """
    print(f"--- Starting new phase: {phase_name.upper()} ---")
    game["game_state"] = phase_name

    # Reset per-phase data to ensure a clean state
    if phase_name == "night":
        game["night_wolf_choices"] = {}
        game["night_seer_choice"] = None
    elif phase_name == "day_discussion":
        # This is where we will add state for accusations in the next phase
        pass

    living_player_data = [
        {"id": p.id, "username": p.username} for p in get_living_players()
    ]

    # The 'all_players' list is crucial for the client to build its master roster.
    all_player_data = [
        {"id": p.id, "username": p.username} for p in game["players"].values()
    ]

    socketio.emit(
        "phase_change",
        {
            "phase": phase_name,
            "living_players": living_player_data,
            "all_players": all_player_data,
        },
        room=game["game_code"],
    )


def check_night_actions_complete():
    """Checks if all required night actions (wolf & seer votes) are submitted."""
    living_wolves = get_living_players("wolf")
    living_seer = get_living_players("seer")

    wolves_done = all(wolf.id in game["night_wolf_choices"] for wolf in living_wolves)
    seer_done = not living_seer or game["night_seer_choice"] is not None

    print(
        f"[DEBUG] Checking night actions: Wolves done? {wolves_done}. Seer done? {seer_done}."
    )

    if wolves_done and seer_done:
        socketio.sleep(1)  # Small delay for dramatic effect
        process_night_actions()


def process_night_actions():
    """Resolves the night's events and transitions the game to the day phase."""
    print("Processing night actions...")
    killed_player = None

    # Determine the result of the wolves' vote.
    choices = list(game["night_wolf_choices"].values())
    # Kill only happens if all living wolves made a choice AND they were unanimous.
    if (
        choices
        and len(choices) == len(get_living_players("wolf"))
        and all(c == choices[0] for c in choices)
    ):
        target_id = choices[0]
        if target_id in game["players"] and game["players"][target_id].is_alive:
            game["players"][target_id].is_alive = False
            killed_player = game["players"][target_id]
            print(f"Wolves unanimously killed {killed_player.username}")

    if killed_player:
        payload = {
            "killed_player": {
                "id": killed_player.id,
                "username": killed_player.username,
                "role": killed_player.role,
            },
        }
        socketio.emit("night_result_kill", payload, room=game["game_code"])
    else:
        socketio.emit("night_result_no_kill", {}, room=game["game_code"])
        print("No one was killed by wolves (either no votes or not unanimous).")

    # In a future phase, we will add a win condition check here.

    # Use the centralized function to transition to the next phase.
    start_new_phase("day_discussion")


# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    if "player_id" in session:
        player_id = session["player_id"]
        if player_id in game["players"]:
            if game["game_state"] != "waiting":
                return redirect(url_for("game_page"))
            else:
                return redirect(url_for("lobby"))
        else:  # Player has a stale session from a previous game.
            session.clear()

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

        session["player_id"] = str(uuid.uuid4())
        session["username"] = username
        return redirect(url_for("lobby"))

    return render_template("index.html")


@app.route("/lobby")
def lobby():
    player_id = session.get("player_id")
    if not player_id:
        return redirect(url_for("index"))

    if game["game_state"] != "waiting":
        if player_id in game["players"]:
            return redirect(url_for("game_page"))
        else:
            return redirect(url_for("index"))

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

    username = session.get("username")
    is_reconnecting = player_id in game["players"]

    if not is_reconnecting:
        if game["game_state"] != "waiting":
            emit("error", {"message": "Game is already in progress."})
            return

        new_player = Player(username, request.sid)
        if not get_living_players():  # First player to join becomes admin
            new_player.is_admin = True
            game["admin_sid"] = request.sid
        game["players"][player_id] = new_player
        print(f"Player '{username}' has joined the lobby.")
    else:
        game["players"][player_id].sid = request.sid
        print(
            f"Player {game['players'][player_id].username} reconnected with new SID: {request.sid}"
        )

    join_room(game["game_code"])

    if game["game_state"] == "waiting":
        broadcast_player_list()
    else:
        player = game["players"][player_id]
        emit("reconnect_state", {"role": player.role, "is_alive": player.is_alive})


@socketio.on("disconnect")
def handle_disconnect():
    player_id = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        print(f"Player {game['players'][player_id].username} disconnected.")


@socketio.on("admin_exclude_player")
def admin_exclude_player(data):
    if request.sid != game["admin_sid"]:
        return
    player_to_exclude_id = data.get("player_id")
    if player_to_exclude_id in game["players"]:
        excluded_player_sid = game["players"][player_to_exclude_id].sid
        del game["players"][player_to_exclude_id]
        emit("force_kick", room=excluded_player_sid)
        leave_room(game["game_code"], sid=excluded_player_sid)
        broadcast_player_list()


@socketio.on("admin_start_game")
def admin_start_game():
    if request.sid != game["admin_sid"] or game["game_state"] != "waiting":
        return
    if len(game["players"]) < 4:
        emit("error", {"message": "Cannot start with fewer than 4 players."})
        return

    print("Admin is starting the game...")
    assign_roles()
    game["game_state"] = "night"

    socketio.emit("game_started", room=game["game_code"])


@socketio.on("client_ready_for_game_state")
def on_client_ready():
    """Sent by clients after they load the game page to get the initial state."""
    player_id = session.get("player_id")
    if not player_id or player_id not in game["players"]:
        return

    p_obj = game["players"][player_id]
    emit("your_role", {"role": p_obj.role, "is_alive": p_obj.is_alive})

    # Only the admin's client triggers the very first phase change to avoid duplicates.
    if request.sid == game["admin_sid"] and game["game_state"] == "night":
        start_new_phase("night")

    # If a player reconnects, resend them the current phase data
    elif game["game_state"] != "waiting":
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
            },
        )


@socketio.on("wolf_choice")
def handle_wolf_choice(data):
    """Handles a wolf's vote to kill a player."""
    player_id = get_player_by_sid(request.sid)
    player = game["players"].get(player_id)
    if (
        not player
        or player.role != "wolf"
        or not player.is_alive
        or game["game_state"] != "night"
    ):
        return

    target_id = data.get("target_id")
    if (
        not target_id
        or target_id not in game["players"]
        or not game["players"][target_id].is_alive
    ):
        return

    game["night_wolf_choices"][player_id] = target_id
    print(f"Wolf {player.username} chose to kill {game['players'][target_id].username}")

    wolf_sids = [w.sid for w in get_living_players("wolf")]
    for sid in wolf_sids:
        emit("wolf_pack_update", game["night_wolf_choices"], room=sid)

    check_night_actions_complete()


@socketio.on("seer_choice")
def handle_seer_choice(data):
    """Handles the Seer's choice to investigate a player."""
    player_id = get_player_by_sid(request.sid)
    player = game["players"].get(player_id)
    # Standard validation: must be a living seer in the night phase
    if (
        not player
        or player.role != "seer"
        or not player.is_alive
        or game["game_state"] != "night"
    ):
        return

    target_id = data.get("target_id")
    # Target must be a valid, living player
    if (
        not target_id
        or target_id not in game["players"]
        or not game["players"][target_id].is_alive
    ):
        return

    game["night_seer_choice"] = target_id
    target_player = game["players"][target_id]
    print(f"Seer {player.username} investigated {target_player.username}")

    # Send the result only to the Seer.
    emit(
        "seer_result", {"username": target_player.username, "role": target_player.role}
    )

    check_night_actions_complete()


# --- Main Execution ---
if __name__ == "__main__":
    socketio.run(app, debug=True)
