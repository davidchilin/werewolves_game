# test_phase3.py
from game_engine import Game
from roles import AVAILABLE_ROLES

game = Game("test_complex")
game.add_player("p1", "Wolf")
game.add_player("p2", "Monster")
game.add_player("p3", "Cupid")
game.add_player("p4", "Lover1")

# Force Roles
game.players["p1"].role = AVAILABLE_ROLES["Werewolf"]()
game.players["p2"].role = AVAILABLE_ROLES["Monster"]()
game.players["p3"].role = AVAILABLE_ROLES["Cupid"]()
game.players["p4"].role = AVAILABLE_ROLES["Villager"]()

game.set_phase("NIGHT")

# 1. Test Cupid (p3 links p3 and p4)
game.receive_night_action("p3", "p4")

# 2. Test Wolf attacking Monster (p1 attacks p2)
# The Monster should survive because of passive_effect
game.receive_night_action("p1", "p2")

dead = game.resolve_night_phase()

print(f"Dead: {dead}")

# CHECK 1: Monster should NOT be in dead list
if "p2" not in dead:
    print("SUCCESS: Monster survived wolf attack.")
else:
    print("FAILURE: Monster died.")

# CHECK 2: If we kill the Cupid manually, does Lover1 die?
# (You can test this by mocking the kill list in the engine or running a second night)
