"""
config.py
Central location for all game defaults and timer settings.
"""

GAME_DEFAULTS = {
    # Timers (in seconds)
    "TIMER_DAY": 120,
    "TIMER_NIGHT": 60,
    "TIMER_VOTE": 30,
    "TIMER_DISCUSSION": 45,
    # Game Settings
    "MIN_PLAYERS": 4,
    "DEFAULT_LANGUAGE": "en",
    # Feature Flags
    "ENABLE_PASS_AND_PLAY": False,
}

# --- Phases ---
PHASE_LOBBY = "Lobby"
PHASE_NIGHT = "Night"
PHASE_ACCUSATION = "Accusation"
PHASE_LYNCH = "Lynch_Vote"
PHASE_GAME_OVER = "Game_Over"

# --- Roles ---
# Simplified keys as requested
ROLE_WEREWOLF = "Werewolf"
ROLE_SEER = "Seer"
ROLE_VILLAGER = "Villager"
ROLE_BODYGUARD = "Bodyguard"
ROLE_WITCH = "Witch"
ROLE_CUPID = "Cupid"
ROLE_MONSTER = "Monster"
ROLE_ALPHA_WEREWOLF = "Alpha_Werewolf"
