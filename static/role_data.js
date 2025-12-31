// static/role_data.js
// v 4.6.0

const ROLE_DATA = {
  "Alpha Werewolf": {
    short: "Solo wins if last one standing.",
    long: "You are the leader of the Werewolves. You vote with the pack to kill at night. However, your goal is to sit alone on your mountain.",
    rating: -0.5,
    color: "#C00040",
  },
  "Backlash Werewolf": {
    short:
      "Ability to strike another player with your dying breath (like Hunter).",
    long: "You are a Werewolf with deathly reflexes. You may choose a player at Night to kill upon your death.",
    rating: -1.0,
    color: "#FF0000",
  },
  Bodyguard: {
    short:
      "Choose a player to protect from Werewolves. Can't select same player twice in a row.",
    long: "Every night, you may choose one player to guard. If the Werewolves attack that player, your protection saves them, and nobody dies. You cannot protect the same person two nights in a row.",
    rating: 0.5,
    color: "#4000C0",
  },
  Cupid: {
    short:
      "Link two players in love. If one dies, the other dies of a broken heart.",
    long: "On the first night, choose two players to be 'Lovers.' These two learn their lover name. Their fates are linked: if one is killed (at night or by lynching), the other dies immediately from grief.",
    rating: -0.2,
    color: "#990066",
  },
  "Demented Villager": {
    short: "Solo win if last one standing.",
    long: "You have no special powers and appear as a Villager to the Seer. However, ChatGPT convinced you to kill everyone for the WIN.",
    rating: 0.2,
    color: "#660099",
  },
  Fool: {
    short: "Your goal is to get yourself lynched by the village.",
    long: "You are a neutral chaos agent. You are not part of the villagers nor the werewolves.Although your ultimate win is successful if you convince the town to successfully Lynch you.",
    rating: -0.2,
    color: "#990066",
  },
  Honeypot: {
    short: "A trap role. If you are killed, your killer dies with you.",
    long: "You are a Villager, but dangerous to touch. If you are killed—whether by Werewolves or a Lynch mob — they will pay with their life.",
    rating: 0,
    color: "#800080",
  },
  Hunter: {
    short: "As you die, you fire an arrow with your last ounce of strength.",
    long: "During the night you may select someone to kill upon your death.",
    rating: 0.4,
    color: "#4D00B3",
  },
  Lawyer: {
    short: "Choose a client at night. They cannot be lynched the next day.",
    long: "You work to defend the accused. At night, you select a player to be your client. If that player goes to lynch trial, the lynching will fail, and they will survive.",
    rating: 0.2,
    color: "#660099",
  },
  Martyr: {
    short: "Gift a player to receive a 2nd life upon your death.",
    long: "At night you can select a player to take your life force upon your death.",
    rating: 0.2,
    color: "#660099",
  },
  Mayor: {
    short:
      "Your vote can break a tie during accusations. You can pass on role to certain roles.",
    long: "You are the leader of the village. Because of your political influence, your vote carries tie-breaking weight during the daily accusation. You can secretly announce your successor. Your successor can only name their successor if their role has no night actions.",
    rating: 0.4,
    color: "#4D00B3",
  },
  Monster: {
    short:
      "You are a supernatural beast. You cannot be eaten by Werewolves, but are seen as one.",
    long: "You are not on the Villager team or the Werewolf team; you are on your own. You are immune to the Werewolf attacks, but are seen as a werewolf.",
    rating: 0.3,
    color: "#5A00A6",
  },
  Prostitute: {
    short:
      "Visit a player at night to block their night choices. If you or your visitor die, you both die.",
    long: "Each night, you can visit another player. The visiting player's night selection is secretly cancelled. If you or the visiting player is killed, you both die. Visit most of the players for a solo win!",
    rating: 0.4,
    color: "#4D00B3",
  },
  "Random Seer": {
    short:
      "Use with normal Seer role. 25% sane, 25% paranoid, 25% naive, 25% insane.",
    long: "25% sane, 25% paranoid (see werewolves everywhere), 25% naive (sees only villagers), 25% insane (sees opposite role). Should be played with normal seer, Seer mental state is a secret attribute.",
    rating: -0.1,
    color: "#8D0073",
  },
  Revealer: {
    short:
      "Can reveal a player's role. If reveal a Wolf: they die. If Villager: YOU die.",
    long: "You have a high-stakes power. You choose a player to 'Reveal.' If they are a Werewolf, they are exposed and killed immediately. If they are a Villager, you die of embarrassment for accusing an innocent.",
    rating: 0.3,
    color: "#5A00A6",
  },
  Seer: {
    short: "Choose a player at night to learn if they are a werewolf.",
    long: "You are the village's most powerful investigator. Every night, you select one player to reveal that player's team - werewolves or villagers.",
    rating: 1.0,
    color: "#0000FF",
  },
  "Serial Killer": {
    short:
      "You are a lone killer. Kill one person nightly. Win if last one standing.",
    long: "You are a third party. You do not win with the Village or the Werewolves. Every night, you choose a victim to mutilate. Your kills cannot be stopped by the Bodyguard.",
    rating: -0.2,
    color: "#990066",
  },
  Sorcerer: {
    short:
      "You are the Seer for the Werewolves. You look for the Seer or other magic roles.",
    long: "You are on the Werewolf team but do not wake up with them to kill. Instead, you investigate players to identify who the Seer is or other magic users.",
    rating: -0.4,
    color: "#B3004D",
  },
  "Tough Villager": {
    short: "You are a Villager who can survive one death.",
    long: "You have no active powers, but you are wearing armor. The first time you die, you will mysteriously survive. You only really die upon your second death.",
    rating: 0.7,
    color: "#2600D9",
  },
  "Tough Werewolf": {
    short: "A Werewolf that survives the first attempt on their life.",
    long: "You hunt with the pack. If a Hunter shoots you, a Witch poisons you, Lynch-mob targets you, or the Serial Killer attacks you, you survive that first hit.",
    rating: -0.8,
    color: "#E6001A",
  },
  Villager: {
    short: "Find the Werewolves and vote them out.",
    long: "You have no special night abilities. Your strength lies in your vote and your deduction skills. Listen to the others, find the inconsistencies, and lynch the beasts.",
    rating: 0.4,
    color: "#4D00B3",
  },
  Werewolf: {
    short: "Wake up at night to kill a Villager. Don't get caught.",
    long: "You are part of the pack. Every night, you wake up with the other Werewolves and agree unanimously on a victim to kill. During the day, you must act like an innocent Villager to avoid being lynched.",
    rating: -0.6,
    color: "#CC0033",
  },
  "Wild Child": {
    short: "Pick a role model. If they die, you become a Werewolf.",
    long: "On the first night, you choose another player to be your 'Role Model.' As long as they live, and nurture you, you stay human. If they die, you become a Werewolf and join the pack.",
    rating: -0.3,
    color: "#A6005A",
  },
  Witch: {
    short: "You have two potions: one to kill a player, one to save a victim.",
    long: "You wake up before the Werewolves. You can use your Healing Potion to possibly save the victim if you guess right, or your Poison Potion to kill another player of your choice. You can use each potion only once per game.",
    rating: 0.3,
    color: "#5A00A6",
  },
};
