# Relay goal pin

Checked 2026-10-10. Set, replace, and clear call the same Hermes goal store Desktop uses.

- Session: `relay-eddie-echo`. Not the Telegram session.
- Command: `hermes_cli.goals.GoalManager` through `relay_goal.py`.
- Edit fills the one box and arms goal. Send replaces the standing goal. There is no separate edit command.
- Pause and resume call GoalManager. Trash is clear. The bar sits on the prompt only while a goal is active or paused. Click the summary to read the whole line. No timer. A clock would pretend the pin started work.
- The goal text is not stored in a Mesh file.
- A work turn is not queued yet. Setting the goal does not start Echo.
- Live chat send stays off.

The phone reaches this through the local listener on 127.0.0.1:8772. The old listener on 8771 was left up because its command line could not be read.
