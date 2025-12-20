"""
roles.py
Version: 4.4.9
Defines the behavior of all roles using a generic base class and specific subclasses.
"""
import random
from config import *

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
        self.name_key = "Unknown"
        self.description_key = "desc_generic"
        self.team = "neutral"  # villager, werewolf, solo

        # Logic Settings
        self.priority = 0  # 0 = First (e.g., Bodyguard), 100 = Last (e.g.,Werewolf)
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

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target."""
        return [p for p in game_context["players"] if p.is_alive]

    @property
    def night_prompt(self) -> str:
        """The text displayed to the user during the night."""
        return "Dim didi dum :)"

    def night_action(self, player_obj, target_player_obj, game_context):
        """
        Logic for when the player performs their night action.
        Returns a dict of action data to be stored in the game state.
        """
        return {}

    def get_night_ui_schema(self, player_obj, game_context):
        """
        Returns a dict defining the UI interaction.
        Types: 'info', 'single_target', 'multi_target', 'menu'
        """
        # Default behavior: Just show a message (Villager style)
        return {
            "type": "info",
            "pre": f"<h4>{self.night_prompt}</h4>",
            "post": "<p>You are sleeping...</p>",
        }

    def passive_effect(self, player_obj):
        """Logic for constant effects (e.g., Tough Werewolf extra life)."""
        return {}

    def check_win_condition(self, player_obj, game_context) -> bool:
        """
        Custom win condition check.
        Returns True if this specific player has satisfied their win condition.
        """
        return False

    def on_death(self, player_obj, game_context):
        """
        Triggered when this player dies.
        Can be used for Hunter (shoot someone) or Martyr (buff someone).
        """
        print(f"DEBUG: {player_obj.name} ({self.name_key}) has died.")
        # Future logic:
        # if self.name_key == "role_hunter":
        #     game_context['engine'].trigger_hunter_event(player_obj)
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
        self.name_key = ROLE_VILLAGER
        self.description_key = "desc_villager"
        self.team = "villager"
        self.is_night_active = False

    @property
    def night_prompt(self):
        prompts = [
            "Who has the cutest smile?",
            "Who would die first in a zombie apocalypse?",
            "Who is the most lightweight drinker?",
            "Who looks the most suspicious right now?",
            "Who is a finger licker?",
        ]
        return random.choice(prompts)

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "type": "single_target",
            "pre": f'<p>You are dreaming of yummy pupusas while the night creatures are stirring ... </p><h4>{self.night_prompt}</h4><select id="action-select"></select> <button id="action-btn">Select</button>',
            "post": '<p>You made an interesting choice, picking <span style="color: #ff0000">${playerPicked}</span>. Waiting...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Werewolf(Role):
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_WEREWOLF
        self.description_key = "desc_werewolf"
        self.team = "werewolf"
        self.priority = 50  # Wolves attack after defensive roles
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # The engine will aggregate Werewolf votes, but the action is simply voting a target
        return {"action": "kill_vote", "target": target_player_obj.id}

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "type": "single_target",
            "pre": '<h4>Werewolf, who will you eat?</h4><select id="action-select"></select> <button id="action-btn">Kill</button>',
            "post": '<p>You are hungry for <span style="color: #ff0000">${playerPicked}</span>. Waiting...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Seer(Role):
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_SEER
        self.description_key = "desc_seer"
        self.team = "villager"
        self.priority = 10  # Seer acts early
        self.is_night_active = True

    def investigate(self, target_player):
        """Central logic for determining what the Seer sees."""
        if (
            target_player.role.team == "werewolf"
            or target_player.role.team == "monster"
        ):
            return ROLE_WEREWOLF
        return ROLE_VILLAGER

    def night_action(self, player_obj, target_player_obj, game_context):
        # Return the information immediately to the engine to send back to user
        result = self.investigate(target_player_obj)
        return {
            "action": "investigate",
            "target": target_player_obj.id,
            "result": result,
        }

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "type": "single_target",
            "pre": '<h4>Seer, whose role will you see?</h4><select id="action-select"></select> <button id="action-btn">Investigate</button>',
            "post": '<p>You saw <span style="color: #ff0000">${playerPicked}</span>\'s role. Waiting ...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Bodyguard(Role):
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_BODYGUARD
        self.description_key = "desc_bodyguard"
        self.team = "villager"
        self.priority = 0  # Priority 0: PROTECT BEFORE ATTACK
        self.is_night_active = True
        self.last_protected_id = None

    def night_action(self, player_obj, target_player_obj, game_context):
        if target_player_obj.id == self.last_protected_id:
            return {}

        target_player_obj.status_effects.append("protected")
        self.last_protected_id = target_player_obj.id
        print(f"Bodyguard protecting {target_player_obj.name}")
        return {}

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs excluding last portected"""
        all_living = [p for p in game_context["players"] if p.is_alive]
        if self.last_protected_id:
            return [p for p in all_living if p.id != self.last_protected_id]
        return all_living

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "type": "single_target",
            "pre": '<h4>Bodyguard, who will you protect?</h4><select id="action-select"></select> <button id="action-btn">Protect</button>',
            "post": '<p>Sending protection orders for <span style="color: #ff0000">${playerPicked}</span>. Waiting ...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


# roles.py (Additions)


@register_role
class Cupid(Role):
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_CUPID
        self.team = "villager"
        self.priority = 1  # Very early, before wolves
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        self.is_night_active = False

        # Validation: Cannot pick self
        if target_player_obj.id == player_obj.id:
            return {}

        # 1. Get Potion Type from Metadata (provided by Engine)
        metadata = game_context.get("current_action_metadata", {})
        target_player_id2 = metadata.get("target_id2")

        if not target_player_id2:
            print("Cupid Error: Second target not found.")
            return {}

        target_player_obj2 = next(
            (p for p in game_context["players"] if p.id == target_player_id2), None
        )

        if not target_player_obj2:
            print("Cupid Error: Second target not found.")
            return {}

        target_player_obj.status_effects.append("lover")
        target_player_obj2.status_effects.append("lover")
        target_player_obj.linked_partner_id = target_player_obj2.id
        target_player_obj2.linked_partner_id = target_player_obj.id

        print(f"Cupid {target_player_obj.name} linked with {target_player_obj2.name}")

        return {}

    def get_night_ui_schema(self, player_obj, game_context):
        if not self.is_night_active:
            return {"type": "info", "pre": "<p>You have already chosen lovers.</p>"}

        return {
            "type": "two_target",
            "pre": '<h4>Select the lovers:</h4><p class="role-desc">The selected players are fatally in love. If one dies, the other dies of heartache.</p><select id="action-select"></select><select id="action-select-2"></select><button id="action-btn">Shoot Arrow</button>',
            "post": '<p>Love is in the air... <span style="color: #ff0000">${playerPicked} & ${playerPicked2}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": False,
        }


@register_role
class Witch(Role):
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_WITCH
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
        metadata = game_context.get("current_action_metadata", {})
        potion = metadata.get("potion")  # 'heal' or 'kill'

        # 2. Process Heal
        if potion == "heal" and self.has_heal_potion:
            self.has_heal_potion = False
            target_player_obj.status_effects.append("healed")
            return {
                "action": "witch_magic",
                "target": target_player_obj.id if target_player_obj else None,
                "effect": "healed",
            }

        # 3. Process Kill
        elif potion == "poison" and self.has_kill_potion:
            self.has_kill_potion = False
            target_player_obj.status_effects.append("poisoned")
            return {
                "action": "witch_magic",
                "target": target_player_obj.id,
                "effect": "poisoned",
            }

        return {}

    def get_night_ui_schema(self, player_obj, game_context):
        if not self.has_heal_potion and not self.has_kill_potion:
            return {"type": "info", "pre": "<p>You have used all your potions!</p>"}

        # Format potions as {id, name} so populateSelect works
        potions = []
        if self.has_heal_potion:
            potions.append({"id": "heal", "name": "Heal Potion"})
        if self.has_kill_potion:
            potions.append({"id": "poison", "name": "Poison Potion"})
        potions.append({"id": "none", "name": "Do Nothing"})

        return {
            "type": "two_target",
            "pre": '<h4>Witch, who will consume a potion?</h4><select id="action-select"></select> <select id="action-select-2"></select><button id="action-btn">Feed Potion</button>',
            "post": '<p><span style="color: #ff0000">${playerPicked}</span> consumed ${playerPicked2}</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "potions": potions,
            "can_skip": True,
        }


@register_role
class Monster(Role):
    # seen as Werewolf, but cannot be killed by Werewolf
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_MONSTER
        self.team = "monster"

    def on_assign(self, player_obj):
        # This is checked by the Engine when calculating deaths
        player_obj.status_effects.append("immune_to_wolf")

    @property
    def night_prompt(self):
        return "Who is a finger licker?"


@register_role
class AlphaWerewolf(Werewolf):  # Inherits from Werewolf!
    def __init__(self):
        super().__init__()
        self.name_key = ROLE_ALPHA_WEREWOLF

    def check_win_condition(self, player_obj, game_context):
        # Wins if is the ONLY one left alive
        living_players = [p for p in game_context["players"] if p.is_alive]
        if len(living_players) == 1 and player_obj.is_alive:
            return True
        return False
