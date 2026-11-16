# errand web: decisions

- **Where**: in the agents. Each agent page shows every machine of its own ledger, asked as `errand tui` asks them ( `tui/machines.py`, `tui/rows.py` ): the Mac's page shows everything, lmo's its own ledger ( often lmo alone ).
- **One per user per machine**: the agent that holds `~/.cache/errand/web.lock` serves; the others ( environments, nested agents ) do not. It writes `web.json` { port, token, pid } ( mode 0600 ).
- **Address**: `127.0.0.1` only, port = 20000 + uid % 10000 ( stable, so a ssh tunnel stays the same ); taken → any free port, said in `web.json`. No remote access other than `ssh -L`.
- **Access**: a random token per agent, in the URL `errand web` opens, then an `HttpOnly; SameSite=Strict` cookie; no token → 403. `Host` checked ( DNS rebinding ).
- **Command**: `errand web` starts the local agent if needed, reads `web.json`, opens the browser at the URL with its token ( and prints it ).
- **Life**: served from the agent's start; a page request counts as use ( keeps the agent ). Machines are asked only while a page asks ( watchers start on request, stop 30 s after the last one ), so a closed page keeps no remote agent busy.
- **Actions**: stop a process ( and a VM, as the tui ), POST + `confirm()` + token. No agent stop.
- **Refresh**: polling ( 2 s ), one HTML page with inline JS, JSON behind. Stdlib only ( `http.server` ).
