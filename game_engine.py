"""
game_engine.py
# Version: 4.8.5
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
        PERSISTENT_EFFECTS = ["poisoned", "immune_to_wolf", "2nd_life", "solo_win"]
        self.status_effects = [
            effect for effect in self.status_effects if effect in PERSISTENT_EFFECTS
        ]

    def to_dict(self):
        """Serialize for frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "is_alive": self.is_alive,
            "role": self.role.name_key if self.role else None,
            "team": self.role.team if self.role else None,
            "status_effects": self.status_effects,
        }


class Game:
    def __init__(self, game_id, settings=None, mode="standard"):
        self.game_id = game_id
        self.settings = settings or {}
        self.mode = self.settings.get("mode", mode)
        self.isPassAndPlay = self.mode == "pass_and_play"
        self.ghost_mode = self.settings.get("ghost_mode", False)
        self.lock = RLock()
        self.message_history = []

        self.phase = PHASE_LOBBY
        self.phase_start_time = None
        self.phase_end_time = 0

        self.prompt_order = list(range(len(Role.VILLAGER_PROMPTS)))
        random.shuffle(self.prompt_order)
        self.night_count = -1

        self.players = {}  # Dict[session_id, Player_Obj]

        # Night Phase Data
        self.pending_actions = {}  # Dict[player_id, target_id]
        self.turn_history = set()  # set[player_id]
        self.night_log = []  # frontend logs e.g., "Seer saw a Werewolf"

        # Day Phase Data
        self.accusation_restarts = 0
        self.end_day_votes = set()  # set[voter_id]

        self.lynch_target_id = None

        # Admin/Meta Data
        self.admin_only_chat = False
        self.timers_disabled = False

        timers_settings = self.settings.get("timers", {})
        self.timers_disabled = timers_settings.get("timers_disabled", False)

        self.timer_durations = {
            PHASE_NIGHT: int(timers_settings.get("night", GAME_DEFAULTS["TIME_NIGHT"])),
            PHASE_ACCUSATION: int(
                timers_settings.get("accusation", GAME_DEFAULTS["TIME_ACCUSATION"])
            ),
            PHASE_LYNCH: int(
                timers_settings.get("lynch_vote", GAME_DEFAULTS["TIME_LYNCH"])
            ),
        }
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
            print(f"WARNING: Trimming roles for {num_players} players.")
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

    def is_ghost_mode_active(self):
        """Active only if setting enabled AND 2 or more players are dead."""
        dead_count = len(self.players) - len(self.get_living_players())
        return self.ghost_mode and dead_count >= 2

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
            self.night_count += 1
            self.pending_actions = {}
            self.turn_history = set()  # Reset tracker
            for player_obj in self.players.values():
                player_obj.reset_night_status()
                # trigger night hoooks
                if player_obj.role:
                    player_obj.role.on_night_start(
                        player_obj, {"players": list(self.players.values())}
                    )
        elif new_phase == PHASE_ACCUSATION:
            for player_obj in self.players.values():
                player_obj.visiting_id = None

            self.pending_actions = {}
            self.end_day_votes = set()
            self.lynch_target_id = None
        elif new_phase == PHASE_LYNCH:
            self.pending_actions = {}

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

    def get_current_prompt_index(self):
        """Returns the specific index for this night from the shuffled list."""
        if not self.prompt_order:
            return 0
        # Cycle through the shuffled list
        return self.prompt_order[self.night_count % len(self.prompt_order)]

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

            # Calculate who NEEDS to act (Alive + is_night_active)
            active_night_players = [
                p.id
                for p in self.players.values()
                if p.is_alive and p.role and p.role.is_night_active
            ]

            # Check if everyone has acted
            all_acted = set(active_night_players).issubset(self.turn_history)

            # 1. Check if we should resolve (Pass-and-Play Logic) All players active
            if self.isPassAndPlay:
                living_count = len(self.get_living_players())
                acted_count = len(self.turn_history)
                print(f"PassAndPlay Status: {acted_count}/{living_count} have acted.")
                if acted_count >= living_count:
                    print("All players acted. Resolving Night...")
                    # Auto-transition to next phase usually happens inside resolve or app.py
                    return "RESOLVED"
            # 2. Standard Timer Logic (NEW)
            # If timers are ACTIVE (not disabled) and everyone has acted, resolve early.
            elif not self.timers_disabled and all_acted:
                print("All active players submitted. Resolving Night early...")
                return "RESOLVED"

            return "WAITING"

    def get_player_phase_choice(self, player_id, get_meta=None):
        """Returns the target ID the player submitted, or None."""
        choice = self.pending_actions.get(player_id)
        # if dict (Witch), extract target_id
        if isinstance(choice, dict):
            if get_meta:
                # Returns the metadata dict (e.g. {'potion': 'heal'}) or None
                return choice.get("metadata")
            else:
                return choice.get("target_id")
        if get_meta:
            return None
        else:
            return choice

    def resolve_night_deaths(self):
        print("--- RESOLVING NIGHT Deaths & ACTIONS ---")

        # 1. Get all alive players with active roles
        active_player_objs = [
            p for p in self.players.values() if p.is_alive  # and p.role.is_night_active
        ]
        # Sort: Low priority number = Acts First
        active_player_objs.sort(key=lambda p: p.role.priority)

        werewolf_vote_ids = []
        pending_deaths = []  # List[Dict] [{"target_id": id, "reason": str}]
        blocked_player_ids = set()  # prostitute night block
        notifications = []
        villager_votes = []

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
                final_death_events.append(
                    {"id": player_obj.id, "type": "armor_save", "name": player_obj.name}
                )
                return final_death_events

            dead_ids_set.add(player_id)
            player_obj.is_alive = False
            print(f"DIED: {player_obj.name}, Reason: {reason}")

            for p in self.players.values():
                if p.is_alive and p.role and p.role.name_key == ROLE_WILD_CHILD:
                    # Check if the dying player is their Role Model, in case last werewolf
                    if getattr(p.role, "role_model_id", None) == player_id:
                        if not p.role.transformed:
                            game_context = {"players": list(self.players.values())}
                            p.role.on_night_start(p, game_context)

            final_death_events.append(
                {
                    "id": player_obj.id,
                    "type": "death",
                    "name": player_obj.name,
                    "role": player_obj.role.name_key,
                    "reason": reason,
                }
            )

            # Trigger Death Hook (hunter/backlash) return {"kill": target_id}
            ctx = {"players": list(self.players.values()), "reason": reason}
            death_reaction = player_obj.role.on_death(player_obj, ctx)

            if death_reaction:
                if "kill" in death_reaction:
                    retaliation_target_id = death_reaction["kill"]
                    custom_reason = death_reaction.get("reason", "Retaliation")

                    if (
                        retaliation_target_id
                        and retaliation_target_id not in dead_ids_set
                    ):
                        retaliation_target_obj = self.players.get(retaliation_target_id)
                        if retaliation_target_obj:
                            print(
                                f"Retaliation by {player_obj.name} on {retaliation_target_obj.name}!"
                            )
                        kill_recursive(retaliation_target_id, custom_reason)

                if death_reaction.get("type") == "announcement":
                    final_death_events.append(death_reaction)

            # Lovers Pact
            if player_obj.linked_partner_id:
                partner_player_obj = self.players.get(player_obj.linked_partner_id)
                if partner_player_obj and partner_player_obj.is_alive:
                    msg = f"💘 Lovers Pact: <strong>{partner_player_obj.name}</strong> dies of broken heart 💔"
                    print(msg)
                    kill_recursive(partner_player_obj.id, msg)

            # Prostitute Collateral Damage
            if player_obj.visiting_id:
                visitor_player_obj = self.players.get(player_obj.visiting_id)
                if visitor_player_obj and visitor_player_obj.is_alive:
                    msg = f"👠 Date damage: <strong>{visitor_player_obj.name}</strong> dies too 🔞  They were a <strong>{visitor_player_obj.role.name_key}</strong>"
                    print(msg)
                    kill_recursive(
                        visitor_player_obj.id,
                        msg,
                    )

        # 1. Execute Actions
        for player_obj in active_player_objs:
            if player_obj.id in blocked_player_ids:
                print(f"SKIPPED: {player_obj.name} was distracted by the Prostitute.")
                notifications.append(
                    {
                        "id": player_obj.id,
                        "type": "blocked",
                        "message": "💋 You were visited by the Prostitute and were too distracted to perform your night action!💦",
                    }
                )
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
            result = player_obj.role.night_action(
                player_obj, target_player_obj, game_context
            )

            if player_obj.role.name_key == "Prostitute" and target_player_obj:
                print(f"BLOCKING: {target_player_obj.name} visited by Prostitute.")
                blocked_player_ids.add(target_player_obj.id)
                # Handle Prostitute solo win here
                if player_obj.role.check_win_condition(player_obj, game_context):
                    if "solo_win" not in player_obj.status_effects:
                        player_obj.status_effects.append("solo_win")
                        # todo fix message only sent after refresh
                        msg = f'🥰 The <span style="color: #ff66aa">Prostitute {player_obj.name}</span> made a full circle and achieved a Solo Win🥇'
                        print(msg)
                        notifications.append(
                            {
                                "type": "announcement",
                                "message": msg,
                            }
                        )

            # 4. Handle Results
            if result:
                if result.get("type") == "announcement":
                    notifications.append(result)
                # Need to resolve the target player object from ID
                action_type = result.get("action")
                effect = result.get("effect")

                if target_player_obj and effect:
                    print(f"Effect Applied: {effect} on {target_player_obj.name}")
                    target_player_obj.status_effects.append(effect)

                self.night_log.append(
                    {
                        "player_id": player_obj.id,
                        "message": f"Result: {result.get('result', 'Done')}",
                    }
                )

                if "poisoned" in target_player_obj.status_effects:
                    print(f"{target_player_obj.name} poisoned!")
                    kill_recursive(
                        target_player_obj.id, result.get("reason", "Witch Poison")
                    )

                if action_type == "revealed_werewolf":
                    kill_recursive(
                        target_player_obj.id, result.get("reason", "Revealed")
                    )

                if action_type == "revealed_wrongly":
                    kill_recursive(player_obj.id, result.get("reason", "Revealed"))

                if action_type == "direct_kill":
                    kill_recursive(target_player_obj.id, result.get("reason", "Murder"))

                if action_type == "villager_vote" and target_player_obj:
                    villager_votes.append(target_player_obj.id)

                # Handle Kill Votes (Werewolves)
                if action_type == "kill_vote":
                    # For Werewolves, the target is the ID
                    werewolf_vote_ids.append(target_player_obj.id)

        if len(villager_votes) >= 3:
            # Find most common
            vote_counts = Counter(villager_votes)
            top_target_id, count = vote_counts.most_common(1)[0]

            if top_target_id in self.players:
                top_name = self.players[top_target_id].name

                idx = self.get_current_prompt_index()
                prompt_text = Role.VILLAGER_PROMPTS[idx]

                # Add to notifications (announced at end of night)
                notifications.append(
                    {
                        "type": "announcement",
                        "message": f"📊 <strong>Village Poll:</strong> <em>'{prompt_text}'</em> <red><strong>{top_name}</strong></red>",
                    }
                )

        # 4. Resolve Werewolf Votes
        # Unanimous vote kills, else no kill
        living_werewolves = self.get_living_players("Werewolves")
        active_werewolves = [
            w
            for w in living_werewolves
            if w.id not in blocked_player_ids and w.role.name_key != ROLE_SORCERER
        ]
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
                if victim_player_obj.is_alive:
                    if "protected" in victim_player_obj.status_effects:
                        print(
                            f"Attack on {victim_player_obj.name} blocked by protection!"
                        )
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

            player = self.players.get(accuser_id)
            if not player:
                return False

            # GHOST LOGIC
            vote_value = target_id
            if not player.is_alive:
                if not self.is_ghost_mode_active():
                    return False  # Dead cannot vote if ghost mode inactive

                # 25% Chance check
                if random.random() > 0.25:
                    vote_value = "Ghost_Fail"

            # Record the vote (if not already voted)
            if accuser_id not in self.pending_actions:
                self.pending_actions[accuser_id] = vote_value

            # CHECK: Have all LIVING players voted?
            living_voters = [
                pid for pid in self.pending_actions.keys() if self.players[pid].is_alive
            ]
            living_total = len(self.get_living_players())

            return len(living_voters) >= living_total

    def tally_accusations(self):
        valid_votes = [
            target_id
            for target_id in self.pending_actions.values()
            if target_id and target_id != "Ghost_Fail"
        ]

        if not valid_votes:
            self.set_phase(PHASE_NIGHT)
            return {"result": "night", "message": "No accusations. Sleeping..."}

        counts = Counter(valid_votes)
        most_common = counts.most_common(2)

        # if tie, restart accusations once
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            mayor = next(
                (
                    p
                    for p in self.players.values()
                    if p.is_alive and getattr(p.role, "next_mayor_id", None)
                ),
                None,
            )
            if mayor:
                mayor_vote = self.pending_actions.get(mayor.id)
                tied_candidate_1 = most_common[0][0]
                tied_candidate_2 = most_common[1][0]

                if mayor_vote == tied_candidate_1 or mayor_vote == tied_candidate_2:
                    self.lynch_target_id = mayor_vote

                    tie_msg = f"⚖️ <strong>Tie Vote!</strong> The Mayor broke the tie against <strong>{self.players[mayor_vote].name}!</strong>"
                    self.message_history.append(tie_msg)

                    self.set_phase(PHASE_LYNCH)
                    return {
                        "result": "trial",
                        "target_id": self.lynch_target_id,
                        "target_name": self.players[self.lynch_target_id].name,
                        "message": tie_msg,
                    }

            if self.accusation_restarts == 0:
                self.accusation_restarts += 1
                self.pending_actions = {}
                return {"result": "restart", "message": "⚖️ Tie vote! Re-discuss."}
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

            player = self.players.get(voter_id)
            if not player:
                return False

            # GHOST LOGIC
            # This prevents re-rolling the 10% chance by refreshing.
            if not player.is_alive and voter_id in self.pending_actions:
                return False

            vote_value = vote
            if not player.is_alive:
                if not self.is_ghost_mode_active():
                    return False
                # 10% Chance check
                if random.random() > 0.10:
                    vote_value = "Ghost_Fail"  # Failed roll

            # Record vote
            self.pending_actions[voter_id] = vote_value  # FIX: Use vote_value

            # CHECK: Have all LIVING players voted?
            living_voters = [
                pid for pid in self.pending_actions.keys() if self.players[pid].is_alive
            ]
            living_total = len(self.get_living_players())

            return len(living_voters) >= living_total

    def resolve_lynch_vote(self):
        """
        Calculates lynch result. Apply death if needed. Checks Win.
        Returns result dict.
        """
        yes_count = list(self.pending_actions.values()).count("yes")
        no_count = list(self.pending_actions.values()).count("no")
        total_valid_votes = yes_count + no_count

        result_data = {
            "summary": {"yes": [], "no": []},
            "killed_id": None,
            "armor_save": False,
            "game_over": False,
            "announcements": [],
            "secondary_deaths": [],
        }

        # Populate summary names
        for player_id, vote in self.pending_actions.items():
            if vote in ["yes", "no"]:
                p_name = self.players[player_id].name
                # Fix: Mask ghost names
                if not self.players[player_id].is_alive:
                    p_name = "Ghost"
                result_data["summary"][vote].append(p_name)

        if total_valid_votes > 0 and yes_count > (total_valid_votes / 2):
            # --- Lawyer Check ---
            target_obj = self.players[self.lynch_target_id]
            if "no_lynch" in target_obj.status_effects:
                # Cancel the death
                result_data["killed_id"] = None

                msg = f"⚖️ <strong>{target_obj.name}</strong> was voted out, but their <strong>Lawyer</strong> found a loophole! The lynch is cancelled!"
                result_data["announcements"].append(msg)

                # Return early (no recursion, no death)
                return result_data

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
                print(f"DIED2: {player_obj.name}, Reason: {reason}")

                if player_id != self.lynch_target_id:
                    print(f"DIED2:secondary_deaths {player_obj.name}, Reason: {reason}")
                    result_data["secondary_deaths"].append(
                        {
                            "id": player_id,
                            "name": player_obj.name,
                            "role": player_obj.role.name_key,
                            "reason": reason,
                        }
                    )

                # Wild Child Update in case last werewolf died
                for p in self.players.values():
                    if p.is_alive and p.role and p.role.name_key == ROLE_WILD_CHILD:
                        if getattr(p.role, "role_model_id", None) == player_id:
                            if not p.role.transformed:
                                game_context = {"players": list(self.players.values())}
                                p.role.on_night_start(p, game_context)

                ctx = {
                    "players": list(self.players.values()),
                    "reason": reason,
                    "lynch_votes": self.pending_actions,
                }
                death_reaction = player_obj.role.on_death(player_obj, ctx)

                if death_reaction:
                    if "kill" in death_reaction:
                        retaliation_target_id = death_reaction["kill"]
                        custom_reason = death_reaction.get("reason", "Retaliation")

                        if (
                            retaliation_target_id
                            and retaliation_target_id not in dead_ids_set
                        ):
                            retaliation_target_obj = self.players.get(
                                retaliation_target_id
                            )
                            if retaliation_target_obj:
                                print(
                                    f"🪚 Retaliation by {player_obj.name} on {retaliation_target_obj.name}! 🪓"
                                )
                            kill_recursive(retaliation_target_id, custom_reason)
                    if death_reaction.get("type") == "announcement":
                        result_data["announcements"].append(death_reaction["message"])

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
                        msg = f"👠 Date damage: <strong>{host_obj.name}</strong> dies too 🔞  They were a <strong>{host_obj.role.name_key}</strong>"
                        print(msg)
                        kill_recursive(host_obj.id, msg)

            # Start the chain reaction
            kill_recursive(self.lynch_target_id, "Lynched")

            # Check Win Conditions
            if result_data["killed_id"]:  # Only triggers if they actually died
                target_player_obj = self.players[result_data["killed_id"]]

                # Handle Fool Win immediately
                if target_player_obj.role.name_key == ROLE_FOOL:
                    solo_win_continues = self.settings.get("solo_win_continues", False)
                    msg = f"🤡 The Fool {target_player_obj.name} tricked you all and got lynched for a Solo Win! 🥇"
                    if solo_win_continues:
                        if "solo_win" not in target_player_obj.status_effects:
                            target_player_obj.status_effects.append("solo_win")
                            result_data["announcements"].append(msg)
                    else:
                        if "solo_win" not in target_player_obj.status_effects:
                            target_player_obj.status_effects.append("solo_win")
                        self.winner = target_player_obj.name
                        self.game_over_data = {
                            "winning_team": target_player_obj.name,
                            "reason": msg,
                            "final_player_states": [
                                p.to_dict() for p in self.players.values()
                            ],
                        }
                        result_data["game_over"] = True
                        return result_data

            if self.check_game_over():
                result_data["game_over"] = True

        return result_data

    def check_game_over(self):
        """
        Checks all win conditions.
        Priority: 1. Solo Roles 2. Teams
        """
        solo_win_continues = self.settings.get("solo_win_continues", False)

        if self.winner:
            return True

        active_player_objs = self.get_living_players()
        game_context = {"players": list(self.players.values())}

        self.winner = None
        reason = ""

        # 1. Solo Win Conditions
        for player_obj in active_player_objs:
            if player_obj.role and player_obj.role.check_win_condition(
                player_obj, game_context
            ):
                # last_man = player_obj.role.name_key in SOLO_LAST_MAN
                if (
                    solo_win_continues and len(active_player_objs) > 2
                ):  # and not last_man:
                    if "solo_win" not in player_obj.status_effects:
                        player_obj.status_effects.append("solo_win")
                        msg = f"🥇 <span style='color: #fdd835'>{player_obj.role.name_key}</span> has achieved a Solo Win!"
                        print(msg)
                        # todo fix message only sent after refresh
                        self.message_history.append(msg)
                else:
                    self.winner = player_obj.name
                    reason = f"Solo Winner <span style='color: #fdd835'>{player_obj.role.name_key} {self.winner}</span> has met their goals!"

        # 2. Check Team Win Conditions
        if not self.winner:
            wolves = self.get_living_players("Werewolves")
            non_wolves_count = len(active_player_objs) - len(wolves)

            # Villagers win if no wolves left
            if len(wolves) == 0:
                self.winner = "Villagers"
                reason = "All of the <span style='color: #880808'>Werewolves</span> have been eradicated."

            # Wolves win if they outnumber villagers (or equal)
            elif len(wolves) >= non_wolves_count:
                self.winner = "Werewolves"
                reason = "The <span style='color: #880808'>Werewolves</span> have taken over the village."

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
