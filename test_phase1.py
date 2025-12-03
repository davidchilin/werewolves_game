# test_phase1.py
from roles import AVAILABLE_ROLES, Seer, Werewolf

print("--- Testing Registry ---")
print(f"Registered Roles: {list(AVAILABLE_ROLES.keys())}")
# Check: Should print ['Villager', 'Werewolf', 'Seer', 'Bodyguard']

print("\n--- Testing Instantiation ---")
seer_role = AVAILABLE_ROLES["Seer"]()
print(f"Seer Team: {seer_role.team}")
print(f"Seer Priority: {seer_role.priority}")

wolf_role = AVAILABLE_ROLES["Werewolf"]()
print(f"Wolf Priority: {wolf_role.priority}")

# Check: logic flow
if seer_role.priority < wolf_role.priority:
    print("SUCCESS: Seer moves before Wolf.")
else:
    print("FAILURE: Priority order is wrong.")
