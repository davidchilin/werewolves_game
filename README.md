# **Werewolves \- A Flask-based Multiplayer Game**

A real-time, multiplayer social deduction game inspired by Mafia and Werewolf.
This web application is built primarily with Python, using the Flask framework
and WebSockets for live player interaction. I made this to practice using an
LLM.

## **Description**

This project is a web-based implementation of the classic party game Werewolves.
Players join a lobby using a unique game code, are secretly assigned roles
(Villager, Wolf, or Seer), and then enter a cycle of "night" and "day" phases.
During the night, wolves secretly choose a player to eliminate, and the seer can
investigate a player's role. During the day, players discuss and vote to lynch
someone they suspect is a wolf. The game is designed to be played alongside a
separate video or voice chat (like Jitsi Meet or Zoom), where the real-time
discussion and deception take place.

## **Core Features (Implemented)**

- **Secure Game Lobby:** Players join a single game instance using a shared,
  verbally communicated game code.
- **Admin Controls:** The first player to join becomes the admin and has the
  ability to:
  - Exclude players from the lobby.
  - Start the game once enough players have joined (minimum of 4).
  - Set custom timer durations (in seconds) for the Night, Accusation, and Lynch
    Vote phases.
  - Set a new game code.
- **Persistent Sessions:** Players can refresh their browser or momentarily
  disconnect without losing their place in the game.
- **Dynamic Role Assignment:** At the start of the game, players are randomly
  and secretly assigned one of three roles:
  - **Villager:** Must work to find and eliminate the wolves.
  - **Wolf:** Must work with other wolves to eliminate villagers until they have
    the majority.
  - **Seer:** A special villager who can investigate one player's role each
    night.
- **Live Game Updates:** The UI updates in real-time for all players using
  WebSockets, showing phase changes, player status, and game log events.
- **Dark Mode UI:** A clean, modern dark theme for comfortable gameplay.

## Game Phases

- Night Phase (Timed):

  - Phase ends when either the timer runs out OR all Wolves and the Seer have
    submitted their actions.
  - Wolves: Secretly vote to kill a player. A kill only succeeds if all living
    wolves vote unanimously for the same player. They can also choose to kill
    "Nobody". If the timer expires, any non-voting wolf's action is skipped.
  - Seer: Investigates one player's role each night. The result is shown only to
    the seer. They can also choose to see "Nobody". If the timer expires, the
    Seer's action is skipped.

- Accusation Phase (Timed):

  - Phase ends when either the timer runs out OR all living players have made an
    accusation.
  - Living players vote to accuse one person or "Nobody".
  - If the timer expires, any non-voting player defaults to accusing "Nobody".
  - A live count of accusations is displayed next to each player's name.
  - Tie-Breaking Logic: If there is a tie for the most accused player:
    - If the tie is between only two players, no lynch vote occurs.
    - If the tie is among more than two players, the accusation phase is
      restarted once. A second tie results in no lynch vote.

- Lynch Vote Phase (Timed):

  - If a single player has the most accusations, a trial begins.
  - Phase ends when either the timer runs out OR all living players have voted.
  - Living players vote "Yes" or "No" to lynch the accused player.
  - If the timer expires, any non-voting player defaults to a "No" vote.
  - A majority "Yes" vote is required for the lynch to succeed.
  - A detailed summary of who voted "Yes" and "No" is displayed in the game log.

- General Day Phase Actions: Living players can vote to end the day phase early
  and immediately start the night. If a majority is reached, the game
  transitions.

## **Tech Stack**

- **Backend:** Python 3.10
- **Framework:** Flask
- **Real-time Communication:** Flask-SocketIO
- **Frontend:** Jinja2 for server-side templating, with vanilla HTML, CSS, and
  JavaScript for client-side interactivity.

## **Setup and Running the Project**

To run this project locally, follow these steps:

1. **Clone the repository:** git clone
   https://github.com/davidchilin/werewolves\_game.git cd werewolves_game

2. **Create and activate a virtual environment:**

   - **Windows:** python \-m venv venv .\\venv\\Scripts\\activate

   - **macOS / Linux:** python3 \-m venv venv source venv/bin/activate

3. Install the required dependencies: (You may need to create a requirements.txt
   file first) pip install Flask Flask-SocketIO python-uuid

4. **Run the Flask application:** python app.py

5. Access the game: Open your web browser and go to http://127.0.0.1:5000. Open
   multiple tabs or browsers to simulate different players joining the game.

## **Project Roadmap**

This project is under active development. The next planned features are:

- **Phase 5: Winning Conditions & Game Loop:**
  - Check for win conditions after every death (Villagers win if all wolves are
    dead; Wolves win if they equal or outnumber other players).
  - Implement a "Game Over" screen and a "Return to Lobby" button.
- **Phase 6: Refinements:**
  - Add automated timers for phases.
  - Improve UI/UX with more visual cues and animations.
