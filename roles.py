"""
roles.py
Version: 4.9.0
Defines the behavior of all roles using a generic base class and specific subclasses.
"""
import random
from config import VILLAGER_PROMPTS

# --- Roles ---
# Simplified keys, add manually to lobby.html
ROLE_ALPHA_WEREWOLF = "Alpha_Werewolf"
ROLE_BACKLASH_WEREWOLF = "Backlash_Werewolf"
ROLE_BODYGUARD = "Bodyguard"
ROLE_CUPID = "Cupid"
ROLE_DEMENTED_VILLAGER = "Demented_Villager"
ROLE_FOOL = "Fool"
ROLE_HONEYPOT = "Honeypot"
ROLE_HUNTER = "Hunter"
ROLE_LAWYER = "Lawyer"
ROLE_MARTYR = "Martyr"
ROLE_MAYOR = "Mayor"
ROLE_MONSTER = "Monster"
ROLE_PROSTITUTE = "Prostitute"
ROLE_RANDOM_SEER = "Random_Seer"
ROLE_REVEALER = "Revealer"
ROLE_SEER = "Seer"
ROLE_SERIAL_KILLER = "Serial_Killer"
ROLE_SORCERER = "Sorcerer"
ROLE_TOUGH_VILLAGER = "Tough_Villager"
ROLE_TOUGH_WEREWOLF = "Tough_Werewolf"
ROLE_VILLAGER = "Villager"
ROLE_WEREWOLF = "Werewolf"
ROLE_WILD_CHILD = "Wild_Child"
ROLE_WITCH = "Witch"

GOOD_MAYORS = [
    ROLE_VILLAGER,
    ROLE_DEMENTED_VILLAGER,
    ROLE_FOOL,
    ROLE_MONSTER,
    ROLE_TOUGH_VILLAGER,
    ROLE_MAYOR,
]
SPECIAL_WEREWOLVES = [ROLE_ALPHA_WEREWOLF, ROLE_TOUGH_WEREWOLF, ROLE_BACKLASH_WEREWOLF]
SOLO_LAST_MAN = [
    ROLE_ALPHA_WEREWOLF,
    ROLE_DEMENTED_VILLAGER,
    ROLE_MONSTER,
    ROLE_SERIAL_KILLER,
]

# 1. Global Registry to keep track of all available roles
AVAILABLE_ROLES = {}


def register_role(cls):
    """Decorator to automatically register a role class."""
    AVAILABLE_ROLES[cls.__name__] = cls
    return cls


# 2. The Base Generic Class
class Role:
    name_key = "Unknown"
    description_key = "desc_generic"
    team = "Neutral"  # Villager, Werewolf, Neutral
    priority = 8  # 0 = First (e.g., Bodyguard), 50 = Last (e.g.,Werewolf)

    ui_short = "No description."
    ui_long = "No description."
    ui_rating = 0.0
    ui_color = "#888888"

    def __init__(self):
        # Basic Metadata
        self.is_night_active = False
        self.player_id = None

    VILLAGER_PROMPTS = VILLAGER_PROMPTS

    def on_assign(self, player_obj):
        """
        Called once when the role is assigned to the player.
        Use this to apply permanent status effects.
        """
        self.player_id = player_obj.id
        pass

    def on_night_start(self, player_obj, game_context):
        """Called at the very start of the night phase."""
        pass

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target."""
        return [p for p in game_context["players"] if p.is_alive]

    def night_action(self, player_obj, target_player_obj, game_context):
        """
        Logic for when the player performs their night action.
        Returns a dict of action data to be stored in the game state.
        """
        return {}

    def get_night_ui_schema(self, player_obj, game_context):
        idx = game_context.get("villager_promt_index", 0)
        safe_idx = idx % len(self.VILLAGER_PROMPTS) if self.VILLAGER_PROMPTS else 0
        current_prompt = self.VILLAGER_PROMPTS[safe_idx]

        return {
            "pre": f'<h4>{current_prompt}</h4><select id="action-select"></select> <button id="action-btn">Select</button>',
            "post": '<p>You made an interesting choice, picking <span style="color: springgreen">${playerPicked}</span>. <p>You are now dreaming of yummy pupusas while the night creatures are stirring ...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }

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
        # Future logic:
        # if self.name_key == "hunter":
        #     game_context['engine'].trigger_hunter_event(player_obj)
        return {}

    def to_dict(self):
        """Serializes role info for the frontend."""
        return {
            "name_key": self.name_key,
            "description_key": self.description_key,
            "team": self.team,
            "is_night_active": self.is_night_active,
            "short": self.ui_short,
            "long": self.ui_long,
            "rating": self.ui_rating,
            "color": self.ui_color,
        }


# --- Specific Role Implementations ---


@register_role
class Villager(Role):
    name_key = ROLE_VILLAGER
    description_key = "desc_villager"
    team = "Villagers"
    ui_short = "Find the Werewolves and vote them out."
    ui_long = "You have no special night abilities. Your strength lies in your vote and your deduction skills. Listen to the others, find the inconsistencies, and lynch the beasts."
    ui_rating = 0.4
    ui_color = "#4D00B3"

    def __init__(self):
        super().__init__()
        self.is_night_active = False

    def night_action(self, player_obj, target_player_obj, game_context):
        """
        Logic for when the player performs their night action.
        Returns a dict of action data to be stored in the game state.
        """
        if not target_player_obj:
            return {}
        return {"action": "villager_vote", "target": target_player_obj.id}


@register_role
class Werewolf(Role):
    name_key = ROLE_WEREWOLF
    description_key = "desc_werewolf"
    team = "Werewolves"
    priority = 45  # Wolves attack after defensive roles
    ui_short = "Kill Villagers at night. Don't get caught."
    ui_long = "You are part of the pack. Every night, you wake up with the other Werewolves and must agree unanimously on a victim to kill. During the day, you must colloborate with the other Werwolves while still acting like an innocent Villager to avoid being caught."
    ui_rating = -0.6
    ui_color = "#CC0033"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # The engine will aggregate Werewolf votes, but the action is simply voting a target
        return {"action": "kill_vote", "target": target_player_obj.id}

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Werewolf, who will you eat?</h4><select id="action-select"></select> <button id="action-btn">Kill</button>',
            "post": '<p>You are hungry for <span style="color: red" strong >${playerPicked}</span>. Waiting...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Seer(Role):
    name_key = ROLE_SEER
    description_key = "desc_seer"
    team = "Villagers"
    priority = 3  # Seer acts early
    ui_short = "See a player's sole at night! (Werewolf?)"
    ui_long = "You are the village's most powerful investigator. Every night, you select one player to reveal that player's team - werewolves or villagers. Note the Monster is seen as a Werewolf."
    ui_rating = 1.0
    ui_color = "#0000FF"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def investigate(self, target_player):
        """Central logic for determining what the Seer sees."""
        if (
            target_player.role.team == "Werewolves"
            or target_player.role.team == "Monster"
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
            "pre": '<h4>Seer, whose role will you see?</h4><select id="action-select"></select> <button id="action-btn">Investigate</button>',
            "post": '<p>You saw <span style="color: yellow">${playerPicked}</span>\'s role. Waiting ...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Alpha_Werewolf(Werewolf):
    name_key = ROLE_ALPHA_WEREWOLF
    ui_short = "Solo wins if last one standing."
    ui_long = "You are the leader of the Werewolves. You vote with the pack to kill at night. However, your goal is to sit alone on your mountain. Solo win if only living werewolf with maximum of one living non-Monster."
    ui_rating = -0.5
    ui_color = "#C00040"

    def __init__(self):
        super().__init__()

    def check_win_condition(self, player_obj, game_context):
        # Wins if is the ONLY one left alive with max one non-monster alive
        if not player_obj.is_alive:
            return False

        living_players = [p for p in game_context["players"] if p.is_alive]
        if len(living_players) == 1:
            return True

        werewolves = [p for p in living_players if p.role.team == "Werewolves"]
        if len(werewolves) > 1:
            return False

        non_monsters = [p for p in living_players if p.role.name_key != "Monster"]

        return (
            len(living_players) == 2 and len(non_monsters) == 2
        )  # werewolf is a nonmonster as well


@register_role
class Bodyguard(Role):
    name_key = ROLE_BODYGUARD
    description_key = "desc_bodyguard"
    team = "Villagers"
    priority = 17  # Priority PROTECT BEFORE ATTACK
    ui_short = "Chooses a player to protect from Werewolves."
    ui_long = "Every night, you may choose one player to guard. If the Werewolves attack that player, your protection saves them, and nobody dies. You cannot protect the same person two nights in a row."
    ui_rating = 0.5
    ui_color = "#4000C0"

    def __init__(self):
        super().__init__()
        self.is_night_active = True
        self.last_protected_id = None

    def night_action(self, player_obj, target_player_obj, game_context):
        if target_player_obj.id == self.last_protected_id:
            return {}

        self.last_protected_id = target_player_obj.id
        print(f"Bodyguard protecting {target_player_obj.name}")
        return {
            "action": "Protect",
            "effect": "protected",
            "target": target_player_obj.id,
        }

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs excluding last portected"""
        all_living = [p for p in game_context["players"] if p.is_alive]
        if self.last_protected_id:
            return [p for p in all_living if p.id != self.last_protected_id]
        return all_living

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Bodyguard, who will you protect?</h4><select id="action-select"></select> <button id="action-btn">Protect</button>',
            "post": '<p>Sending protection orders for <span style="color: turquoise">${playerPicked}</span>. Waiting ...</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Cupid(Villager):
    name_key = ROLE_CUPID
    priority = 9  # Very early, before wolves
    ui_short = "Link two players in fatal love."
    ui_long = "On your first night, choose two players to be 'Lovers.' These two learn their lover name. Their fates are linked: if one is killed (at night or by lynching), the other dies immediately of a broken heart."
    ui_rating = -0.2
    ui_color = "#990066"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        if self.is_night_active:
            self.is_night_active = False

            # Validation: Cannot pick self
            if target_player_obj.id == player_obj.id:
                return {}

            # 1. Get second lover from Metadata (provided by Engine)
            metadata = game_context.get("current_action_metadata", {})
            target_player_id2 = metadata.get("target_id2")
            if not target_player_id2:
                print("Cupid Error: Second target not found in metadata.")
                return {}

            target_player_obj2 = next(
                (p for p in game_context["players"] if p.id == target_player_id2), None
            )
            if not target_player_obj2:
                print("Cupid Error: Second target not found.")
                return {}

            target_player_obj.linked_partner_id = target_player_obj2.id
            target_player_obj2.linked_partner_id = target_player_obj.id

            print(
                f"Cupid: {target_player_obj.name} linked with {target_player_obj2.name}"
            )

            return {
                "action": "Link Lovers",
                "target": target_player_obj.name,
                "partner": target_player_obj2.name,
            }

        return {"action": "villager_vote", "target": target_player_obj.id}

    def get_night_ui_schema(self, player_obj, game_context):
        if not self.is_night_active:
            return Villager.get_night_ui_schema(self, player_obj, game_context)

        return {
            "pre": '<h4>Select the lovers:</h4><p class="role-desc">The selected players are fatally in love. If one dies, the other dies of heartache.</p><select id="action-select"></select><select id="action-select-2"></select><button id="action-btn">Shoot Arrow</button>',
            "post": '<p>Love is in the air... <span style="color: orchid">${playerPicked} & ${playerPicked2}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": False,
        }


@register_role
class Demented(Villager):
    name_key = ROLE_DEMENTED_VILLAGER
    team = "Neutral"  # Wins alone
    ui_short = "Solo wins if last one standing."
    ui_long = "You have no special powers and appear as a Villager to the Seer. However, ChatGPT convinced you to kill everyone for the WIN. Note you won't be last if left with a Monster, Honeypot, Hunter, Serial Killer, and Wild Child."
    ui_rating = 0.2
    ui_color = "#660099"

    def __init__(self):
        super().__init__()

    # Wins if last one alive
    def check_win_condition(self, player_obj, game_context):
        # win if alive and max one non serial killer villager alive
        if not player_obj.is_alive:
            return False

        living_players = [p for p in game_context["players"] if p.is_alive]
        if len(living_players) == 1:
            return True

        werewolves = [p for p in living_players if p.role.team == "Werewolves"]

        if len(werewolves) > 0:
            return False

        KILL_DEMENTED = [
            ROLE_MONSTER,
            ROLE_HONEYPOT,
            ROLE_HUNTER,
            ROLE_SERIAL_KILLER,
            ROLE_WILD_CHILD,
        ]
        villagers = [p for p in living_players if p.role.name_key not in KILL_DEMENTED]

        return len(living_players) == 2 and len(villagers) == 2


@register_role
class Fool(Villager):
    name_key = ROLE_FOOL
    team = "Neutral"
    ui_short = "Tries to get themselves lynched by the village."
    ui_long = "You are a neutral chaos agent. You are not part of the villagers nor the werewolves. Although your ultimate win is successful if you convince the town to Lynch you."
    ui_rating = -0.2
    ui_color = "#990066"

    # Wins if lynched
    def __init__(self):
        super().__init__()
        # Logic handled in game_engine.resolve_lynch_vote


@register_role
class Honeypot(Villager):
    name_key = ROLE_HONEYPOT
    ui_short = "A trap role. If killed, their killer dies too."
    ui_long = "You are a Villager, but dangerous to touch. If you are killed, whether by Werewolves or a Lynch mob — they will pay with their life."
    ui_rating = 0
    ui_color = "#800080"

    def __init__(self):
        super().__init__()

    def on_death(self, player_obj, game_context):
        reason = game_context.get("reason", "")

        # 1. Lynch Retaliation: Kill a random "Yes" voter
        if reason == "Lynched":
            votes = game_context.get("lynch_votes", {})
            yes_voters = [
                pid
                for pid, vote in votes.items()
                if vote == "yes" and pid != player_obj.id
            ]

            # Filter for ALIVE voters only
            alive_yes_voters = [
                pid
                for pid in yes_voters
                if any(p.id == pid and p.is_alive for p in game_context["players"])
            ]

            if alive_yes_voters:
                target_id = random.choice(alive_yes_voters)
                target_player_obj = next(
                    (p for p in game_context["players"] if p.id == target_id), None
                )
                msg = "Honeypot Retaliation"
                if target_player_obj:
                    msg = f"Honeypot retaliation: <strong>{target_player_obj.name}</strong> selected from lynch mob. They were a {target_player_obj.role.name_key}!"
                    print(msg)
                return {"kill": target_id, "reason": msg}

        # 2. Werewolf Retaliation: Kill a random Werewolf
        elif reason == "Werewolf meat":
            wolves = [
                p
                for p in game_context["players"]
                if p.is_alive and p.role.team == "Werewolves"
            ]
            if wolves:
                target = random.choice(wolves)
                msg = (
                    f"Honeypot retaliation: {target.name} selected from werewolf pack."
                )
                print(msg)
                return {"kill": target.id, "reason": msg}

        # 3. Witch Retaliation: Kill the Witch
        elif reason == "Witch Poison":
            witches = [
                p
                for p in game_context["players"]
                if p.is_alive and p.role.name_key == "Witch"
            ]
            if witches:
                target = random.choice(witches)
                msg = f"Honeypot retaliation: {target.name} is taking an acid bath."
                print(msg)
                return {"kill": target.id, "reason": msg}

        # 4. Serial Killer Retaliation: Kill the Serial Killer
        elif reason == "Serial Killer":
            killers = [
                p
                for p in game_context["players"]
                if p.is_alive and p.role.name_key == "Serial_Killer"
            ]
            if killers:
                target = random.choice(killers)
                msg = (
                    f"Honeypot retaliation: {target.name} is sleeping with the fishies."
                )
                print(msg)
                return {"kill": target.id, "reason": msg}

        return {}


@register_role
class Hunter(Role):
    name_key = ROLE_HUNTER
    team = "Villagers"
    priority = 48
    ui_short = "Can strike another player with last dying breath."
    ui_long = "During the night you may select someone to kill upon your death."
    ui_rating = 0.4
    ui_color = "#4D00B3"

    def __init__(self):
        super().__init__()
        self.is_night_active = True
        self.failsafe_id = None

    def night_action(self, player_obj, target_player_obj, game_context):
        # Store the target, do NOT kill yet.
        self.failsafe_id = target_player_obj.id
        return {}

    def on_death(self, player_obj, game_context):
        # If I die, I take my failsafe target with me
        if self.failsafe_id:
            return {"kill": self.failsafe_id}
        return {}

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Hunter: Who will you shoot IF you die?</h4><select id="action-select"></select> <button id="action-btn">Aim</button>',
            "post": '<p>You are aiming at <span style="color:crimson">${playerPicked}</span> (only fires if you die).</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Backlash_Werewolf(Hunter):
    # Same logic as Hunter, just Werewolf team
    name_key = ROLE_BACKLASH_WEREWOLF
    team = "Werewolves"
    priority = 50
    ui_short = "Can strike another player with last dying breath."
    ui_long = "You are a Werewolf with deathly reflexes. You may choose a player at Night to avenge upon your death."
    ui_rating = -1.0
    ui_color = "#FF0000"

    def __init__(self):
        super().__init__()
        self.failsafe_id = None

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            # We provide a UI with TWO dropdowns
            "pre": """
                <h4>Backlash Wolf Actions</h4>
                <p>1. Vote for the Night Kill (Pack Action)<br>
                   2. Select a Grudge Target (Dies if you die)</p>
                <select id="action-select"></select>
                <select id="action-select-2"></select>
                <button id="action-btn">Submit Choices</button>
            """,
            "post": '<p>You voted to kill <span style="color:crimson">${playerPicked}</span> and marked <span style="color:darkred">${playerPicked2}</span> for backlash.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,  # Wolves must vote!
        }

    def night_action(self, player_obj, target_player_obj, game_context):
        # 1. Handle the Primary Selection (The Wolf Kill Vote)
        # We use the parent logic to generate the standard kill vote

        # 2. Handle the Secondary Selection (The Backlash Grudge)
        # We retrieve the second dropdown's value from metadata
        metadata = game_context.get("current_action_metadata", {})
        backlash_id = metadata.get("target_id2")

        if backlash_id:
            self.failsafe_id = backlash_id
            backlash_name = "Unknown"
            found_player = next(
                (p for p in game_context["players"] if p.id == backlash_id), None
            )
            if found_player:
                backlash_name = found_player.name

            print(f"Backlash Wolf {player_obj.name} marked {backlash_name} for death.")

        return {"action": "kill_vote", "target": target_player_obj.id}


@register_role
class Lawyer(Villager):
    name_key = ROLE_LAWYER
    description_key = "desc_lawyer"
    priority = 14  # Acts around the same time as Bodyguard
    ui_short = "Chooses a client to be unlynchable the next day."
    ui_long = "You work to defend the accused. At night, you select a player to be your client. If that player goes to lynch trial, the lynching will fail, and they will survive."
    ui_rating = 0.2
    ui_color = "#660099"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # Apply the protection effect
        return {
            "action": "defend",
            "effect": "no_lynch",
            "target": target_player_obj.id,
            "reason": "Lawyer Defense",
        }

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Lawyer, who will you defend in this monkey court?</h4><select id="action-select"></select> <button id="action-btn">Defend</button>',
            "post": '<p>You are preparing a defense for <span style="color: gold">${playerPicked}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Martyr(Villager):
    name_key = "Martyr"
    ui_short = "Gifts a player to receive a 2nd life upon their death."
    ui_long = "At night you can select a player to absorb your life force upon your death."
    ui_rating = 0.2
    ui_color = "#660099"

    def __init__(self):
        super().__init__()
        self.is_night_active = True
        self.failsafe_id = None

    def on_death(self, player_obj, game_context):
        # Let's do: If I die, I give a "blessing" (armor) to a random living player.
        lucky_person = next(
            (
                p
                for p in game_context["players"]
                if p.is_alive and p.id == self.failsafe_id
            ),
            None,
        )
        if lucky_person:
            lucky_person.status_effects.append("2nd_life")
            print(f"Martyr died and blessed {lucky_person.name}")

        return {}

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Martyr, Who will you bestow a 2nd Life upon your death?</h4><select id="action-select"></select> <button id="action-btn">Protect</button>',
            "post": '<p>You are watching over <span style="color:deeppink">${playerPicked}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": False,
        }

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def night_action(self, player_obj, target_player_obj, game_context):
        self.failsafe_id = target_player_obj.id
        return {}


@register_role
class Mayor(Villager):
    # Mayor tag is transferable to not night active like villager, demented villager, fool, monster, tough_villager
    name_key = ROLE_MAYOR
    description_key = "desc_mayor"
    priority = 12
    ui_short = "Vote can break a tie during accusations."
    ui_long = "You are the leader of the village. Because of your political influence, your vote carries tie-breaking weight during the daily accusation. You can secretly announce your successor. Your successor can only name their successor if their role has no night actions, like a Villager or Monster."
    ui_rating = 0.4
    ui_color = "#4D00B3"

    def __init__(self):
        super().__init__()
        self.is_night_active = True
        self.next_mayor_id = "not_set_yet"

    def night_action(self, player_obj, target_player_obj, game_context):
        if self.is_night_active:
            self.is_night_active = False
            self.next_mayor_id = target_player_obj.id
            return {
                "type": "announcement",
                "message": f"🗳️ Next mayor selected: <strong>{target_player_obj.name}</strong> promoted to <strong>Mayor-Elect!</strong>",
            }

        return {"action": "villager_vote", "target": target_player_obj.id}

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def get_night_ui_schema(self, player_obj, game_context):
        if self.next_mayor_id != "not_set_yet":
            return Villager.get_night_ui_schema(self, player_obj, game_context)

        return {
            "pre": '<h4>Mayor, who will be the next mayor?</h4><select id="action-select"></select> <button id="action-btn">Elect</button>',
            "post": '<p>Politics is great, right <span style="color: turquoise">${playerPicked}</span> ;)</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }

    def on_night_start(self, player_obj, game_context):
        """if next_mayor is dead, choose new next_mayor"""
        if self.next_mayor_id and self.next_mayor_id != "not_set_yet":
            next_mayor = next(
                (p for p in game_context["players"] if p.id == self.next_mayor_id), None
            )
            if next_mayor and not next_mayor.is_alive:
                self.is_night_active = True

    def on_death(self, player_obj, game_context):
        if not self.next_mayor_id or self.next_mayor_id == "not_set_yet":
            return {}

        new_mayor = next(
            (
                p
                for p in game_context["players"]
                if p.is_alive and p.id == self.next_mayor_id
            ),
            None,
        )

        if new_mayor:
            new_mayor.role.next_mayor_id = "not_set_yet"
            # only GOOD_MAYORS can pass on mayor title
            if new_mayor.role.name_key in GOOD_MAYORS:
                new_mayor.role.is_night_active = True
                new_mayor.role.next_mayor_id = "not_set_yet"
                # bind mayor functions
                new_mayor.role.night_action = Mayor.night_action.__get__(
                    new_mayor.role, type(new_mayor.role)
                )
                new_mayor.role.get_night_ui_schema = Mayor.get_night_ui_schema.__get__(
                    new_mayor.role, type(new_mayor.role)
                )
                new_mayor.role.on_death = Mayor.on_death.__get__(
                    new_mayor.role, type(new_mayor.role)
                )
                new_mayor.role.on_night_start = Mayor.on_night_start.__get__(
                    new_mayor.role, type(new_mayor.role)
                )
                new_mayor.role.get_valid_targets = Mayor.get_valid_targets.__get__(
                    new_mayor.role, type(new_mayor.role)
                )
                # announce to all next mayor name has been elected
            return {
                "type": "announcement",
                "message": f"🎩 The Mayor is dead! Long live Mayor <strong>{new_mayor.name}</strong>!",
            }
        return {}


@register_role
class Monster(Villager):
    # seen as Werewolf, but cannot be killed by Werewolf
    name_key = ROLE_MONSTER
    team = "Monster"
    ui_short = "Solo wins if last one standing. Teamless"
    ui_long = "You are a supernatural beast. You are not on the Villager team or the Werewolf team; you are on your own. You are immune to the Werewolf attacks and are seen as a Werewolf. Solo win if alive with maximum of one living Werewolf."
    ui_rating = 0.3
    ui_color = "#5A00A6"

    def __init__(self):
        super().__init__()

    def on_assign(self, player_obj):
        # This is checked by the Engine when calculating deaths
        player_obj.status_effects.append("immune_to_wolf")

    def check_win_condition(self, player_obj, game_context):
        # Monster win if alive and max one werewolf alive.
        if not player_obj.is_alive:
            return False

        living_players = [p for p in game_context["players"] if p.is_alive]
        if len(living_players) == 1:
            return True

        werewolves = [p for p in living_players if p.role.team == "Werewolves"]

        if len(living_players) == 2 and len(werewolves) == 1:
            return True

        return False


@register_role
class Prostitute(Role):
    name_key = ROLE_PROSTITUTE
    priority = 5
    team = "Villagers"
    ui_short = "Visit a player at night and block their night choices."
    ui_long = "Each night, you can visit another player. The visiting player's night selection is secretly cancelled. If you or the visiting player is killed, you both die. Visit most of the players for a solo win!"
    ui_rating = 0.4
    ui_color = "#4D00B3"

    def __init__(self):
        super().__init__()
        self.slept_with = set()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        player_obj.visiting_id = target_player_obj.id
        target_player_obj.visiting_id = player_obj.id
        self.slept_with.add(target_player_obj.id)
        print(f"Prostitute {player_obj.name} is visiting {target_player_obj.name}")
        return {}

    def check_win_condition(self, player_obj, game_context):
        # Wins if sleeps with (Total - 2) players, dead or alive
        # called in resolve_night_deaths
        all_p = len(game_context["players"])
        if len(self.slept_with) >= (all_p - 2):
            return True
        return False

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Prostitute, Who to visit tonight?</h4><select id="action-select"></select> <button id="action-btn">Visit</button>',
            "post": '<p>Visiting <span style="color:deeppink">${playerPicked}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": False,
        }


@register_role
class Random_Seer(Seer):
    name_key = ROLE_RANDOM_SEER
    ui_short = "Has secret attribute: sane, paranoid, naive, insane"
    ui_long = "25% sane normal, 25% paranoid (see werewolves everywhere), 25% naive (sees only villagers), 25% insane (sees opposite role). Should be played with normal Seer. Seer mental state is a secret attribute."
    ui_rating = -0.1
    ui_color = "#8D0073"

    def __init__(self):
        super().__init__()
        # insane, naive, paranoid, normal
        self.sanity = random.choice(["insane", "naive", "paranoid", "normal"])

    def investigate(self, target_player):
        actual = super().investigate(target_player)  # "Werewolf" or "Villager"

        if self.sanity == "paranoid":
            return ROLE_WEREWOLF
        elif self.sanity == "naive":
            return ROLE_VILLAGER
        elif self.sanity == "insane":
            return ROLE_VILLAGER if actual == ROLE_WEREWOLF else ROLE_WEREWOLF

        return actual  # Normal


@register_role
class Revealer(Role):
    name_key = ROLE_REVEALER
    team = "Villagers"
    priority = 25
    ui_short = "Reveal a player's role? Reveal: Wolf- Wolf dies; Villager- You die."
    ui_long = "You have a high-stakes power. You choose a player to 'Reveal.' If they are a Werewolf, they are exposed and killed immediately. If they are a Villager, you die of embarrassment for accusing an innocent."
    ui_rating = 0.3
    ui_color = "#5A00A6"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        # If wolf -> kill wolf. Else -> kill self.
        if target_player_obj.role.team == "Werewolves":
            return {
                "action": "revealed_werewolf",
                "reason": "revealed_werewolf",
            }
        else:
            return {
                "action": "revealed_wrongly",
                "reason": "revealed_wrongly",
            }

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Revealer: Expose a wolf. If you\'re wrong, you die💀</h4><select id="action-select"></select> <button id="action-btn">Reveal</button>',
            "post": '<p>You revealed <span style="color:orangered">${playerPicked}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Serial_Killer(Role):
    name_key = "Serial_Killer"
    team = "Serial_Killer"
    priority = 15  # Kills before wolves
    ui_short = "Kills one person nightly. Wins if last one standing."
    ui_long = "You are a third party. You do not win with the Villagers or the Werewolves. Every night, you choose a victim to mutilate. Your kills cannot be stopped by the Bodyguard. You can only solo win with maximum of one other living human."
    ui_rating = -0.2
    ui_color = "#990066"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def night_action(self, player_obj, target_player_obj, game_context):
        return {
            "action": "direct_kill",
            "target": target_player_obj.id,
            "reason": "Serial Killer",  # Custom death reason
        }

    def check_win_condition(self, player_obj, game_context):
        # win if alive and max one non-wolf non-monster alive
        if not player_obj.is_alive:
            return False

        living_players = [p for p in game_context["players"] if p.is_alive]

        if len(living_players) == 1:
            return True

        if len(living_players) == 2:
            targets = [
                p
                for p in living_players
                if p.role.team != "Werewolves" and p.role.name_key != "Monster"
            ]
            return (
                len(targets) == 2
            )  # serial_killer is in targets + max 1 non-wolf non-monster
        return False

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Serial Killer, Who is your next victim?</h4><select id="action-select"></select> <button id="action-btn">Murder</button>',
            "post": '<p>You prepared your tools for <span style="color: crimson">${playerPicked}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": False,
        }

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]


@register_role
class Sorcerer(Role):
    name_key = "Sorcerer"
    team = "Werewolves"  # Wins with wolves
    priority = 11  # Acts around Seer time
    ui_short = "Team Werewolf. Search for other magic roles."
    ui_long = "You are on the Werewolf team but do not wake up with them to kill. Instead, you investigate players to identify who the Seer is or other magic users like the Witch and the Revealer."
    ui_rating = -0.4
    ui_color = "#B3004D"

    def __init__(self):
        super().__init__()
        self.is_night_active = True

    def investigate(self, target_player):
        # Looks for Magic users
        if target_player.role.name_key in [
            ROLE_SEER,
            ROLE_WITCH,
            ROLE_RANDOM_SEER,
            ROLE_REVEALER,
        ]:
            return "Magic User"
        return "non-Magic User"

    def night_action(self, player_obj, target_player_obj, game_context):
        result = self.investigate(target_player_obj)
        return {
            "action": "investigate",
            "target": target_player_obj.id,
            "result": result,
        }

    def get_night_ui_schema(self, player_obj, game_context):
        return {
            "pre": '<h4>Sorcerer, find the Seer or Witch!</h4><select id="action-select"></select> <button id="action-btn">Scan</button>',
            "post": '<p>You gazed into the void and saw <span style="color: purple">${playerPicked}</span> role.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "can_skip": True,
        }


@register_role
class Tough_Villager(Villager):
    name_key = ROLE_TOUGH_VILLAGER
    ui_short = "Villager who can survive one death."
    ui_long = "You have no active powers, but you are wearing armor. The first time you die, you will mysteriously survive. You only really die upon your second death."
    ui_rating = 0.7
    ui_color = "#2600D9"

    def __init__(self):
        super().__init__()

    def on_assign(self, player_obj):
        player_obj.status_effects.append("2nd_life")


@register_role
class Tough_Werewolf(Werewolf):
    name_key = ROLE_TOUGH_WEREWOLF
    ui_short = "Will survive the first attempt on their life."
    ui_long = "You hunt with the pack. If a Hunter shoots you, a Witch poisons you, Lynch-mob targets you, or the Serial Killer attacks you, you survive that first strike."
    ui_rating = -0.8
    ui_color = "#E6001A"

    def __init__(self):
        super().__init__()

    def on_assign(self, player_obj):
        player_obj.status_effects.append("2nd_life")


@register_role
class Wild_Child(Villager):
    name_key = ROLE_WILD_CHILD
    ui_short = "Picks a role model. If they die, child becomes a Werewolf."
    ui_long = "On the first night, you choose another player to be your 'Role Model.' As long as they live, and nurture you, you stay human. If they die, you become a Werewolf and join the pack."
    ui_rating = -0.3
    ui_color = "#A6005A"

    def __init__(self):
        super().__init__()
        self.role_model_id = None
        self.transformed = False
        self.is_night_active = True

    def get_valid_targets(self, game_context):
        """Returns a list of valid player IDs this role can target, exclude self."""
        return [
            p for p in game_context["players"] if p.is_alive and p.id != self.player_id
        ]

    def on_night_start(self, player_obj, game_context):
        # Check if Model died
        if self.role_model_id and self.transformed == False:
            model = next(
                (p for p in game_context["players"] if p.id == self.role_model_id), None
            )
            if model and not model.is_alive:
                self.transformed = True
                self.team = "Werewolves"
                self.priority = 45
                self.is_night_active = True
                print("Wild Child transformed!")

    def night_action(self, player_obj, target_player_obj, game_context):
        # Night 1 only: select role model
        if self.role_model_id is None and self.transformed == False:
            self.role_model_id = target_player_obj.id
            if self.role_model_id:
                self.is_night_active = False
                return {"result": "Role Model Selected"}
        # if transformed, werewolf action
        elif self.transformed:
            return {"action": "kill_vote", "target": target_player_obj.id}
        return {"action": "villager_vote", "target": target_player_obj.id}

    def get_night_ui_schema(self, player_obj, game_context):
        # select role model
        if self.role_model_id is None:
            return {
                "pre": '<h4>Wild Child, Choose your Rolemodel:</h4><select id="action-select"></select> <button id="action-btn">Choose</button>',
                "post": '<p>You look up to <span style="color:darkorange">${playerPicked}</span>.</p>',
                "targets": [
                    {"id": p.id, "name": p.name}
                    for p in self.get_valid_targets(game_context)
                ],
                "can_skip": False,
            }
        # werewolf ui
        if self.transformed:
            return {
                "pre": '<h4>Werewolf, who will you eat?</h4><select id="action-select"></select> <button id="action-btn">Kill</button>',
                "post": '<p>You are hungry for <span style="color: red" strong >${playerPicked}</span>. Waiting...</p>',
                "targets": [
                    {"id": p.id, "name": p.name}
                    for p in self.get_valid_targets(game_context)
                ],
                "can_skip": True,
            }
        # villager ui if not transformed
        else:
            return Villager.get_night_ui_schema(self, player_obj, game_context)


@register_role
class Witch(Villager):
    name_key = ROLE_WITCH
    priority = 20  # After Seer, Before Wolves to set heal
    ui_short = "Has two potions: one to kill, one to heal."
    ui_long = "You wake up before the Werewolves. You can use your Healing Potion to possibly save the victim if you guess right, or your Poison Potion to kill another player of your choice. You can use each potion only once per game."
    ui_rating = 0.3
    ui_color = "#5A00A6"

    def __init__(self):
        super().__init__()
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
            return {
                "action": "Witch Magic",
                "target": target_player_obj.id if target_player_obj else None,
                "effect": "healed",
            }

        # 3. Process Kill
        elif potion == "poison" and self.has_kill_potion:
            self.has_kill_potion = False
            return {
                "action": "Witch Magic",
                "target": target_player_obj.id if target_player_obj else None,
                "effect": "poisoned",
            }

        return {"action": "villager_vote", "target": target_player_obj.id}

    def get_night_ui_schema(self, player_obj, game_context):
        if not self.has_heal_potion and not self.has_kill_potion:
            return Villager.get_night_ui_schema(self, player_obj, game_context)

        # Format potions as {id, name} so populateSelect works
        potions = []
        if self.has_heal_potion:
            potions.append({"id": "heal", "name": "Heal Potion"})
        if self.has_kill_potion:
            potions.append({"id": "poison", "name": "Poison Potion"})
        potions.append({"id": "none", "name": "Do Nothing"})

        return {
            "pre": '<h4>Witch, who will consume a potion?</h4><select id="action-select"></select> <select id="action-select-2"></select><button id="action-btn">Feed Potion</button>',
            "post": '<p><span style="color: lawngreen">${playerPicked}</span> consumed <span style="gold">${playerPicked2}</span>.</p>',
            "targets": [
                {"id": p.id, "name": p.name}
                for p in self.get_valid_targets(game_context)
            ],
            "potions": potions,
            "can_skip": True,
        }
