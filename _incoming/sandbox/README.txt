Run from D:\Dev\Onoes-Mesh-sandbox:

    python -B server.py

Open http://127.0.0.1:8771/ . Stop with Ctrl+C and run the same command to restart.
The server binds only 127.0.0.1:8771 and uses Python's standard library.

Open config, enter a short title (optional note), and choose keep local.
New cards stay in Unfiled. Sample headers and sample cards are examples.
Samples cannot be played or sent. No people picker or outside services.

Play saves ready state and data/handoff.json (id, title, state).
Playing another live card pauses the previous one without trashing it.
Pause keeps the card and changes the current handoff state to paused.
Trash is recoverable through config's trash filter; cards are not auto-deleted.
Pins also show a card in Category 0 without changing its header.

Disk state: data/cards.json. Do not edit it while the server is running.
Writes replace complete JSON files. Startup reconstructs the handoff from saved
state if a stop interrupted the two file writes. Invalid existing JSON fails
startup rather than resetting cards. The locked reference is unchanged.

The same menu now opens overview, workroom, relay, to-do, and log.
To-do remains the default page. Section hashes support reload and browser Back.
All pages use the to-do terminal and glass shell. On a phone, open [nav].

Overview: expand the pinned goal and read the sample machine notes.
Workroom: filter the preview's sample tasks and open their sample details.
Relay: Eddie and Echo only. Keep local adds text in this page until reload.
Live send is inactive; the relay composer never writes a handoff or sends work.
Log: read the Crew/Mind preview fixtures, not live service status.
Config outside to-do has the preview's fixture-tag and compact-card toggles.
N-gram pin and live changes remain inactive preview controls.
Desk mic, model start, Telegram, and GPU integration remain unwired.

Verification: node verify.cjs (stop the app first). The checks temporarily add
cards, restart the server, then restore the original cards and handoff. Run
python -B server.py again afterward. Browser verification uses a workspace
Chrome profile and a debugging pipe, with no additional listening port.
Evidence: .verification/envelope-results.json and design-qa.md.
