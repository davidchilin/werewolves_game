#
# /------------------ game_logic.py ------------------/
#
# This file contains the core logic for the game itself.
# It defines the Player and Game classes, which manage state.
# It is completely independent of Flask and SocketIO.
#

import random


class Player:
    """
    Represents a single player in the game.
    """

    def __init__(self, sid, username):
        self.sid = sid  # The player's unique session ID from SocketIO
        self.username = username
        self.role = None  # e.g., 'Wolf', 'Seer', 'Villager'
        self.is_alive = True  # Players are alive by default

    def to_dict(self, show_role=False):
        """
        Converts the player object to a dictionary for sending to clients.
        The 'show_role' flag controls whether the role is included.
        """
        player_data = {
            "sid": self.sid,
            "username": self.username,
            "is_alive": self.is_alive,
        }
        if show_role:
            player_data["role"] = self.role
        return player_data


class Game:
    """
    Represents the entire state and logic of a single game instance.
    """

    def __init__(self, game_code):
        self.game_code = game_code
        self.players = []
        self.game_state = "waiting"  # 'waiting', 'night', 'day', 'ended'
        self.admin_sid = None  # The session ID of the admin player

    def add_player(self, player):
        """Adds a player to the game."""
        self.players.append(player)

    def remove_player(self, player):
        """Removes a player from the game."""
        self.players.remove(player)

    def get_player_by_sid(self, sid):
        """Finds and returns a player object by their session ID."""
        for player in self.players:
            if player.sid == sid:
                return player
        return None

    def set_admin(self, admin_sid):
        """Sets the admin for the game."""
        self.admin_sid = admin_sid

    def assign_roles(self):
        """
        Assigns roles to all players in the game.
        This is a simple implementation. A more advanced one would scale roles
        with the number of players.
        """
        roles_to_assign = []
        num_players = len(self.players)

        # Example logic: 1 wolf, 1 seer, rest are villagers
        if num_players >= 4:
            roles_to_assign.append("Wolf")
            roles_to_assign.append("Seer")
            # Fill the rest with Villagers
            for _ in range(num_players - 2):
                roles_to_assign.append("Villager")
        else:
            # Fallback for very small games (for testing)
            roles_to_assign = ["Villager"] * num_players

        # Shuffle the roles and assign them to players
        random.shuffle(roles_to_assign)
        for player, role in zip(self.players, roles_to_assign):
            player.role = role
            print(f"Assigned {player.username} the role of {role}")

    def start_game(self):
        """Starts the game, assigns roles, and sets the state to night."""
        self.assign_roles()
        self.game_state = "night"

    def get_state(self):
        """
        Returns a dictionary representing the public state of the game.
        This state is safe to broadcast to all players (no secret roles).
        """
        return {
            "game_code": self.game_code,
            "game_state": self.game_state,
            "players": [p.to_dict() for p in self.players],
            "admin_sid": self.admin_sid,
        }

    def get_player_perspective(self, sid):
        """
        Returns a dictionary representing the game state from the
        perspective of a single player, including their secret role.
        """
        player_perspective_state = self.get_state()
        player = self.get_player_by_sid(sid)
        if player:
            # Add the personal role to the state for this player only
            player_perspective_state["my_role"] = player.role
        return player_perspective_state
