# test_phase2.py
from game_engine import Game

# 1. Setup
game = Game("test_lobby_1")
game.add_player("p1", "Alice (Bodyguard)")
game.add_player("p2", "Bob (Werewolf)")
game.add_player("p3", "Charlie (Seer)")
game.add_player("p4", "Dave (Villager)")

# 2. Force assign roles (bypassing random for testing)
from roles import AVAILABLE_ROLES

game.players["p1"].role = AVAILABLE_ROLES["Bodyguard"]()
game.players["p2"].role = AVAILABLE_ROLES["Werewolf"]()
game.players["p3"].role = AVAILABLE_ROLES["Seer"]()
game.players["p4"].role = AVAILABLE_ROLES["Villager"]()

print("--- STARTING NIGHT ---")
game.set_phase("NIGHT")

# 3. Simulate Inputs
# Scenario: Wolf tries to kill Dave. Bodyguard protects Dave.
game.receive_night_action("p2", "p4")  # Wolf attacks Dave
game.receive_night_action("p1", "p4")  # BG protects Dave
game.receive_night_action("p3", "p2")  # Seer checks Bob

# 4. Resolve
dead_players = game.resolve_night_phase()

print(f"\nDead Players: {dead_players}")

# CHECK: Dave should be ALIVE (Empty list of dead players)
if not dead_players:
    print("SUCCESS: Bodyguard prevented the kill!")
else:
    print("FAILURE: Dave died.")
