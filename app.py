#
# /------------------ app.py ------------------/
#
# This is the main file for the Flask web server.
# It handles HTTP requests and real-time communication using Flask-SocketIO.
#

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from game_logic import Game, Player

# Initialize the Flask application and Flask-SocketIO
app = Flask(__name__)
app.config["SECRET_KEY"] = "a_very_secret_key"  # Used for session security
socketio = SocketIO(app)

# --- Global State ---
# In this simple version, we will have only one game instance at a time.
# The 'current_game' variable will hold the game object.
current_game = None

# This is the secret code required to join the game.
# In a real-world application, this might be dynamically generated.
GAME_CODE = "werewolf123"

# --- HTTP Routes ---


@app.route("/")
def index():
    """
    Renders the main game page (index.html).
    This is the entry point for all players.
    """
    return render_template("index.html")


# --- SocketIO Event Handlers ---
# These functions handle real-time events between the server and clients (players).


@socketio.on("connect")
def handle_connect():
    """
    Handles a new client connecting to the server.
    This is a good place for initial setup or logging.
    """
    print(f"Client connected: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    """
    Handles a client disconnecting from the server.
    If the player was in a game, we should handle their removal.
    """
    global current_game
    if current_game:
        # Find and remove the player from the game
        player_to_remove = current_game.get_player_by_sid(request.sid)
        if player_to_remove:
            current_game.remove_player(player_to_remove)
            print(f"Player {player_to_remove.username} disconnected and was removed.")
            # Send an updated game state to all remaining players
            emit("game_state_update", current_game.get_state(), broadcast=True)
    print(f"Client disconnected: {request.sid}")


@socketio.on("join_game")
def handle_join_game(data):
    """
    Handles a player's request to join the game.
    Data expected: {'username': 'PlayerName', 'game_code': 'some_code'}
    """
    global current_game
    username = data.get("username")
    game_code = data.get("game_code")

    # --- Validation ---
    if not username:
        emit("error", {"message": "Username is required."})
        return

    if game_code != GAME_CODE:
        emit("error", {"message": "Invalid Game Code."})
        return

    # --- Game Initialization ---
    # If there is no active game, or the last game ended, create a new one.
    if not current_game or current_game.game_state == "ended":
        current_game = Game(game_code=GAME_CODE)
        print("A new game has been created.")

    # Prevent joining if the game is already in progress
    if current_game.game_state != "waiting":
        emit("error", {"message": "Game is already in progress."})
        return

    # --- Add Player ---
    # Create a new player object and add them to the game
    player = Player(sid=request.sid, username=username)
    current_game.add_player(player)

    # The first player to join becomes the admin
    if not current_game.admin_sid:
        current_game.set_admin(player.sid)
        print(f"Player {username} is now the admin.")

    # Add the player to a SocketIO room for this game instance
    join_room(current_game.game_code)

    print(f"Player {username} joined the game.")

    # --- Send Update ---
    # Broadcast the new game state to all players in the room
    emit("game_state_update", current_game.get_state(), broadcast=True)


@socketio.on("admin_exclude_player")
def handle_admin_exclude_player(data):
    """
    Handles the admin's request to exclude a player from the lobby.
    Data expected: {'player_sid_to_exclude': 'some_sid'}
    """
    global current_game
    player_sid_to_exclude = data.get("player_sid_to_exclude")

    # --- Validation ---
    if not current_game or current_game.admin_sid != request.sid:
        emit("error", {"message": "Only the admin can exclude players."})
        return

    player_to_exclude = current_game.get_player_by_sid(player_sid_to_exclude)
    if player_to_exclude:
        # Remove the player from the game logic
        current_game.remove_player(player_to_exclude)

        # Disconnect the player's socket
        # Note: 'close_room' is a forceful way to disconnect a specific SID
        leave_room(current_game.game_code, sid=player_sid_to_exclude)
        socketio.emit(
            "kicked",
            {"message": "The admin has removed you from the game."},
            room=player_sid_to_exclude,
        )
        socketio.close_room(player_sid_to_exclude)

        print(f"Admin excluded player {player_to_exclude.username}.")

        # Broadcast the updated state
        emit("game_state_update", current_game.get_state(), broadcast=True)


@socketio.on("admin_start_game")
def handle_admin_start_game():
    """
    Handles the admin's request to start the game.
    """
    global current_game

    # --- Validation ---
    if not current_game or current_game.admin_sid != request.sid:
        emit("error", {"message": "Only the admin can start the game."})
        return

    # You might want to enforce a minimum number of players
    MIN_PLAYERS = 4  # For example: 1 wolf, 1 seer, 2 villager
    if len(current_game.players) < MIN_PLAYERS:
        emit("error", {"message": f"You need at least {MIN_PLAYERS} players to start."})
        return

    # --- Start Game Logic ---
    current_game.start_game()
    print("Game has started!")

    # --- Send Role Assignments ---
    # Send each player their role individually (Direct Message)
    for player in current_game.players:
        player_state = current_game.get_player_perspective(player.sid)
        emit("personal_state_update", player_state, room=player.sid)

    # Broadcast the public game state (without roles) to everyone
    emit("game_state_update", current_game.get_state(), broadcast=True)


# --- Main Entry Point ---
if __name__ == "__main__":
    print("Server starting...")
    # This will run the Flask app with SocketIO support.
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
