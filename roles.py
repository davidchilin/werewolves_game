"""
roles.py
Version: 2.0.0
Defines the behavior of all roles using a generic base class and specific subclasses.
"""
import random

# 1. Global Registry to keep track of all available roles
AVAILABLE_ROLES = {}


def register_role(cls):
    """Decorator to automatically register a role class."""
    AVAILABLE_ROLES[cls.__name__] = cls
    return cls


# 2. The Base Generic Class
class Role:
    def __init__(self):
        # Basic Metadata
        self.name_key = "role_generic"
        self.description_key = "desc_generic"
        self.team = "neutral"  # villager, wolf, solo

        # Logic Settings
        self.priority = 0  # 0 = First (e.g., Bodyguard), 100 = Last (e.g., Wolf)
        self.is_night_active = False

    def on_assign(self, player_obj):
        """
        Called once when the role is assigned to the player.
        Use this to apply permanent status effects.
        """
        pass

    def get_team(self):
        return self.team

    def on_night_start(self, player_obj, game_context):
        """Called at the very start of the night phase."""
        pass

    def get_valid_targets(self, player_obj, game_context):
        """Returns a list of valid player IDs this role can target."""
        return [p for p in game_context["players"] if p.is_alive]

    @property
    def night_prompt(self) -> str:
        """The text displayed to the user during the night."""
        return "Select a target:"


    def night_action(self, player_obj, target_player_obj, game_context):
        """
        Logic for when the player performs their night action.
        Returns a dict of action data to be stored in the game state.
        """
        return {}

    def passive_effect(self, player_obj):
        """Logic for constant effects (e.g., Tough Wolf extra life)."""
        return {}

    def check_win_condition(self, player_obj, game_context) -> bool:
        """
        Custom win condition check.
        Returns True if this specific player has satisfied their win condition.
        """
        return False

    def on_death(self, player_obj, game_context):
        """Triggered when this player dies (e.g., Hunter)."""
        pass

    def to_dict(self):
        """Serializes role info for the frontend."""
        # todo: possible duplicate from game_engine.py
        return {
            "name_key": self.name_key,
            "description_key": self.description_key,
            "team": self.team,
            "is_night_active": self.is_night_active,
        }


# --- Specific Role Implementations ---


@register_role
class Villager(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_villager"
        self.description_key = "desc_villager"
        self.team = "villager"
        self.is_night_active = False

    @property
    def night_prompt(self):
        prompts = [
            "Who has the cutest smile?",
            "Who would die first in a zombie apocalypse?",
            "Who is the most lightweight drinker?",
            "Who looks the most suspicious right now?"
            "Who is a finger licker?"
        ]
        return random.choice(prompts)

    # todo: possibly not needed, as same as parent version.
    def night_action(self, player_obj, target_player_obj, game_context):
        # Dummy action: Do nothing, return empty
        return {}

@register_role
class Werewolf(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_werewolf"
        self.description_key = "desc_werewolf"
        self.team = "wolf"
        self.priority = 50  # Wolves attack after defensive roles
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # The engine will aggregate wolf votes, but the action is simply voting a target
        return {"action": "kill_vote", "target": target_player_obj.id}


@register_role
class Seer(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_seer"
        self.description_key = "desc_seer"
        self.team = "villager"
        self.priority = 10  # Seer acts early
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # Return the information immediately to the engine to send back to user
        result = "wolf" if (target_player_obj.role.team == "wolf" or
        target_player_obj.role.team == "monster") else "villager"
        return {
            "action": "investigate",
            "target": target_player_obj.id,
            "result": result,
        }


@register_role
class Bodyguard(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_bodyguard"
        self.description_key = "desc_bodyguard"
        self.team = "villager"
        self.priority = 0  # Priority 0: PROTECT BEFORE ATTACK
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        return {"action": "protect", "target": target_player_obj.id}


# roles.py (Additions)


@register_role
class Cupid(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_cupid"
        self.team = "villager"
        self.priority = 1  # Very early, before wolves
        self.is_night_active = True
        self.first_night_only = True  # Logic flag

    def night_action(self, player_obj, target_player_obj, game_context):
        # Cupid only acts on the first night (engine must handle 'first_night' check)
        # Note: Frontend must allow Cupid to select TWO targets.
        # For simplicity in this phase, we assume target_player_obj is a list or we handle single link.
        if self.first_night_only:
            self.first_night_only = False
            return {"action": "link_lovers", "target": target_player_obj.id}
        else:
            return {}


@register_role
class Witch(Role):
    def __init__(self):
        super().__init__()
        self.name_key = "role_witch"
        self.team = "villager"
        self.priority = 15  # After Seer, Before Wolves to set heal
        self.is_night_active = True

        # Specific State
        self.has_heal_potion = True
        self.has_kill_potion = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # The frontend needs to send WHICH potion was used in the metadata
        # tailored engine logic required to parse "action_type"
        if target_player_obj is None:
            return {}

        # 1. Get Potion Type from Metadata (provided by Engine)
        metadata = game_context.get('current_action_metadata', {})
        potion = metadata.get('potion') # 'heal' or 'kill'

        # 2. Process Heal
        if potion == 'heal':
            if self.has_heal_potion:
                self.has_heal_potion = False
                player_obj.status_effects.append('used_heal')
                return {"action": "witch_magic", "target": target_player_obj.id if target_player_obj else None}
            else:
                # Cheating/Error check
                return {}

        # 3. Process Kill
        elif potion == 'kill':
            if self.has_kill_potion and target_player_obj:
                self.has_kill_potion = False
                player_obj.status_effects.append('used_poison')
                return {"action": "witch_magic", "target": target_player_obj.id}
            else:
                return {}

        return {}

@register_role
class Monster(Role):
# seen as wolf, but cannot be killed by wolfs
    def __init__(self):
        super().__init__()
        self.name_key = "role_monster"
        self.team = "monster"

    def on_assign(self, player_obj):
        # This is checked by the Engine when calculating deaths
        player_obj.status_effects.append('immune_to_wolf')

    @property
    def night_prompt(self):
        return "Who is a finger licker?"

    def night_action(self, player_obj, target_player_obj, game_context):
        return {} # Dummy action

@register_role
class AlphaWolf(Werewolf):  # Inherits from Werewolf!
    def __init__(self):
        super().__init__()
        self.name_key = "role_alpha_wolf"

    def check_win_condition(self, player_obj, game_context):
        # Wins if is the ONLY one left alive
        living_players = [p for p in game_context["players"] if p.is_alive]
        if len(living_players) == 1 and living_players[0].id == player_obj.id:
            return True
        return False
