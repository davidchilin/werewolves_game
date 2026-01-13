// static/role_data.js
// v 4.8.6a

const ROLE_DATA = {
  "Alpha Werewolf": {
    short: "Solo wins if last one standing.",
    long: "You are the leader of the Werewolves. You vote with the pack to kill at night. However, your goal is to sit alone on your mountain. Solo win if only living werewolf with maximum of one living non-Monster.",
    rating: -0.5,
    color: "#C00040",
  },
  "Backlash Werewolf": {
    short: "Can strike another player with last dying breath.",
    long: "You are a Werewolf with deathly reflexes. You may choose a player at Night to avenge upon your death.",
    rating: -1.0,
    color: "#FF0000",
  },
  Bodyguard: {
    short: "Chooses a player to protect from Werewolves.",
    long: "Every night, you may choose one player to guard. If the Werewolves attack that player, your protection saves them, and nobody dies. You cannot protect the same person two nights in a row.",
    rating: 0.5,
    color: "#4000C0",
  },
  Cupid: {
    short: "Link two players in fatal love.",
    long: "On your first night, choose two players to be 'Lovers.' These two learn their lover name. Their fates are linked: if one is killed (at night or by lynching), the other dies immediately of a broken heart.",
    rating: -0.2,
    color: "#990066",
  },
  "Demented Villager": {
    short: "Solo wins if last one standing.",
    long: "You have no special powers and appear as a Villager to the Seer. However, ChatGPT convinced you to kill everyone for the WIN. Note you won't be last if left with a Monster, Honeypot, Hunter, Serial Killer, and Wild Child.",
    rating: 0.2,
    color: "#660099",
  },
  Fool: {
    short: "Tries to get themselves lynched by the village.",
    long: "You are a neutral chaos agent. You are not part of the villagers nor the werewolves. Although your ultimate win is successful if you convince the town to Lynch you.",
    rating: -0.2,
    color: "#990066",
  },
  Honeypot: {
    short: "A trap role. If killed, their killer dies too.",
    long: "You are a Villager, but dangerous to touch. If you are killed, whether by Werewolves or a Lynch mob — they will pay with their life.",
    rating: 0,
    color: "#800080",
  },
  Hunter: {
    short: "Can strike another player with last dying breath.",
    long: "During the night you may select someone to kill upon your death.",
    rating: 0.4,
    color: "#4D00B3",
  },
  Lawyer: {
    short: "Chooses a client to be unlynchable the next day.",
    long: "You work to defend the accused. At night, you select a player to be your client. If that player goes to lynch trial, the lynching will fail, and they will survive.",
    rating: 0.2,
    color: "#660099",
  },
  Martyr: {
    short: "Gifts a player to receive a 2nd life upon their death.",
    long: "At night you can select a player to absorb your life force upon your death.",
    rating: 0.2,
    color: "#660099",
  },
  Mayor: {
    short: "Vote can break a tie during accusations.",
    long: "You are the leader of the village. Because of your political influence, your vote carries tie-breaking weight during the daily accusation. You can secretly announce your successor. Your successor can only name their successor if their role has no night actions, like a Villager or Monster.",
    rating: 0.4,
    color: "#4D00B3",
  },
  Monster: {
    short: "Solo wins if last one standing. Teamless",
    long: "You are a supernatural beast. You are not on the Villager team or the Werewolf team; you are on your own. You are immune to the Werewolf attacks and are seen as a Werewolf. Solo win if alive with maximum of one living Werewolf.",
    rating: 0.3,
    color: "#5A00A6",
  },
  Prostitute: {
    short: "Visit a player at night and block their night choices.",
    long: "Each night, you can visit another player. The visiting player's night selection is secretly cancelled. If you or the visiting player is killed, you both die. Visit most of the players for a solo win!",
    rating: 0.4,
    color: "#4D00B3",
  },
  "Random Seer": {
    short: "Has secret attribute: sane, paranoid, naive, insane",
    long: "25% sane normal, 25% paranoid (see werewolves everywhere), 25% naive (sees only villagers), 25% insane (sees opposite role). Should be played with normal Seer. Seer mental state is a secret attribute.",
    rating: -0.1,
    color: "#8D0073",
  },
  Revealer: {
    short:
      "Reveal a player's role? Reveal: Wolf- Wolf dies; Villager- You die.",
    long: "You have a high-stakes power. You choose a player to 'Reveal.' If they are a Werewolf, they are exposed and killed immediately. If they are a Villager, you die of embarrassment for accusing an innocent.",
    rating: 0.3,
    color: "#5A00A6",
  },
  Seer: {
    short: "See a player's sole at night! (Werewolf?)",
    long: "You are the village's most powerful investigator. Every night, you select one player to reveal that player's team - werewolves or villagers. Note the Monster is seen as a Werewolf.",
    rating: 1.0,
    color: "#0000FF",
  },
  "Serial Killer": {
    short: "Kills one person nightly. Wins if last one standing.",
    long: "You are a third party. You do not win with the Villagers or the Werewolves. Every night, you choose a victim to mutilate. Your kills cannot be stopped by the Bodyguard. You can only solo win with maximum of one other living human.",
    rating: -0.2,
    color: "#990066",
  },
  Sorcerer: {
    short: "Team Werewolf. Search for other magic roles.",
    long: "You are on the Werewolf team but do not wake up with them to kill. Instead, you investigate players to identify who the Seer is or other magic users like the Witch and the Revealer.",
    rating: -0.4,
    color: "#B3004D",
  },
  "Tough Villager": {
    short: "Villager who can survive one death.",
    long: "You have no active powers, but you are wearing armor. The first time you die, you will mysteriously survive. You only really die upon your second death.",
    rating: 0.7,
    color: "#2600D9",
  },
  "Tough Werewolf": {
    short: "Will survive the first attempt on their life.",
    long: "You hunt with the pack. If a Hunter shoots you, a Witch poisons you, Lynch-mob targets you, or the Serial Killer attacks you, you survive that first strike.",
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
    short: "Kill Villagers at night. Don't get caught.",
    long: "You are part of the pack. Every night, you wake up with the other Werewolves and must agree unanimously on a victim to kill. During the day, you must colloborate with the other Werwolves while still acting like an innocent Villager to avoid being caught.",
    rating: -0.6,
    color: "#CC0033",
  },
  "Wild Child": {
    short: "Picks a role model. If they die, child becomes a Werewolf.",
    long: "On the first night, you choose another player to be your 'Role Model.' As long as they live, and nurture you, you stay human. If they die, you become a Werewolf and join the pack.",
    rating: -0.3,
    color: "#A6005A",
  },
  Witch: {
    short: "Has two potions: one to kill, one to heal.",
    long: "You wake up before the Werewolves. You can use your Healing Potion to possibly save the victim if you guess right, or your Poison Potion to kill another player of your choice. You can use each potion only once per game.",
    rating: 0.3,
    color: "#5A00A6",
  },
};
