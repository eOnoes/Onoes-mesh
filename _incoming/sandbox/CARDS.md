# Cards on every tab

Eddie is on his phone. The card he wants is the overview stack, not the to-do tree and not the open note under 001. Screenshot: `C:\Users\eMitchell109\AppData\Local\hermes\cache\images\img_d284ab5757da.jpg`

Copy the existing overview card already in index.html (`article.glass` / `.page .glass`):
- background `rgba(18, 22, 20, 0.72)`
- left rule `2px solid var(--cyan)`. Do not invent a yellow border.
- title in yellow brackets, like `[ This PC ]`
- body left aligned
- grey tag under it, like `fixture · sample, not live hardware`
- stacked, full phone width, square corners
- on overview, the pinned goal sits on its own row. Do not let the lime line collide with `PINNED GOAL`. Do not change the sample hardware sentences.

Tabs, all five, same card family:
- overview
- workroom
- relay
- to-do
- log

To-do: remove the traced file tree. No cyan spine, no grey elbows, no box-drawing, no `├─`. Headers stay short names (Category 0, Mesh, Models, Forge, Crew, Unfiled). Do not rename a header 1, 2, 3, or 4. Items are stacked overview cards, newest first. One header open, then one card. Opening another closes the previous. Pin, play, pause, trash, and the sample label stay on the card. A control must not look like a live dispatch.

Other tabs: restyle their existing content into that same overview card. Do not invent a new page, a YouTube flow, a mic, a live send, a model start, or a GPU action. Relay still lists Echo, Cyony, Tripp, and DeepSeek if that row is already there. Do not drop Echo.

Leave alone:
- Sections rail rain in app.js and index.html. No sparkle, no `#0F0` rain, no standing residue columns.
- Nav chrome: `[nav]`, cyan `>`, yellow brackets, dark gray nav, soft left fade, active white, inactive medium grey.
- Host allowlist and the listen address `127.0.0.1:8771`. Do not run tailscale. Do not bind `0.0.0.0`.
- Card data on disk, except a render change.

Phone fills the screen. Text stays left aligned. No sideways scroll. Desktop stays the centered column. Add a no-store meta if the page can be cached, so his phone does not keep the old tree.

Prove it in a phone-width browser, about 390px, on `http://127.0.0.1:8771/`:
- to-do shows cards, not a traced tree
- the open card matches the panel, lime body, and grey meta above
- overview, workroom, relay, and log each show that same card family
- rain still draws on the sections rail
- write the commands and what you actually saw in `CARDS-DONE.txt`

Do not commit or push.
