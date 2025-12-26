"""
game_engine.py
# Version: 4.5.1
Manages the game flow, player states, complex role interactions, and phase transitions.
"""
import random
import time
from config import GAME_DEFAULTS
from collections import Counter
from roles import *
from threading import RLock

# --- Phases ---
PHASE_LOBBY = "Lobby"
PHASE_NIGHT = "Night"
PHASE_ACCUSATION = "Accusation"
PHASE_LYNCH = "Lynch_Vote"
PHASE_GAME_OVER = "Game_Over"


class Player:
    def __init__(self, session_id, name):
        self.id = session_id
        self.lock = RLock()
        self.name = name
        self.role = None  # Will be an instance of a Role class
        self.is_alive = True
        self.status_effects = []  # e.g., ['protected', 'poisoned']
        self.linked_partner_id = None  # For Cupid's lovers
        self.visiting_id = None  # for prostitue

    def reset_night_status(self):
        PERSISTENT_EFFECTS = ["poisoned", "immune_to_wolf", "2nd_life"]
        self.status_effects = [
            effect for effect in self.status_effects if effect in PERSISTENT_EFFECTS
        ]
        self.visiting_id = None

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
        self.message_history = []

        self.phase = PHASE_LOBBY
        self.phase_start_time = None
        self.phase_end_time = 0

        self.players = {}  # Dict[session_id, Player_Obj]

        # Night Phase Data
        self.pending_actions = {}  # Dict[player_id, target_id]
        self.turn_history = set()  # set[player_id]
        self.night_log = []  # frontend logs e.g., "Seer saw a Werewolf"

        # Day Phase Data
        self.accusations = {}  # Dict[accuser_id, target_id]
        self.accusation_restarts = 0
        self.end_day_votes = set()  # set[voter_id]

        self.lynch_target_id = None
        self.lynch_votes = {}  # Dict[voter_id, "yes"/"no"]

        # Admin/Meta Data
        self.admin_only_chat = False
        self.timers_disabled = False
        self.timer_durations = {PHASE_NIGHT:
                                GAME_DEFAULTS["TIME_NIGHT"], PHASE_ACCUSATION:
                                GAME_DEFAULTS["TIME_ACCUSATION"], PHASE_LYNCH:
                                GAME_DEFAULTS["TIME_LYNCH"]}
        self.current_timer_id = 0  # increment id to invalidate old async timers

        # End Game Data
        self.winner = None
        self.game_over_data = None
        self.rematch_votes = set()

    # --- Game Management ---
    def add_player(self, session_id, name):
        if session_id not in self.players:
            self.players[session_id] = Player(session_id, name)

    def remove_player(self, session_id):
        if session_id in self.players:
            del self.players[session_id]

    def assign_roles(self, selected_role_keys):
        """
        1. Calculates Wolves/Seer based on total players.
        2. Assigns special roles
        3. Fills remainder with Villagers.
        4. Assigns randomly.
        """
        print("Starting role assignment process...")

        # 1. Build Map: 'werewolf' -> RoleWerewolf Class
        key_to_class_map = {}
        for role_name, role_cls in AVAILABLE_ROLES.items():
            temp_role_obj = role_cls()
            key_to_class_map[temp_role_obj.name_key] = role_cls

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
            num_wolves = max(1, int(num_players * 0.25))

        # 4. Construct the Master Role List
        final_roles_list = []
        special_werewolves_added = 0

        for r_key in selected_role_keys:
            if r_key not in GAME_DEFAULTS["DEFAULT_ROLES"]:
                final_roles_list.append(r_key)
                if r_key in SPECIAL_WEREWOLVES:
                    special_werewolves_added += 1

        # Add Regular Werewolves (total - special)
        remaining_wolves_needed = max(0, num_wolves - special_werewolves_added)
        for _ in range(remaining_wolves_needed):
            final_roles_list.append(ROLE_WEREWOLF)

        # Fill remainder with Villagers
        while len(final_roles_list) < num_players:
            final_roles_list.append(ROLE_VILLAGER)

        # Safety: If we have too many roles (e.g. 4 players but 5 specials picked), trim the end.
        if len(final_roles_list) > num_players:
            print(
                f"WARNING: Trimming roles for {num_players} players."
            )
            final_roles_list = final_roles_list[:num_players]

        # 2nd Shuffle of roles to ensure randomnes
        random.shuffle(final_roles_list)

        print(f"Final List of Role Keys to Assign: {final_roles_list}")

        # Assign Roles
        # We perform safe zip: Stop if we run out of players or roles
        for player_id, role_key in zip(player_ids, final_roles_list):
            # Reset player state
            self.players[player_id].is_alive = True
            # Lookup the class, default to Villager if key missing
            role_class = key_to_class_map.get(role_key, AVAILABLE_ROLES["Villager"])

            # Instantiate and Assign
            player_obj = self.players[player_id]
            player_obj.role = role_class()
            player_obj.role.on_assign(player_obj)

            print(f"Assigned {role_class.__name__} to {player_obj.name}")

        print(f"Roles assigned for Game {self.game_id} (Mode: {self.mode})")

    def get_living_players(self, role_team=None):
        living_players = [p for p in self.players.values() if p.is_alive]
        if role_team:
            return [p for p in living_players if p.role.team == role_team]
        return living_players

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
            self.night_actions = {}
            self.night_log = []
            self.pending_actions = {}
            self.turn_history = set()  # Reset tracker
            for player_obj in self.players.values():
                player_obj.reset_night_status()
                # trigger night hoooks
                if player_obj.role:
                    player_obj.role.on_night_start(player_obj, {"players": list(self.players.values())})
        elif new_phase == PHASE_ACCUSATION:
            self.accusations = {}
            self.end_day_votes = set()
            self.lynch_target_id = None
            self.lynch_votes = {}
        elif new_phase == PHASE_LYNCH:
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
            # todo is this even needed?
            return choice.get("target_id")
        return choice

    def get_player_night_metadata(self, player_id):
        """Returns the metadata dict (e.g. {'potion': 'heal'}) or None."""
        choice = self.pending_actions.get(player_id)
        if isinstance(choice, dict):
            return choice.get("metadata")
        return None

    def get_player_accusation(self, player_id):
        """Returns the ID of the player this user accused."""
        return self.accusations.get(player_id)

    def get_player_lynch_vote(self, player_id):
        """Returns 'yes' or 'no' if the player has voted."""
        return self.lynch_votes.get(player_id)

    def resolve_night_deaths(self):
        print("--- RESOLVING NIGHT Deaths & ACTIONS ---")

        # 1. Get all alive players with active roles
        active_player_objs = [
            p for p in self.players.values() if p.is_alive and p.role.is_night_active
        ]
        # Sort: Low priority number = Acts First
        active_player_objs.sort(key=lambda p: p.role.priority)

        werewolf_vote_ids = []
        pending_deaths = []  # List[Dict] [{"target_id": id, "reason": str}]
        blocked_player_ids = set() # prostitute night block
        notifications = []

        # 3. Iterate and Execute
        # We pass a 'context' dict so roles can see the state of the game
        game_context = {
            "players": list(self.players.values()),
            "pending_actions": self.pending_actions,
        }

        dead_ids_set = set()
        final_death_events = []

        def kill_recursive(player_id, reason):
            # target.is_alive=False, execute death hook, kill lover
            player_obj = self.players[player_id]

            # Armor Check
            if "2nd_life" in player_obj.status_effects:
                print(f"{player_obj.name} used their 2nd life!")
                player_obj.status_effects.remove("2nd_life")
                final_death_events.append({
                    "id": player_obj.id,
                    "type": "armor_save",
                    "name": player_obj.name
                })
                return final_death_events

            dead_ids_set.add(player_id)
            player_obj.is_alive = False
            print(f"DIED: {player_obj.name}, Reason: {reason}")


            for p in self.players.values():
                if p.is_alive and p.role and p.role.name_key == ROLE_WILD_CHILD:
                    # Check if the dying player is their Role Model
                    if getattr(p.role, "role_model_id", None) == player_id:
                        if not p.role.transformed:
                            p.role.transformed = True
                            p.role.team = "werewolf"
                            p.role.is_night_active = True
                            p.priority = 45
                            print(f"Wild Child {p.name} transformed into a Werewolf!")

            final_death_events.append({
                "id": player_obj.id,
                "type": "death",
                "name": player_obj.name,
                "role": player_obj.role.name_key,
                "reason": reason,
            })

            # Trigger Death Hook (hunter/backlash) return {"kill": target_id}
            ctx = {"players": list(self.players.values()), "reason": reason}
            death_reaction = player_obj.role.on_death(player_obj, ctx )

            if death_reaction and "kill" in death_reaction:
                retaliation_target_id = death_reaction["kill"]
                if retaliation_target_id and retaliation_target_id not in dead_ids_set:
                    print(f"Retaliation by {player_obj.name} on {retaliation_target_id}!")
                    kill_recursive(retaliation_target_id, "Retaliation")

            # Lovers Pact
            if player_obj.linked_partner_id:
                partner_player_obj = self.players.get(player_obj.linked_partner_id)
                if partner_player_obj and partner_player_obj.is_alive:
                    print(f"Lovers Pact: {partner_player_obj.name} dies of broken heart.")
                    kill_recursive(partner_player_obj.id, "Love Pact")

            # Prostitute Collateral Damage
            if player_obj.visiting_id:
                visitor_player_obj = self.players.get(player_obj.visiting_id)
                if visitor_player_obj and visitor_player_obj.is_alive:
                    print(f"Date damage: {visitor_player_obj.name} dies too.")
                    kill_recursive(visitor_player_obj.id, "Collateral Damage")


        # 1. Execute Actions
        for player_obj in active_player_objs:
            if player_obj.id in blocked_player_ids:
                print(f"SKIPPED: {player_obj.name} was distracted by the Prostitute.")
                notifications.append({
                    "id": player_obj.id,
                    "type": "blocked",
                    "message": "💋 You were visited by the Prostitute and were too distracted to perform your action!"
                })
                continue

            raw_action = self.pending_actions.get(player_obj.id)
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
            result = player_obj.role.night_action(player_obj, target_player_obj, game_context)

            if player_obj.role.name_key == "Prostitute" and target_player_obj:
                print(f"BLOCKING: {target_player_obj.name} visited by Prostitute.")
                blocked_player_ids.add(target_player_obj.id)

            # 4. Handle Results
            if result:
                # Need to resolve the target player object from ID
                action_type = result.get("action")
                effect = result.get("effect")


                if target_player_obj.id and effect:
                    print(f"Effect Applied: {effect} on {target_player_obj.name}")
                    target_player_obj.status_effects.append(effect)

                self.night_log.append(
                    {"player_id": player_obj.id,
                    "message": f"Result: {result.get('result', 'Done')}", })

                if "poisoned" in target_player_obj.status_effects:
                    print(f"{target_player_obj.name} poisoned!")
                    kill_recursive(target_player_obj.id, result.get("reason", "Witch Poison"))

                if action_type == "revealed_werewolf":
                    kill_recursive(target_player_obj.id, result.get("reason", "Revealed"))

                if action_type == "revealed_wrongly":
                    kill_recursive(player_obj.id, result.get("reason", "Revealed"))

                # Handle Kill Votes (Werewolves)
                if action_type == "kill_vote":
                    # For Werewolves, the target is the ID
                    werewolf_vote_ids.append(target_player_obj.id)

        # 4. Resolve Werewolf Votes
        # Unanimous vote kills, else no kill
        living_werewolves = self.get_living_players("werewolf")
        active_werewolves = [w for w in living_werewolves if w.id not in
                             blocked_player_ids and w.role.name_key != ROLE_SORCERER]
        if (
            werewolf_vote_ids
            and len(active_werewolves) > 0
            and len(werewolf_vote_ids) >= len(active_werewolves)
            and len(set(werewolf_vote_ids)) == 1
        ):
            target_id = werewolf_vote_ids[0]
            if target_id in self.players:
                victim_player_obj = self.players[target_id]
                print(f"Werewolves selected: {victim_player_obj.name}")

                if "protected" in victim_player_obj.status_effects:
                    print(f"Attack on {victim_player_obj.name} blocked by protection!")
                elif "healed" in victim_player_obj.status_effects:
                    print(f"Attack on {victim_player_obj.name} healed by Witch!")
                elif "immune_to_wolf" in victim_player_obj.status_effects:
                    print(f"Attack on {victim_player_obj.name} failed (Immune)!")
                else:
                    pending_deaths.append(
                        {"target_id": target_id, "reason": "Werewolf meat"}
                    )
        # 5. Process Deaths & Lovers Pact
        for death_record in pending_deaths:
            kill_recursive(death_record["target_id"], death_record["reason"])

        return final_death_events + notifications

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
            return len(self.end_day_votes) > (len(self.get_living_players()) / 2)

    def tally_accusations(self):
        valid_votes = [target_id for target_id in self.accusations.values() if target_id]

        if not valid_votes:
            self.set_phase(PHASE_NIGHT)
            return {"result": "night", "message": "No accusations. Sleeping..."}

        counts = Counter(valid_votes)
        most_common = counts.most_common(2)

        # if tie, restart accusations once
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            if self.accusation_restarts == 0:
                self.accusation_restarts += 1
                self.accusations = {}
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
        yes_count = list(self.lynch_votes.values()).count("yes")
        total_votes = len(self.lynch_votes)

        result_data = {
            "summary": {"yes": [], "no": []},
            "killed_id": None,
            "armor_save": False,
            "game_over": False,
        }

        # Populate summary names
        for player_id, vote in self.lynch_votes.items():
            result_data["summary"][vote].append(self.players[player_id].name)

        if yes_count > (total_votes / 2):
            result_data["killed_id"] = self.lynch_target_id
            dead_ids_set = set()

            def kill_recursive(player_id, reason):
                # target.is_alive=False, execute death hook, kill lover
                player_obj = self.players[player_id]

                # Armor Check
                if "2nd_life" in player_obj.status_effects:
                    print(f"{player_obj.name} used their 2nd life!")
                    player_obj.status_effects.remove("2nd_life")
                    result_data["killed_id"] = None
                    result_data["armor_save"] = True
                    return  # CANCEL DEATH

                dead_ids_set.add(player_id)
                player_obj.is_alive = False
                print(f"DIED: {player_obj.name}, Reason: {reason}")

                # Wild Child Update
                for p in self.players.values():
                    if p.is_alive and p.role and p.role.name_key == ROLE_WILD_CHILD:
                        if getattr(p.role, "role_model_id", None) == player_id:
                            if not p.role.transformed:
                                p.role.transformed = True
                                p.role.team = "werewolf"
                                p.role.is_night_active = True
                                p.priority = 45
                                print(f"Wild Child {p.name} transformed into a Werewolf!")

                ctx = {
                "players": list(self.players.values()),
                "reason": reason,
                "lynch_votes": self.lynch_votes
                }
                death_reaction = player_obj.role.on_death(player_obj, ctx)

                # Trigger Death Hook (hunter/backlash) return {"kill": target_id}
                death_reaction = player_obj.role.on_death(player_obj, {"players": list(self.players.values())})

                if death_reaction and "kill" in death_reaction:
                    retaliation_target_id = death_reaction["kill"]
                    if retaliation_target_id and retaliation_target_id not in dead_ids_set:
                        print(f"Retaliation by {player_obj.name} on {retaliation_target_id}!")
                        kill_recursive(retaliation_target_id, "Retaliation")

                # Check Lovers
                if player_obj.linked_partner_id:
                    partner_obj = self.players.get(player_obj.linked_partner_id)
                    if partner_obj and partner_obj.is_alive:
                        print(f"Lovers Pact: {partner_obj.name} dies of broken heart.")
                        kill_recursive(partner_obj.id, "Love Pact")

                # Check Prostitute
                if player_obj.visiting_id:
                    host_obj = self.players.get(player_obj.visiting_id)
                    if host_obj and host_obj.is_alive:
                        print(f"Date damage: {host_obj.name} dies too.")
                        kill_recursive(host_obj.id, "Collateral Damage")

            # Start the chain reaction
            kill_recursive(self.lynch_target_id, "Lynched")

            # Check Win Conditions
            if result_data["killed_id"]: # Only triggers if they actually died
                target_player_obj = self.players[result_data["killed_id"]]

                # Handle Fool Win immediately
                if target_player_obj.role.name_key == ROLE_FOOL:
                    self.winner = target_player_obj.name
                    self.game_over_data = {
                            "winning_team": target_player_obj.name,
                            "reason": "The Fool tricked you all and got lynched!",
                            "final_player_states": [p.to_dict() for p in self.players.values()],
                            }
                    result_data["game_over"] = True
                    return result_data

            if self.check_game_over():
                result_data["game_over"] = True

        return result_data

    def check_game_over(self):
        """
        Checks all win conditions.
        Priority: 1. Solo Roles (Alpha_Werewolf, Fool) 2. Teams
        """
        if self.winner:
             return True

        active_player_objs = self.get_living_players()
        game_context = {"players": list(self.players.values())}

        self.winner = None
        reason = ""

        # 1. Solo Win Conditions
        for player_obj in active_player_objs:
            if player_obj.role and player_obj.role.check_win_condition(player_obj, game_context):
                self.winner = player_obj.name
                reason = f"Solo Winner {player_obj.role.name_key} {self.winner} has met their goals!"

        # 2. Check Team Win Conditions
        wolves = self.get_living_players("werewolf")
        non_wolves_count = len(active_player_objs) - len(wolves)

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
                "reason": reason,
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
