# Next slice — handoff Echo can read

The envelope is done. Do not redo it. Do not restyle the page.

Echo locked two looks after you finished. Leave them alone:
- Sections rail rain in app.js / index.html. Do not remove it, recolor it, or add sparkle.
- To-do tree traces. Solid lines stay. Cyan is only the active path, and it stops above the last child under the open header. That last drop is grey. Do not put box-drawing characters back.

## Build this

Play already writes data/handoff.json. Echo cannot see that without opening the file by hand.

1. Add GET /api/handoff on the existing 127.0.0.1:8771 server.
   - Same local-only rule as the other API routes.
   - If a non-sample card is ready, return its id, title, and state.
   - If the last handoff was paused or trashed, return that honest state.
   - If there is no handoff, return {"state":"none"}.
2. POST /api/cards already adds an unfiled card. Do not rebuild it. Prove one add still lands under unfiled, newest-first, and survives a restart.
3. Extend verify.cjs for the new GET and that one add. Delete any temporary card before you finish. Restore the original cards and handoff.
4. Write NEXT-DONE.txt with the commands you actually ran and their results.

## Do not

- Do not wire the desk mic, live send, model start, Telegram, or the GPU.
- Do not bind 0.0.0.0. Do not change port 8771. Do not add a Tailscale route.
- Do not commit, push, or add a remote.
- Do not edit files outside D:\Dev\Onoes-Mesh-sandbox.
- Do not edit D:\Dev\mesh-preview.
- Do not guess header names. New cards stay unfiled.
- Do not add a people picker.
