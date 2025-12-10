"""
game_engine.py
# Version: 4.2.0
Manages the game flow, player states, complex role interactions, and phase transitions.
"""
import random
import time
from collections import Counter
from app import get_living_players
from roles import AVAILABLE_ROLES

class Player:
    def __init__(self, session_id, name):
        self.id = session_id
        self.name = name
        self.role = None  # Will be an instance of a Role class
        self.is_alive = True
        self.status_effects = [] # e.g., ['protected', 'poisoned', 'lover']
        self.linked_partner_id = None # For Cupid's lovers

    def reset_night_status(self):
        """Clear temporary night flags like 'protected'. Persist 'lover' status."""
        PERSISTENT_EFFECTS = ['lover', 'poisoned', 'immune_to_wolf']
        self.status_effects = [s for s in self.status_effects if s in PERSISTENT_EFFECTS]

    def to_dict(self):
        """Serialize for frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "is_alive": self.is_alive,
            "role": self.role.name_key if self.role else None,
            "team": self.role.team if self.role else None
        }

class Game:
    def __init__(self, game_id, mode='standard'):
        self.game_id = game_id
        self.mode = mode
        self.isPassAndPlay = (mode == 'pass_and_play')

        self.phase = "LOBBY" # LOBBY, DAY, VOTE, NIGHT, RESOLUTION, GAME_OVER
        self.phase_start_time = None

        self.players = {} # Dict[session_id, Player]

        # Night Phase Data
        self.pending_actions = {} # Dict[player_id, target_id]
        self.turn_history = set() # who acted this phase
        self.night_log = [] # Logs for the frontend (e.g., "Seer saw a Wolf")

        # Day Phase Data
        self.accusations = {} # accuser_id: target_id
        self.accusations_restarts = 0
        self.end_day_votes = set() # set of voter_id

        self.lynch_target_id = None
        self.lynch_votes = {} # voter_id: yes/no

        # Admin/Meta Data
        self.admin_only_chat = False
        self.timers_disabled = False
        self.timer_duration = {
                "night": 90,
                "accusation": 90,
                "lynch_vote": 60
                }
        self.current_timer_id = 0 # increment id to invalidate old async timers

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

    def assign_roles(self, selected_role_names):
        """
        selected_role_names: list of strings matching Role Class names from Lobby.
        e.g. ['Werewolf', 'Seer', 'Villager', 'Villager']
        """
        player_ids = list(self.players.keys())
        random.shuffle(player_ids)

        # fill special roles, then fill remainder with Villager if needed
        while len(selected_role_names) < len(player_ids):
            selected_role_names.append("Villager")

        # assign roles
        for pid, role_name in zip(player_ids, selected_role_names):
            # Instantiate the Role class from the Registry
            role_class = AVAILABLE_ROLES.get(role_name, AVAILABLE_ROLES['Villager'])
            self.players[pid].role = role_class()
            self.players[pid].role.on_assign(self.players[pid])
        print(f"Roles assigned for Game {self.game_id} (Mode: {self.mode})")

    def get_living_players(self, role_team=None):
        living = [p for p in self.players.values() if p.is_alive]
        if role_team:
            return [p for p in living if p.role.team == role_team]
        return living

    def set_phase(self, new_phase):
        self.phase = new_phase
        self.phase_start_time = time.time()
        self.current_timer_id += 1

        print(f"Phase changed to: {self.phase}")
        # Trigger cleanup or specific phase logic here
        if new_phase == "NIGHT":
            self.pending_actions = {}
            self.turn_history = set() # Reset tracker
            self.night_log = []
            self.accusations_restarts = 0
            for p in self.players.values():
                p.reset_night_status()
                # trigger night hoooks
                if p.role:
                    p.role.on_night_start(p, {'players': list(self.players.values())})
        elif new_phase == "ACCUSATION_PHASE":
            self.accusations = {}
            self.end_day_votes = set()
            self.lynch_target_id = None
            self.lynch_votes ={}


    def receive_night_action(self, player_id, target_id):
        """
        Store the player's intent. Process it later.
        Note: target_id can be a string ID or a Dict for complex actions (Witch).
        """
        if self.phase != "NIGHT" or player_id not in self.players:
            return "IGNORED"

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


    def resolve_night_phase(self):
        print("--- RESOLVING NIGHT ---")

        # 1. Get all alive players with active roles
        active_players = [p for p in self.players.values()
                          if p.is_alive and p.role.is_night_active]

        # 2. Sort by Priority (Low number = First)
        # Bodyguard (0) goes before Werewolf (50)
        active_players.sort(key=lambda p: p.role.priority)

        wolf_votes = []
        protected_ids = set()
        kill_list = set()

        # 3. Iterate and Execute
        # We pass a 'context' dict so roles can see the state of the game
        game_context = {
                'players': list(self.players.values()),
                'current_action_metadata': {}
        }

        for player in active_players:
            target_data = self.pending_actions.get(player.id)
            if not target_data:
                continue

            # Need to resolve the target player object from ID
            # (If target_data is a dict, extract ID, otherwise assume string ID)
            # todo: might not need, just use status_effects
            if isinstance(target_data, dict):
                # Pass metadata to Role so Witch knows what to do
                game_context['current_action_metadata'] = target_data
                target_id = target_data.get('target_id')
            else:
                game_context['current_action_metadata'] = {}
                target_id = target_data
            target_player = self.players.get(target_id)

            if not target_player:
                continue

            # Execute the Role's specific logic (polymorphism!)
            result = player.role.night_action(player, target_player, game_context)

            # 4. Handle Results
            if result: # might not need this if
                action_type = result.get('action')

                if action_type == 'protect':
                    print(f"Action: {player.name} protected {target_player.name}")
                    protected_ids.add(target_player.id)
                    target_player.status_effects.append('protected')

                elif action_type == 'link_lovers':
                    # Cupid links the sender and the target (simplified)
                    # Or Cupid sends two targets. Handling simplified 1-target version:
                    print(f"Action: Cupid links {player.name} and {target_player.name}")
                    player.linked_partner_id = target_player.id
                    target_player.linked_partner_id = player.id
                    player.status_effects.append('lover')
                    target_player.status_effects.append('lover')

                elif action_type == 'kill_vote':
                    # must be Unanimous
                    wolf_votes.append(target_player.id)

                elif action_type == 'witch_magic':
                    # Check Status Effects to know what happened
                    if 'used_heal' in player.status_effects:
                        print(f"Action: Witch heals {target_player.name if target_player else 'Unknown'}")
                        if target_player:
                            protected_ids.add(target_player.id)
                        player.status_effects.remove('used_heal')

                    elif 'used_poison' in player.status_effects:
                        print(f"Action: Witch poisons {target_player.name}")
                        if target_player:
                            kill_list.add(target_player.id)
                        player.status_effects.remove('used_poison')

                elif action_type == 'investigate':
                    print(f"Debug: Seer {player.name} investigated {target_player.name}: {result.get('result')}")
                    self.night_log.append({
                        "player_id": player.id,
                        "message": f"Seer Result: {result.get('result')}"
                    })


        # 4. Resolve Wolf Votes
        # Unanimous vote kills, else no kill
        living_wolves = self.get_living_players("wolf")
        if (
                wolf_votes
                and len(wolf_votes) == len(living_wolves)
                and len(set(wolf_votes)) == 1
        ):
            target_id = wolf_votes[0]
            target_name = self.players[target_id].name
            print(f"Wolves selected: {target_name}")

            # Check Protection
            # todo: possible unnest from previous if
            if target_id in protected_ids:
                print(f"Attack on {target_name} blocked by protection!")
            else:
                # Check Passive Immunity (Monster)
                victim = self.players[target_id]


                if 'immune_to_wolf' in victim.status_effects:
                    print(f"Attack on {target_name} failed (Immune)!")
                else:
                    kill_list.add(target_id)

        # 5. Process Deaths & Lovers Pact
        final_deaths = set()

        def process_death(pid):
            final_deaths.add(pid)
            victim = self.players[pid]
            if not victim: return

            # Check Lovers (Daisy chain death)
            if victim.linked_partner_id:
                partner = self.players.get(victim.linked_partner_id)
                if partner and partner.is_alive and partner.id not in final_deaths:
                    print(f"Lovers Pact: {partner.name} dies of grief!")
                    process_death(partner.id)

        for pid in kill_list:
            process_death(pid)

        # Apply State Changes
        for pid in final_deaths:
            self.players[pid].is_alive = False
            print(f"DIED: {self.players[pid].name}")

        return list(final_deaths)

# --- DAY LOGIC (Accusations & Voting) ---

    def process_accusation(self, accuser_id, target_id):
        """Returns True if this accusation triggered a majority/all-voted condition (optional optimization)."""
        if self.phase != "ACCUSATION_PHASE": return False
        if accuser_id in self.accusations: return False # Already accused

        self.accusations[accuser_id] = target_id
        return len(self.accusations) >= len(self.get_living_players())

    def vote_to_sleep(self, player_id):
        """Returns True if majority wants to sleep."""
        if self.phase != "ACCUSATION_PHASE": return False
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
            self.set_phase("NIGHT")
            return {"result": "night", "message": "No accusations. Sleeping..."}

        # 2. Count
        counts = Counter(valid_votes)
        most_common = counts.most_common(2)

        # 3. if tie, restart accusations once
        if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
            if self.accusation_restarts == 0:
                self.accusation_restarts += 1
                self.accusations = {} # Reset
                # Return 'restart' but DO NOT change phase yet, app.py handles notification
                return {"result": "restart", "message": "Tie vote! Re-discuss."}
            else:
                self.set_phase("NIGHT")
                return {"result": "night", "message": "Deadlock tie. No one lynched."}

        # 4. Lynch Trial
        self.lynch_target_id = most_common[0][0]
        self.set_phase("LYNCH_VOTE_PHASE")
        return {
            "result": "trial",
            "target_id": self.lynch_target_id,
            "target_name": self.players[self.lynch_target_id].name
        }

    def cast_lynch_vote(self, voter_id, vote):
        """Returns True if all players have voted."""
        if self.phase != "LYNCH_VOTE_PHASE": return False
        if vote not in ["yes", "no"]: return False

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
            "game_over": False
        }

        # Populate summary names
        for pid, v in self.lynch_votes.items():
            result_data["summary"][v].append(self.players[pid].name)

        # Majority YES required (> 50%)
        if yes > (total / 2):
            self.players[self.lynch_target_id].is_alive = False
            result_data["killed_id"] = self.lynch_target_id

            if self.check_game_over():
                result_data["game_over"] = True
                return result_data

        # Reset to Night (unless game over)
        self.set_phase("NIGHT")
        return result_data

    def check_game_over(self):
        """
        Checks all win conditions.
        Priority: 1. Solo Roles (Alpha Wolf, Fool) 2. Teams
        """
        active_players = get_living_players()
        game_context = {'players': list(self.players.values())}

        # 1. Check Solo Win Conditions
        for p in active_players:
            if p.role and p.role.check_win_condition(p, game_context):
                self.winner = p.name
                self.phase = "GAME_OVER"
                return True

        # 2. Check Team Win Conditions
        wolves = get_living_players("wolf")
        non_wolves_count = len(active_players) - len(wolves)

        # Villagers win if no wolves left
        if len(wolves) == 0:
            self.winner = "Villagers"
            self.phase = "GAME_OVER"
            return True

        # Wolves win if they outnumber villagers (or equal)
        if len(wolves) >= non_wolves_count:
            self.winner = "Werewolves"
            self.phase = "GAME_OVER"
            return True

        return False

    def get_game_state(self):
        """Returns the complete state for the frontend."""
        return {
            "game_id": self.game_id,
            "phase": self.phase,
            "players": [p.to_dict() for p in self.players.values()],
            "winner": self.winner
        }
