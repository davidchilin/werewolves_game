"""
game_engine.py
Version: 5.0.0
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

        self.prompt_order = list(range(Role.VILLAGER_PROMPT_COUNT))
        random.shuffle(self.prompt_order)
        self.night_count = -1

        self.players = {}  # Dict[session_id, Player_Obj]

        # Night Phase Data
        self.pending_actions = {}  # Dict[player_id, target_id]
        self.turn_history = set()  # set[player_id]

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
            r_key = getattr(role_cls, "name_key", role_name)
            key_to_class_map[r_key] = role_cls

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
            num_wolves = max(1, int(num_players * GAME_DEFAULTS["WOLF_RATIO"]))

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
        if not self.prompt_order:
            return 0
        # Use night_count to rotate through the shuffled list
        # We use absolute value or max(0) to ensure positive index if night_count is -1
        safe_night = max(0, self.night_count)
        return self.prompt_order[safe_night % len(self.prompt_order)]

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

    def execute_death_cascade(self, initial_targets, context="night"):
        """
        Centralized logic for processing deaths, saves, and chain reactions.
        Args:
            initial_targets: List of tuples [(player_id, reason), ...]
            context: "night" or "lynch" (used for context in on_death hooks)
        Returns:
            Dict containing lists of 'deaths', 'armor_saves', 'announcements'.
        """
        events = {
            "deaths": [],  # {id, name, role, reason}
            "armor_saves": [],  # {id, name}
            "announcements": [],  # strings
        }

        # Use a list as a queue to handle chain reactions (Lovers, Retaliation)
        queue = list(initial_targets)
        processed_ids = set()  # Prevent infinite loops in this cascade

        while queue:
            pid, reason = queue.pop(0)

            if pid in processed_ids:
                continue

            player = self.players.get(pid)
            if not player or not player.is_alive:
                continue

            # 1. Armor / 2nd Life Check
            if "2nd_life" in player.status_effects:
                print(f"{player.name} used their 2nd life!")
                player.status_effects.remove("2nd_life")
                events["armor_saves"].append({"id": pid, "name": player.name})
                continue  # Stop processing this death

            # 2. Mark Dead
            player.is_alive = False
            processed_ids.add(pid)

            # Record Death Event
            events["deaths"].append(
                {
                    "id": pid,
                    "name": player.name,
                    "role": player.role.name_key,
                    "reason": reason,
                }
            )
            print(f"DIED ({context}): {player.name}, Reason: {reason}")

            # 3. Wild Child Check
            # Check if any ALIVE Wild Child was linked to this DEAD player
            for p in self.players.values():
                if p.is_alive and p.role and p.role.name_key == ROLE_WILD_CHILD:
                    if getattr(p.role, "role_model_id", None) == pid:
                        if not p.role.transformed:
                            # Re-trigger night start to handle transformation logic
                            # (Sets transformed=True, team=Werewolves)
                            game_context = {"players": list(self.players.values())}
                            p.role.on_night_start(p, game_context)

            # 4. Role 'on_death' Hooks (Hunter, Honeypot, etc.)
            ctx = {"players": list(self.players.values()), "reason": reason}
            if context == "lynch":
                ctx["lynch_votes"] = self.pending_actions

            death_reaction = player.role.on_death(player, ctx)
            if death_reaction:
                # Handle Retaliation Kills
                if "kill" in death_reaction:
                    target_id = death_reaction["kill"]
                    custom_reason = death_reaction.get("reason", "Retaliation")
                    # Add to queue if valid
                    if target_id and target_id not in processed_ids:
                        queue.append((target_id, custom_reason))
                        target_obj = self.players.get(target_id)
                        if target_obj:
                            print(f"Retaliation by {player.name} on {target_obj.name}")

                # Handle Announcements
                if death_reaction.get("type") == "announcement":
                    events["announcements"].append(death_reaction["message"])

            # 5. Lovers Pact
            if player.linked_partner_id:
                partner = self.players.get(player.linked_partner_id)
                if partner and partner.is_alive and partner.id not in processed_ids:
                    msg = {
                        "key": "events.lovers_pact",
                        "variables": {
                            "name": partner.name,
                            "role": partner.role.name_key,
                        },
                    }
                    print(f"Lovers Pact death: {partner.name}")
                    queue.append((partner.id, msg))

            # 6. Prostitute Collateral Damage
            # If the player was visiting someone (or was visited), the other person dies.
            # (Logic is bidirectional: visiting_id is set on both parties during night action)
            if player.visiting_id:
                other_node = self.players.get(player.visiting_id)
                if (
                    other_node
                    and other_node.is_alive
                    and other_node.id not in processed_ids
                ):
                    msg = {
                        "key": "events.prostitute_collat",
                        "variables": {
                            "name": other_node.name,
                            "role": other_node.role.name_key,
                        },
                    }
                    print(f"Prostitute damage: {other_node.name}")
                    queue.append((other_node.id, msg))

        return events

    def resolve_night_deaths(self):
        print("--- RESOLVING NIGHT Deaths & ACTIONS ---")

        active_player_objs = [p for p in self.players.values() if p.is_alive]
        active_player_objs.sort(key=lambda p: p.role.priority)

        werewolf_vote_ids = []
        blocked_player_ids = set()
        villager_votes = []

        # Accumulate all outcomes here
        final_events = []
        game_context = {
            "players": list(self.players.values()),
            "pending_actions": self.pending_actions,
        }

        # Helper to merge cascade results into final_events list
        def merge_cascade_results(cascade_dict):
            for d in cascade_dict["deaths"]:
                final_events.append(
                    {
                        "type": "death",
                        "id": d["id"],
                        "name": d["name"],
                        "role": d["role"],
                        "reason": d["reason"],
                    }
                )
            for s in cascade_dict["armor_saves"]:
                final_events.append(
                    {"type": "armor_save", "id": s["id"], "name": s["name"]}
                )
            for a in cascade_dict["announcements"]:
                final_events.append({"type": "announcement", "message": a})

        # 1. Execute Night Actions
        for player_obj in active_player_objs:
            # Skip if dead (e.g. killed by Witch earlier in loop)
            if not player_obj.is_alive:
                continue

            if player_obj.id in blocked_player_ids:
                print(f"SKIPPED: {player_obj.name}")
                final_events.append(
                    {
                        "id": player_obj.id,
                        "type": "blocked",
                        # "message": "💋 You were visited by the Prostitute and were too distracted to perform your night action!💦",
                        "message": {"key": "events.prostitute_block", "variables": {}},
                    }
                )
                continue

            raw_action = self.pending_actions.get(player_obj.id)
            if isinstance(raw_action, dict):
                target_id = raw_action.get("target_id")
                game_context["current_action_metadata"] = raw_action.get("metadata", {})
            else:
                target_id = raw_action
                game_context["current_action_metadata"] = {}

            if not target_id or target_id == "Nobody":
                continue

            target_player_obj = self.players.get(target_id)

            # Execute Role Logic
            result = player_obj.role.night_action(
                player_obj, target_player_obj, game_context
            )

            # Prostitute Block Logic
            if player_obj.role.name_key == ROLE_PROSTITUTE and target_player_obj:
                print(f"BLOCKING: {target_player_obj.name} visited by Prostitute.")
                blocked_player_ids.add(target_player_obj.id)
                # Handle Prostitute solo win here
                if player_obj.role.check_win_condition(player_obj, game_context):
                    if "solo_win" not in player_obj.status_effects:
                        player_obj.status_effects.append("solo_win")
                        # msg = f'🥰 The <span style="color: #ff66aa">Prostitute</span> made many friends and achieved a Solo Win🥇'
                        msg = {
                            "key": "events.prostitute_win",
                            "variables": {"name": player_obj.name},
                        }
                        final_events.append({"type": "announcement", "message": msg})

            # 4. Handle Results
            if result:
                if result.get("type") == "announcement":
                    final_events.append(result)

                action_type = result.get("action")
                effect = result.get("effect")

                if target_player_obj and effect:
                    print(f"Effect Applied: {effect} on {target_player_obj.name}")
                    target_player_obj.status_effects.append(effect)

                # IMMEDIATE DEATHS (Witch / Revealer / Serial Killer)
                immediate_deaths = []
                if target_player_obj and "poisoned" in target_player_obj.status_effects:
                    immediate_deaths.append(
                        (target_player_obj.id, result.get("reason", "Witch Poison"))
                    )

                if action_type in ["revealed_werewolf", "direct_kill"]:
                    if target_player_obj:
                        immediate_deaths.append(
                            (target_player_obj.id, result.get("reason", "Murder"))
                        )
                elif action_type == "revealed_wrongly":
                    immediate_deaths.append(
                        (player_obj.id, result.get("reason", "Revealed"))
                    )

                # Execute Immediate Cascade
                if immediate_deaths:
                    cascade_results = self.execute_death_cascade(
                        immediate_deaths, context="night"
                    )
                    merge_cascade_results(cascade_results)

                if action_type == "villager_vote" and target_player_obj:
                    villager_votes.append(target_player_obj.id)
                if action_type == "kill_vote" and target_player_obj:
                    werewolf_vote_ids.append(target_player_obj.id)

        # 2. Village Poll Announcement
        if len(villager_votes) >= 3:
            # Find most common
            vote_counts = Counter(villager_votes)
            top_target_id, count = vote_counts.most_common(1)[0]

            if top_target_id in self.players:
                idx = self.get_current_prompt_index()

                # [CHANGED] Generate key instead of accessing list
                safe_idx = idx % Role.VILLAGER_PROMPT_COUNT
                prompt_key = f"prompts.villager_{safe_idx}"

                final_events.append(
                    {
                        "type": "announcement",
                        "message": {
                            "key": "events.village_poll",
                            "variables": {
                                "prompt": prompt_key,  # Frontend will translate this key recursively
                                "target": self.players[top_target_id].name,
                            },
                        },
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

        pending_wolf_kills = []
        if werewolf_vote_ids and len(active_werewolves) > 0:
            # Simple Logic: Unanimous (or majority depending on your rules, simplified to unanimous/single target here based on previous code)
            # Your previous code checked len(set(ids)) == 1
            if len(set(werewolf_vote_ids)) == 1 and len(werewolf_vote_ids) >= len(
                active_werewolves
            ):
                target_id = werewolf_vote_ids[0]
                victim = self.players.get(target_id)
                if victim and victim.is_alive:
                    if "protected" in victim.status_effects:
                        print(f"Attack on {victim.name} blocked by protection!")
                    elif "healed" in victim.status_effects:
                        print(f"Attack on {victim.name} healed by Witch!")
                    elif "immune_to_wolf" in victim.status_effects:
                        print(f"Attack on {victim.name} failed (Immune)!")
                    else:
                        pending_wolf_kills.append((target_id, "Werewolf meat"))

        # 4. Execute End-of-Night Cascade
        if pending_wolf_kills:
            cascade_results = self.execute_death_cascade(
                pending_wolf_kills, context="night"
            )
            merge_cascade_results(cascade_results)

        return final_events

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
            return {"result": "night", "message": "No accusations.🌒 Sleeping..."}

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

                    # tie_msg = f"⚖️ <strong>Tie Vote!</strong> The Mayor broke the tie against <strong>{self.players[mayor_vote].name}!</strong>"
                    tie_msg = {
                        "key": "events.mayor_tie",
                        "variables": {"target": self.players[mayor_vote].name},
                    }
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
                # return {"result": "restart", "message": "⚖️ Tie vote! Re-discuss."}
                return {
                    "result": "restart",
                    "message": {"key": "events.tie_restart", "variables": {}},
                }
            else:
                self.set_phase(PHASE_NIGHT)
                # return {"result": "night", "message": "Deadlock tie. No one lynched."}
                return {
                    "result": "night",
                    "message": {"key": "events.tie_deadlock", "variables": {}},
                }

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
        living_total = len(self.get_living_players())

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

        # Determine Lynch Result
        if yes_count and yes_count > (living_total / 2):
            target_obj = self.players[self.lynch_target_id]

            # Lawyer Check
            if "no_lynch" in target_obj.status_effects:
                # Cancel the death
                result_data["killed_id"] = None
                msg = {
                    "key": "events.lawyer_save",
                    "variables": {"name": target_obj.name},
                }
                result_data["announcements"].append(msg)
                return result_data

            # EXECUTE CASCADE
            cascade = self.execute_death_cascade(
                [(self.lynch_target_id, "Lynched")], context="lynch"
            )

            # Map results to result_data
            # 1. Identify primary death vs secondary
            for d in cascade["deaths"]:
                if d["id"] == self.lynch_target_id:
                    result_data["killed_id"] = d["id"]
                else:
                    result_data["secondary_deaths"].append(d)

            # 2. Check Armor Save on Target
            for s in cascade["armor_saves"]:
                if s["id"] == self.lynch_target_id:
                    result_data["armor_save"] = True
                    # If saved, killed_id should be None
                    result_data["killed_id"] = None

            # 3. Add Announcements
            result_data["announcements"].extend(cascade["announcements"])

            # 4. Check Win Conditions (Fool)
            if result_data["killed_id"]:
                killed_obj = self.players[result_data["killed_id"]]
                if killed_obj.role.name_key == ROLE_FOOL:
                    solo_win_continues = self.settings.get("solo_win_continues", False)
                    # msg = f"🤡 The Fool {killed_obj.name} tricked you all and got lynched for a Solo Win! 🥇"
                    msg = {
                        "key": "events.fool_win",
                        "variables": {"name": killed_obj.name},
                    }

                    if "solo_win" not in killed_obj.status_effects:
                        killed_obj.status_effects.append("solo_win")

                    if not solo_win_continues:
                        self.winner = killed_obj.name
                        self.game_over_data = {
                            "winning_team": killed_obj.name,
                            "reason": msg,
                            "final_player_states": [
                                p.to_dict() for p in self.players.values()
                            ],
                        }
                        result_data["game_over"] = True
                        return result_data
                    else:
                        result_data["announcements"].append(msg)

            # 5. Check Game Over
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
                        # msg = f"🥇 <span style='color: #fdd835'>{player_obj.role.name_key}</span> has achieved a Solo Win!"
                        msg = {
                            "key": "events.solo_win_continue",
                            "variables": {
                                "role": player_obj.role.name_key,
                                "name": player_obj.name,
                            },
                        }
                        print(f"Solo win recorded for {player_obj.name}")
                        # todo fix message only sent after refresh
                        self.message_history.append(msg)
                else:
                    self.winner = player_obj.name
                    # reason = f"Solo Winner <span style='color: #fdd835'>{player_obj.role.name_key} {self.winner}</span> has met their goals!"
                    reason = {
                        "key": "events.win_solo",
                        "variables": {
                            "role": player_obj.role.name_key,
                            "name": self.winner,
                        },
                    }

        # 2. Check Team Win Conditions
        if not self.winner:
            wolves = self.get_living_players("Werewolves")
            non_wolves_count = len(active_player_objs) - len(wolves)

            # Villagers win if no wolves left
            if len(wolves) == 0:
                self.winner = "Villagers"
                # reason = "All of the <span style='color: #880808'>Werewolves</span> have been eradicated."
                reason = {"key": "events.win_villagers", "variables": {}}

            # Wolves win if they outnumber villagers (or equal)
            elif len(wolves) >= non_wolves_count:
                self.winner = "Werewolves"
                # reason = "The <span style='color: #880808'>Werewolves</span> have taken over the village."
                reason = {"key": "events.win_werewolves", "variables": {}}

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
