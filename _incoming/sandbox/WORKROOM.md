Workroom and one real card. Local only. Eddie and Echo.

The phone page is already up at http://127.0.0.1:8771/ and through Tailscale. Do not run tailscale. Do not change serve routes. Do not enable funnel. Do not bind 0.0.0.0. Do not touch the host allowlist in server.py.

Do not touch relay. Do not touch the log page. Do not touch Mind. Do not touch the rain. Do not restyle the overview hardware cards. Those stay labeled sample. Do not commit or push.

Two changes:

1. To-do needs a way to add one real card from the phone. POST /api/cards already accepts JSON {"title","note"}. Title 1 to 40 characters. Note optional, under 1001. The new card is unfiled, sample false, state idle, who Eddie. Put a small add field on the to-do page, same card family, not a new look. After a successful add, the new card is in the list with play enabled. Sample cards stay disabled. Do not invent a second store.

2. Workroom must stop showing the three fixture buttons. Read GET /api/handoff. If state is none or the file is missing, show one empty card: "Nothing held." If state is ready, show that one card, marked held by Echo. If state is paused, show that same card marked paused. Same overview card family. No model starts. No download. The filters can go. A tap must not write a fake sentence.

Verify on http://127.0.0.1:8771/ only:
- add a temp card, confirm play is enabled, then trash it and confirm the original sample cards are unchanged
- workroom shows Nothing held when no handoff is ready
- relay, log, rain, and overview sample text are unchanged
- write the commands and what you saw in WORKROOM-DONE.txt

Do not leave the temp card in the list.
