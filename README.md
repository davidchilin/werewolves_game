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
separate video or voice chat (like Zoom or Discord), where the real-time
discussion and deception take place.

## **Core Features (Implemented)**

- **Secure Game Lobby:** Players join a single game instance using a shared,
  verbally communicated game code.
- **Admin Controls:** The first player to join becomes the admin and has the
  ability to:
  - Exclude players from the lobby.
  - Start the game once enough players have joined (minimum of 4).
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
- **Night Phase Logic:**
  - Living wolves can each vote to kill a player. A kill only succeeds if all
    living wolves vote for the same person.
  - The living seer can choose one player to reveal their role (the result is
    shown only to the seer).
- **Live Game Updates:** The UI updates in real-time for all players using
  WebSockets, showing phase changes, player status, and game log events.
- **Dark Mode UI:** A clean, modern dark theme for comfortable gameplay.

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

- **Phase 3: Day Phase \- Accusations & Voting:**
  - Implement the ability for living players to accuse each other during the
    day.
  - Allow players to vote to end the day phase early and immediately start the
    night.
- **Phase 4: Day Phase \- Lynch Execution:**
  - Tally accusations to determine the most-accused player.
  - Implement a majority-rules vote to lynch the accused player.
- **Phase 5: Winning Conditions & Game Loop:**
  - Check for win conditions after every death (Villagers win if all wolves are
    dead; Wolves win if they equal or outnumber other players).
  - Implement a "Game Over" screen and a "Return to Lobby" button.
- **Phase 6: Refinements:**
  - Add automated timers for phases.
  - Improve UI/UX with more visual cues and animations.
