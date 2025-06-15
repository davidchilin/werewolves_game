# app.py

import os
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid  # Used to generate unique IDs for players

# --- App Initialization ---
app = Flask(__name__)
# IMPORTANT: A secret key is required for Flask sessions to work
# This key should be a long, random, secret string in a real application
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "a-SUPER-DUPER-secret-key")
socketio = SocketIO(app)

# --- Game State ---
game = {
    "players": {},  # Dictionary to store players by session ID
    "game_state": "waiting",  # Can be 'waiting', 'in_progress', 'ended'
    "admin_sid": None,
    "game_code": "WEREWOLF123",  # Default game code
}


# --- Player Class ---
class Player:
    def __init__(self, username, sid):
        # use the persistent session ID as the primary key
        self.id = session.get("player_id")
        self.username = username
        self.sid = sid  # The temporary SocketIO session ID
        self.is_admin = False
        self.is_alive = True
        self.role = None


def get_player_by_sid(sid):
    """Finds a player dictionary key by their SocketIO SID."""
    for player_id, player_obj in game["players"].items():
        if player_obj.sid == sid:
            return player_id
    return None


def broadcast_player_list():
    """Emits the updated player list to all clients."""
    player_list = [
        {"id": p.id, "username": p.username, "is_admin": p.is_admin}
        for p in game["players"].values()
    ]
    socketio.emit("update_player_list", {"players": player_list})


# --- HTTP Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    """Handles the initial login page."""
    # If player already in session and in game, redirect to lobby
    if "player_id" in session and session["player_id"] in game["players"]:
        return redirect(url_for("lobby"))

    if request.method == "POST":
        username = request.form.get("username")
        code = request.form.get("game_code")

        # Validation
        if not username:
            return render_template(
                "index.html", error="Username is required.", game_code=game["game_code"]
            )
        if code != game["game_code"]:
            return render_template(
                "index.html", error="Invalid game code.", game_code=game["game_code"]
            )

        # check for unique username (case-insensitive)
        for p in game["players"].values():
            if p.username.lower() == username.lower():
                return render_template(
                    "index.html",
                    error="Username is already taken.",
                    game_code=game["game_code"],
                )

        # create persistent player ID and store in session
        session["player_id"] = str(uuid.uuid4())
        session["username"] = username
        return redirect(url_for("lobby"))

    return render_template("index.html", game_code=game["game_code"])


@app.route("/lobby")
def lobby():
    """Shows the game lobby."""
    # If player tries to access lobby directly without a session, send back to login
    if "player_id" not in session:
        return redirect(url_for("index"))
    return render_template("lobby.html", game_code=game["game_code"])


# --- SocketIO Events ---
@socketio.on("connect")
def handle_connect():
    """Handles a new client connection."""
    player_id = session.get("player_id")
    # If user has no session ID, they haven't gone through the login page
    if not player_id:
        return

    # If player re-connecting, update their SID
    if player_id in game["players"]:
        game["players"][player_id].sid = request.sid
        print(
            f"Player {game['players'][player_id].username} reconnected with new SID: {request.sid}"
        )
    else:
        # This is a new player joining
        username = session.get("username")
        if not username:
            return  # Should not happen, but a good safeguard

        new_player = Player(username, request.sid)

        # The first player to join becomes admin
        if not game["players"]:
            new_player.is_admin = True
            game["admin_sid"] = request.sid  # useful to know admin's current SID
            print(f"Admin '{username}' has joined.")
        else:
            print(f"Player '{username}' has joined.")

        game["players"][player_id] = new_player

    join_room(game["game_code"])
    broadcast_player_list()
    print(f"Current players: {[p.username for p in game['players'].values()]}")


@socketio.on("disconnect")
def handle_disconnect():
    """Handles a client disconnection."""
    # just note they are disconnected. they will be re-mapped on reconnect
    player_id = get_player_by_sid(request.sid)
    if player_id and player_id in game["players"]:
        print(f"Player {game['players'][player_id].username} disconnected.")
    # No need to leave_room or broadcast, they'll rejoin automatically


@socketio.on("admin_exclude_player")
def admin_exclude_player(data):
    """Allows admin to remove a player from the lobby."""
    # Security check: only the admin can perform this action
    if request.sid != game["admin_sid"]:
        return

    player_to_exclude_id = data.get("player_id")
    if player_to_exclude_id in game["players"]:
        excluded_player_sid = game["players"][player_to_exclude_id].sid
        print(f"Admin is excluding player with ID: {player_to_exclude_id}")
        # Kick player from SocketIO room and our game dict
        del game["players"][player_to_exclude_id]
        socketio.emit("force_kick", room=excluded_player_sid)
        leave_room(game["game_code"], sid=excluded_player_sid)
        broadcast_player_list()


# event for admin to set new game code
@socketio.on("admin_set_new_code")
def admin_set_new_code(data):
    """Allow admin to set a new game code when the game is in 'waiting' or 'ended' state."""
    if request.sid != game["admin_sid"]:
        return

    if game["game_state"] in ["waiting", "ended"]:
        new_code = data.get("new_code", "WEREWOLF").upper()
        if new_code:
            old_code = game["game_code"]
            game["game_code"] = new_code
            print(f"Admin changed game code from {old_code} to {new_code}")
            # Notify all players of the new code
            socketio.emit("new_code_set", {"new_code": new_code}, room=old_code)
            # This part is tricky. We can't easily move everyone to a new SocketIO room.
            # The simplest approach is to have clients handle the new code display.


# --- Main Execution ---
if __name__ == "__main__":
    socketio.run(app, debug=True)
