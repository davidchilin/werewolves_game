"""
game_engine.py
# Version: 4.4.7
Manages the game flow, player states, complex role interactions, and phase transitions.
"""
import random
import time
from config import *
from collections import Counter
from roles import AVAILABLE_ROLES
from threading import RLock


class Player:
    def __init__(self, session_id, name):
        self.id = session_id
        self.lock = RLock()
        self.name = name
        self.role = None  # Will be an instance of a Role class
        self.is_alive = True
        self.status_effects = []  # e.g., ['protected', 'poisoned', 'lover']
        self.linked_partner_id = None  # For Cupid's lovers

    def reset_night_status(self):
        PERSISTENT_EFFECTS = ["lover", "poisoned", "immune_to_wolf"]
        self.status_effects = [
            s for s in self.status_effects if s in PERSISTENT_EFFECTS
        ]

    def to_dict(self):
        """Serialize for frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "is_alive": self.is_alive,
            "role": self.role.name_key if self.role else None,
            "team": self.role.team if self.role else None,
        }


class Game:
    def __init__(self, game_id, mode="standard"):
        self.game_id = game_id
        self.mode = mode
        self.isPassAndPlay = mode == "pass_and_play"
        self.lock = RLock()

        self.phase = PHASE_LOBBY
        self.phase_start_time = None
        self.phase_end_time = 0

        self.players = {}  # Dict[session_id, Player]

        # Night Phase Data
        self.pending_actions = {}  # Dict[player_id, target_id]
        self.turn_history = set()  # who acted this phase
        self.night_log = []  # Logs for the frontend e.g., "Seer saw a Werewolf"

        # Day Phase Data
        self.accusations = {}  # accuser_id: target_id
        self.accusation_restarts = 0
        self.end_day_votes = set()  # set of voter_id

        self.lynch_target_id = None
        self.lynch_votes = {}  # voter_id: yes/no

        # Admin/Meta Data
        self.admin_only_chat = False
        self.timers_disabled = False
        self.timer_durations = {PHASE_NIGHT: 90, PHASE_ACCUSATION: 90, PHASE_LYNCH: 60}
        self.current_timer_id = 0  # increment id to invalidate old async timers

        # End Game Data
        self.winner = None
        self.game_over_data = None
        self.rematch_votes = set()

    # --- game management
    def add_player(self, session_id, name):
        if session_id not in self.players:
            self.players[session_id] = Player(session_id, name)

    def remove_player(self, session_id):
        if session_id in self.players:
            del self.players[session_id]

    def assign_roles(self, selected_role_keys):
        """
        Assigns roles based on player count logic (Auto-Balance).
        1. Calculates Wolves/Seer based on total players.
        2. Fills remainder with Villagers.
        3. Assigns randomly.
        """
        print("Starting role assignment process...")

        # 1. Build Map: 'role_werewolf' -> RoleWerewolf Class
        key_to_class_map = {}
        for role_name, role_cls in AVAILABLE_ROLES.items():
            temp_obj = role_cls()
            key_to_class_map[temp_obj.name_key] = role_cls

        # 2. Prepare Players
        player_ids = list(self.players.keys())
        random.shuffle(player_ids)
        num_players = len(player_ids)

        # 3. Calculate Counts (The Math)
        if 4 <= num_players <= 6:
            num_wolves = 1
        elif 7 <= num_players <= 8:
            num_wolves = 2
        elif 9 <= num_players <= 11:
            num_wolves = 3
        elif 12 <= num_players <= 16:
            num_wolves = 4
        else:
            num_wolves = max(1, int(num_players * 0.25))  # Safety floor

        num_seer = 1 if num_players >= 4 else 0

        # 4. Construct the Master Role List
        final_roles_list = []
        base_roles = [ROLE_WEREWOLF, ROLE_SEER, ROLE_VILLAGER]

        for r_key in selected_role_keys:
            if r_key not in base_roles:
                final_roles_list.append(r_key)

        # Add Wolves
        if not selected_role_keys or ROLE_WEREWOLF in selected_role_keys:
            for _ in range(num_wolves):
                final_roles_list.append(ROLE_WEREWOLF)

        # Add Seer
        if not selected_role_keys or ROLE_SEER in selected_role_keys:
            for _ in range(num_seer):
                final_roles_list.append(ROLE_SEER)

        # Fill remainder with Villagers
        while len(final_roles_list) < num_players:
            final_roles_list.append(ROLE_VILLAGER)

        # Safety: If we have too many roles (e.g. 4 players but 5 specials picked), trim the end.
        if len(final_roles_list) > num_players:
            print(
                f"WARNING: Too many roles selected for {num_players} players. Trimming."
            )
            final_roles_list = final_roles_list[:num_players]

        # Shuffle roles to ensure randomness (since players are already shuffled, this is double safety)
        random.shuffle(final_roles_list)

        print(f"Final List of Role Keys to Assign: {final_roles_list}")

        # 5. Assign Roles
        # We perform safe zip: Stop if we run out of players or roles
        for pid, role_key in zip(player_ids, final_roles_list):
            # Reset player state
            self.players[pid].is_alive = True

            # Lookup the class, default to Villager if key missing
            role_class = key_to_class_map.get(role_key, AVAILABLE_ROLES["Villager"])

            # Instantiate and Assign
            self.players[pid].role = role_class()
            self.players[pid].role.on_assign(self.players[pid])

            print(f"DEBUG: Assigned {role_class.__name__} to Player ID: {pid}")

        print(f"Roles assigned for Game {self.game_id} (Mode: {self.mode})")

    def get_living_players(self, role_team=None):
        living = [p for p in self.players.values() if p.is_alive]
        if role_team:
            return [p for p in living if p.role.team == role_team]
        return living

    def has_player_voted_to_sleep(self, player_id):
        """Returns True if the player is in the set of sleep voters."""
        return player_id in self.end_day_votes

    def set_phase(self, new_phase):
        self.phase = new_phase
        self.phase_start_time = time.time()
        self.current_timer_id += 1

        duration = self.timer_durations.get(new_phase, 0)
        self.phase_end_time = time.time() + duration

        print(f"Phase changed to: {self.phase}, duration: {duration}s")
        # Trigger cleanup or specific phase logic here
        if new_phase == PHASE_NIGHT:
            self.accusation_restarts = 0
            self.accusations = {}
            duration = self.timer_durations.get(PHASE_NIGHT, 90)
            self.end_day_votes = set()
            self.night_actions = {}
            self.night_log = []
            self.pending_actions = {}
            self.turn_history = set()  # Reset tracker
            for p in self.players.values():
                p.reset_night_status()
                # trigger night hoooks
                if p.role:
                    p.role.on_night_start(p, {"players": list(self.players.values())})
        elif new_phase == PHASE_ACCUSATION:
            self.accusations = {}
            duration = self.timer_durations.get(PHASE_ACCUSATION, 90)
            self.end_day_votes = set()
            self.lynch_target_id = None
            self.lynch_votes = {}
            self.night_actions = {}
        elif new_phase == PHASE_LYNCH:
            duration = self.timer_durations.get(PHASE_LYNCH, 60)
            self.lynch_votes = {}

        self.phase_end_time = time.time() + duration

    def tick(self):
        """
        Called every second by the main server loop.
        Returns 'TIMEOUT' if the timer just expired.
        """
        with self.lock:
            if self.timers_disabled:
                return None

            if self.phase_end_time and time.time() >= self.phase_end_time:
                # Prevent double firing
                self.phase_end_time = 0
                return "TIMEOUT"

            return None

    def advance_phase(self):
        """
        Automatically transitions to the next logical phase based on current state.
        Removes phase logic from app.py.
        """
        if self.phase == PHASE_NIGHT:
            self.set_phase(PHASE_ACCUSATION)

        elif self.phase == PHASE_LYNCH:
            self.set_phase(PHASE_NIGHT)

        elif self.phase == PHASE_ACCUSATION:
            self.set_phase(PHASE_NIGHT)

    def receive_night_action(self, player_id, target_id):
        """
        Store the player's intent. Process it later.
        Note: target_id can be a string ID or a Dict for complex actions (Witch).
        """
        with self.lock:
            if self.phase != PHASE_NIGHT or player_id not in self.players:
                return "IGNORED"

            if player_id in self.pending_actions:
                return "ALREADY_ACTED"

            self.pending_actions[player_id] = target_id
            self.turn_history.add(player_id)
            print(f"Action received from {self.players[player_id].name}")

            # 2. Check if we should resolve (Pass-and-Play Logic)
            if self.isPassAndPlay:
                living_count = len(self.get_living_players())
                acted_count = len(self.turn_history)

                print(f"PassAndPlay Status: {acted_count}/{living_count} have acted.")

                if acted_count >= living_count:
                    print("All players acted. Resolving Night...")
                    # Auto-transition to next phase usually happens inside resolve or app.py
                    return "RESOLVED"

            return "WAITING"

    def get_player_night_choice(self, player_id):
        """Returns the target ID the player submitted, or None."""
        choice = self.pending_actions.get(player_id)
        # if dict (Witch), extract target_id
        if isinstance(choice, dict):
            return choice.get("target_id")
        return choice

    def get_player_accusation(self, player_id):
        """Returns the ID of the player this user accused."""
        return self.accusations.get(player_id)

    def get_player_lynch_vote(self, player_id):
        """Returns 'yes' or 'no' if the player has voted."""
        return self.lynch_votes.get(player_id)

    def resolve_night_phase(self):
        print("--- RESOLVING NIGHT ---")

        # 1. Get all alive players with active roles
        active_players = [
            p for p in self.players.values() if p.is_alive and p.role.is_night_active
        ]

        # 2. Sort by Priority (Low number = First)
        # Bodyguard (0) goes before Werewolf (50)
        active_players.sort(key=lambda p: p.role.priority)

        werewolf_votes = []
        kill_list = set()

        # 3. Iterate and Execute
        # We pass a 'context' dict so roles can see the state of the game
        game_context = {
            "players": list(self.players.values()),
            "pending_actions": self.pending_actions,
        }

        for player in active_players:
            raw_action = self.pending_actions.get(player.id)

            target_id = None
            metadata = {}

            # Parse input (it might be a string ID or a dict with metadata)
            if isinstance(raw_action, dict):
                target_id = raw_action.get("target_id")
                metadata = raw_action.get("metadata", {})
            else:
                target_id = raw_action

            # Update context for roles that need metadata (e.g. Witch)
            game_context["current_action_metadata"] = metadata

            if not target_id or target_id == "Nobody":
                continue

            # Resolve ID to Player Object
            target_player_obj = self.players.get(target_id)
            if not target_player_obj:
                continue

            # Execute the Role's specific logic (polymorphism!)
            result = player.role.night_action(player, target_player_obj, game_context)

            # 4. Handle Results
            if result:  # might not need this if
                # Need to resolve the target player object from ID
                result_target_id = result.get("target")
                action_type = result.get("action")
                effect = result.get("effect")

                if result_target_id and effect:
                    # Resolve the target ID from the result to an object
                    t_obj = self.players.get(result_target_id)
                    if t_obj:
                        print(f"Effect Applied: {effect} on {t_obj.name}")
                        t_obj.status_effects.append(effect)

                self.night_log.append(
                    {
                        "player_id": player.id,
                        "message": f"Result: {result.get('result', 'Done')}",
                    }
                )

                if "poisoned" in target_player_obj.status_effects:
                    print(f"{target_player_obj.name} poisoned!")
                    kill_list.add(target_player_obj.id)

                # Handle Kill Votes (Werewolves)
                if action_type == "kill_vote":
                    werewolf_votes.append(result_target_id)

        # 4. Resolve Werewolf Votes
        # Unanimous vote kills, else no kill
        living_werewolves = self.get_living_players("werewolf")
        if (
            werewolf_votes
            and len(werewolf_votes) == len(living_werewolves)
            and len(set(werewolf_votes)) == 1
        ):
            target_id = werewolf_votes[0]
            if target_id in self.players:
                victim = self.players[target_id]
                target_name = victim.name
                print(f"Werewolves selected: {target_name}")

                if "protected" in victim.status_effects:
                    print(f"Attack on {target_name} blocked by protection!")
                elif "protected" in victim.status_effects:
                    print(f"Attack on {target_name} healed by Witch!")
                elif "immune_to_wolf" in victim.status_effects:
                    print(f"Attack on {target_name} failed (Immune)!")
                else:
                    kill_list.add(target_id)

        # 5. Process Deaths & Lovers Pact

        final_deaths = set()

        def process_death(pid):
            if pid in final_deaths:
                return
            final_deaths.add(pid)

            victim = self.players[pid]
            if not victim:
                return

            # Check Lovers
            if "lover" in victim.status_effects:
                lovers_to_kill = [
                    p
                    for p in self.players.values()
                    if p.is_alive
                    and p.id not in final_deaths
                    and "lover" in p.status_effects
                ]
                for partner in lovers_to_kill:
                    print(f"Lovers Pact: {partner.name} dies of grief!")
                    process_death(partner.id)

        for pid in kill_list:
            process_death(pid)

        # Apply State Changes
        for pid in final_deaths:
            player = self.players[pid]
            player.is_alive = False
            print(f"DIED: {self.players[pid].name}")

            # We pass the killer's ID or context if available (simplified here)
            if player.role:
                player.role.on_death(player, {"players": list(self.players.values())})

        return list(final_deaths)

    # --- DAY LOGIC (Accusations & Voting) ---

    def process_accusation(self, accuser_id, target_id):
        """Returns True if this accusation triggered a majority/all-voted condition (optional optimization)."""
        with self.lock:
            if self.phase != PHASE_ACCUSATION:
                return False
            if accuser_id in self.accusations:
                return False  # Already accused

            self.accusations[accuser_id] = target_id
            return len(self.accusations) >= len(self.get_living_players())

    def vote_to_sleep(self, player_id):
        """Returns True if majority wants to sleep."""
        with self.lock:
            if self.phase != PHASE_ACCUSATION:
                return False
            self.end_day_votes.add(player_id)

            # Check Majority
            living = len(self.get_living_players())
            return len(self.end_day_votes) > (living / 2)

    def tally_accusations(self):
        """
        Determines if we Lynch, Restart (Tie), or Sleep (No Accusations).
        Returns a dict describing the result.
        """
        # 1. No Accusations -> Night
        valid_votes = [v for v in self.accusations.values() if v]
        if not valid_votes:
            self.set_phase(PHASE_NIGHT)
            return {"result": "night", "message": "No accusations. Sleeping..."}

        # 2. Count
        counts = Counter(valid_votes)
        most_common = counts.most_common(2)

        # 3. if tie, restart accusations once
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            if self.accusation_restarts == 0:
                self.accusation_restarts += 1
                self.accusations = {}  # Reset
                # Return 'restart' but DO NOT change phase yet, app.py handles notification
                return {"result": "restart", "message": "Tie vote! Re-discuss."}
            else:
                self.set_phase(PHASE_NIGHT)
                return {"result": "night", "message": "Deadlock tie. No one lynched."}

        # 4. Lynch Trial
        self.lynch_target_id = most_common[0][0]
        self.set_phase(PHASE_LYNCH)
        return {
            "result": "trial",
            "target_id": self.lynch_target_id,
            "target_name": self.players[self.lynch_target_id].name,
        }

    def cast_lynch_vote(self, voter_id, vote):
        """Returns True if all players have voted."""
        with self.lock:
            if self.phase != PHASE_LYNCH:
                return False
            if vote not in ["yes", "no"]:
                return False

            self.lynch_votes[voter_id] = vote
            return len(self.lynch_votes) >= len(self.get_living_players())

    def resolve_lynch_vote(self):
        """
        Calculates lynch result. Apply death if needed. Checks Win.
        Returns result dict.
        """
        yes = list(self.lynch_votes.values()).count("yes")
        total = len(self.lynch_votes)

        result_data = {
            "summary": {"yes": [], "no": []},
            "killed_id": None,
            "game_over": False,
        }

        # Populate summary names
        for pid, v in self.lynch_votes.items():
            result_data["summary"][v].append(self.players[pid].name)

        # Majority YES required (> 50%)
        if yes > (total / 2):
            victim = self.players[self.lynch_target_id]
            victim.is_alive = False
            result_data["killed_id"] = self.lynch_target_id

            # TRIGGER ROLE HOOK
            if victim.role:
                victim.role.on_death(victim, {"players": list(self.players.values())})

            if self.check_game_over():
                result_data["game_over"] = True
                return result_data

        return result_data

    def check_game_over(self):
        """
        Checks all win conditions.
        Priority: 1. Solo Roles (Alpha_Werewolf, Fool) 2. Teams
        """
        active_players = self.get_living_players()
        game_context = {"players": list(self.players.values())}

        self.winner = None
        reason = ""
        # 1. Check Solo Win Conditions
        for p in active_players:
            if p.role and p.role.check_win_condition(p, game_context):
                self.winner = p.name
                reason = f"Solo Winner {self.winner} has met their goals!"

        # 2. Check Team Win Conditions
        wolves = self.get_living_players("werewolf")
        non_wolves_count = len(active_players) - len(wolves)

        # Villagers win if no wolves left
        if len(wolves) == 0:
            self.winner = "Villagers"
            reason = "All of the werewolves have been eradicated."

        # Wolves win if they outnumber villagers (or equal)
        elif len(wolves) >= non_wolves_count:
            self.winner = "Werewolves"
            reason = "The werewolves have taken over the village."

        if self.winner:
            self.phase = PHASE_GAME_OVER

            # CRITICAL: You must populate this data or the frontend will ignore the screen!
            self.game_over_data = {
                "winning_team": self.winner,
                "reason": reason,  # Or specific reason
                "final_player_states": [p.to_dict() for p in self.players.values()],
            }
            return True
        return False

    def get_game_state(self):
        """Returns the complete state for the frontend."""
        return {
            "game_id": self.game_id,
            "phase": self.phase,
            "players": [p.to_dict() for p in self.players.values()],
            "winner": self.winner,
        }
