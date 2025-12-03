"""
test_phase3_complex.py
Comprehensive verification of Complex Roles, Status Effects, and Win Conditions.
"""

from game_engine import Game
from roles import AVAILABLE_ROLES


def assert_alive(player, expected_alive, context=""):
    status = "ALIVE" if player.is_alive else "DEAD"
    expected = "ALIVE" if expected_alive else "DEAD"
    if player.is_alive == expected_alive:
        print(f"[PASS] {context}: {player.name} is {status}.")
    else:
        print(f"[FAIL] {context}: {player.name} is {status}, expected {expected}!")


def print_separator(title):
    print(f"\n{'='*20} {title} {'='*20}")


# --- SETUP ---
print_separator("INITIALIZATION")
game = Game("test_complex")

# 1. Add Players
game.add_player("p_witch", "Wanda (Witch)")
game.add_player("p_wolf1", "Warren (Wolf 1)")
game.add_player("p_wolf2", "Wyatt (Wolf 2)")
game.add_player("p_cupid", "Charlie (Cupid)")
game.add_player("p_monster", "Mike (Monster)")
game.add_player("p_villager", "Val (Villager)")


# 2. Force Assign Roles AND Trigger Hooks (FIXED)
def force_role(pid, role_name):
    player = game.players[pid]
    # Instantiate
    player.role = AVAILABLE_ROLES[role_name]()
    # Trigger the on_assign hook (Crucial for Monster status effect)
    player.role.on_assign(player)


force_role("p_witch", "Witch")
force_role("p_wolf1", "Werewolf")
force_role("p_wolf2", "Werewolf")
force_role("p_cupid", "Cupid")
force_role("p_monster", "Monster")  # <--- This will now add 'immune_to_wolf'
force_role("p_villager", "Villager")

print("Players initialized and roles assigned (Hooks triggered).")

# ==============================================================================
# NIGHT 1: Cupid Links, Wolf Split Vote (Fail), Witch Heals Self
# ==============================================================================
print_separator("NIGHT 1 SCENARIO")
game.set_phase("NIGHT")

# 1. Cupid Links: Wolf1 + Villager (Romeo & Juliet scenario)
game.receive_night_action("p_cupid", {"target_id": "p_wolf1"})
# Note: For this test, we assume Cupid links Sender + Target.
# If your code links Target1 + Target2, adjust input here.
# Engine currently: Cupid links Self + Target?
# Wait, checking engine... Engine logic: "player.linked_partner_id = target... target.linked... = player"
# So Cupid links THEMSELVES to the target in current implementation.
# Let's adjust inputs to link Cupid + Villager for this test.
game.receive_night_action("p_cupid", {"target_id": "p_villager"})

# 2. Wolves Disagree (Split Vote)
game.receive_night_action("p_wolf1", "p_monster")
game.receive_night_action("p_wolf2", "p_witch")

# 3. Witch Self-Heals (Pre-emptive)
# Input: {'target_id': 'p_witch', 'potion': 'heal'}
game.receive_night_action("p_witch", {"target_id": "p_witch", "potion": "heal"})

# RESOLVE
game.resolve_night_phase()

# CHECKS
print("\n--- RESULTS NIGHT 1 ---")
# 1. Check Lovers
if game.players["p_cupid"].linked_partner_id == "p_villager":
    print("[PASS] Cupid and Villager are linked lovers.")
else:
    print(
        f"[FAIL] Lover link failed. Cupid partner: {game.players['p_cupid'].linked_partner_id}"
    )

# 2. Check Wolf Fail
assert_alive(game.players["p_monster"], True, "Monster (Wolf Split Vote)")
assert_alive(game.players["p_witch"], True, "Witch (Wolf Split Vote)")

# 3. Check Witch Inventory (Should have used Heal)
if game.players["p_witch"].role.has_heal_potion is False:
    print("[PASS] Witch used Heal potion.")
else:
    print("[FAIL] Witch still has Heal potion!")

# 4. Check Status Effect Cleanup
if "used_heal" not in game.players["p_witch"].status_effects:
    print("[PASS] 'used_heal' status effect was cleaned up.")
else:
    print("[FAIL] 'used_heal' status effect persists!")


# ==============================================================================
# NIGHT 2: Monster Immunity, Witch Kills Wolf2
# ==============================================================================
print_separator("NIGHT 2 SCENARIO")
game.set_phase("NIGHT")

# 1. Wolves Unanimous Vote on Monster
game.receive_night_action("p_wolf1", "p_monster")
game.receive_night_action("p_wolf2", "p_monster")

# 2. Witch Poisons Wolf2
game.receive_night_action("p_witch", {"target_id": "p_wolf2", "potion": "kill"})

# RESOLVE
game.resolve_night_phase()

# CHECKS
print("\n--- RESULTS NIGHT 2 ---")
# 1. Monster should survive (Immunity)
assert_alive(game.players["p_monster"], True, "Monster (Immune to Wolves)")

# 2. Wolf 2 should die (Witch Poison)
assert_alive(game.players["p_wolf2"], False, "Wolf 2 (Poisoned)")


# ==============================================================================
# NIGHT 3: Lovers Pact (Chain Death)
# ==============================================================================
print_separator("NIGHT 3 SCENARIO")
game.set_phase("NIGHT")

# 1. Remaining Wolf (Wolf 1) attacks Cupid
game.receive_night_action("p_wolf1", "p_cupid")

# 2. Witch has no potions left, sends empty/skip
game.receive_night_action("p_witch", {})

# RESOLVE
game.resolve_night_phase()

# CHECKS
print("\n--- RESULTS NIGHT 3 ---")
# 1. Cupid dies (Wolf attack)
assert_alive(game.players["p_cupid"], False, "Cupid (Attacked)")

# 2. Villager dies (Heartbreak/Linked to Cupid)
assert_alive(game.players["p_villager"], False, "Villager (Died of Grief)")


# ==============================================================================
# WIN CONDITION CHECK
# ==============================================================================
print_separator("GAME OVER CHECK")
# Remaining: Witch (Alive), Wolf 1 (Alive), Monster (Alive)
# 1 Wolf vs 2 Non-Wolves. Game continues.

if game.check_game_over():
    print(f"[FAIL] Game ended prematurely! Winner: {game.winner}")
else:
    print("[PASS] Game continues (1 Wolf vs 2 Others).")

# Simulate Day Vote: Witch and Monster lynch Wolf 1
print("\n--- Simulating Lynch of Last Wolf ---")
game.players["p_wolf1"].is_alive = False

if game.check_game_over():
    print(f"[PASS] Game Over triggered correctly. Winner: {game.winner}")
    if game.winner == "Villagers":
        print("[PASS] Villagers won.")
    else:
        print(f"[FAIL] Wrong winner. Expected Villagers, got {game.winner}")
else:
    print("[FAIL] Game did not end even though all wolves are dead.")
