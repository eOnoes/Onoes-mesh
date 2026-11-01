# Box rules

This is the local build copy. It is not the live site.

- Live site stays `http://127.0.0.1:4317`, node PID 96164. Do not stop it.
- This box uses port 4318 and data dir `test/app03-local-pc-box`.
- The server rejects any data dir that is not `test/app03-...` or `data/...`. That is why this is not `test/local-pc-box`.
- `MESH_STANDALONE=1`. Relay stays off.
- Do not copy or open `D:\Dev\Onoes-Mesh\test\app03-manager-m1-disposable`.
- Do not edit `config/commands.json`.
- Do not add a git remote. Do not push.

Working bar: start a session, create a task, edit it, mark it done, and see it after refresh.
