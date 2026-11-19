---
status: proposed
date: 2026-11-19
---

# Agents say what changes; nothing is asked again and again

`errand web` and `errand tui` see the machines through their agents. The subscription (`op: watch`, `look.Watch`)
was already a stream, but behind it the agent asked itself again and again: the dates of a few directories every
few seconds, the whole table at least every 2 s, the history every 5 s (1.2 s each time on a machine with 27,000
runs, ADR 0023), the resources every 5 s. This machine was not even subscribed: asked for its table every 2 s. The
page asked `errand web` every 2 s; the console of a running run was read again by its end at each of those.

Yet an agent knows what happens: a run starts and ends in a process it started; its history changes at those two
moments; the output passes through its pipe; steps and views are written by its runs.

Settled in a grill with Hugo on 2026-11-19 (`grill/events/decisions.md`).

## Decision

- **Nothing runs when nothing happens.** A subscription waits for something to say: a process the agent started or
  saw end, a run that noted itself or wrote a step (it tells its agent, `steps.nudge`), runs removed, a watcher that
  asks. Then it looks, and sends what changed.
- **What is sent** is what changed: the table when it differs (small), the history as a **delta**
  (`{"runs": {"put": [ … ], "drop": [ leaves ]}}`), resources when they moved. A full state at the subscription
  and after a reconnection; nothing replayed.
- **A sweep every 60 s** (and at each subscription) for what does not pass through the agent: an orphan, a VM, a
  run's directory removed by hand. A difference found is sent like any other.
- **Resources are measured only when asked**: a watcher says `{"resources": true}` on its channel while it shows
  them (the machines tab), `false` when it does not; then every 5 s, sent when they move.
- **This machine is subscribed** like the others.
- **errand web pushes** to its page: `/events` (Server-Sent Events) says `runs`, `machines`, `caches`,
  `detail <key>`, as events come from the agents; the page reads `/state` or `/detail` then, and no more every 2 s
  (a slow look, 30 s, stays: a page that lost its stream).
- **The console of a running run**: its agent says `output <proc>` when a process it owns writes (at most twice a
  second), `errand web` passes it on as `detail <key>`; the page reads the end of the console then.
- **The TUI** redraws on an event or a key; the clocks that tick ( "13 s so far" ) every second, asking nobody.
- **No older agent** is kept talking: they are stopped (`errand agents stop --force`), and what they ran is run again.

## Considered options

- **Notifications of the file system** (kqueue, inotify): outside the standard library, different on each system;
  the agent knows what passes through it, and a 60 s sweep covers the rest.
- **WebSockets** to the page: not in the standard library; the page only needs to be told.
- **The output itself in the stream** ( `errand attach`'s ): the page would draw a console of its own; a notice and a
  read of the end draws the one it has, as soon as there is something.
- **Keeping older agents asked**: two ways of watching; Hugo prefers stopping them.

## Consequences

- An idle machine costs a sweep a minute; a change is seen in the time it takes to cross the agents.
- A run tells its agent when it notes itself and writes a step ( a connection, at most once a second ).
- A watcher that shows the machines asks for resources; one that does not, costs none.

## Steps

1. The agent: `Watch` waits on its pokes, sweeps every 60 s, sends deltas, resources on demand; `nudge` op; `output`
   notices.
2. The runs: `seen.note` and the steps journal nudge their agent.
3. The watcher ( `tui/machines.py` ): every machine subscribed, deltas applied, listeners told; resources asked by
   whoever shows them.
4. `errand web`: `/events`, the page reading on notice.
5. The TUI: redraws on events.

## Done, 2026-11-19

- **The bell** ( `agents/look.py` ): a named pipe `bell` in each host agent's directory, made and read from a thread
  by its first subscription ( `listen` ); `ring( outputs )` writes a line to every host agent's bell of this machine
  ( `.` or `o <proc id>` ), never waits, never fails. Rung when an agent starts a process or sees one end
  ( `agent.py`, `procs.py` ), when a process writes ( at most twice a second, the end of a burst told after it ),
  when a run notes itself ( `seen.note` ), writes its journal ( `steps.nudge`, at most once a second ) or its
  `result.yaml` ( `results.py` ), when runs are removed. Windows has no `mkfifo`: there, the subscription looks at the
  directories' dates every 0.5 s, as before.
- **`Watch`**: waits on its pokes ( the bell, `nudge` ) up to the next sweep ( 60 s ), heartbeat ( 30 s ) or measure
  ( 5 s, only while `resources` was asked on its channel: `Watch.write` ); sends the table when it differs, the
  history as `{"runs": {"put", "drop", "more"}}` after a full `{"seen"}`, `{"output": [ ids ]}`.
- **The watcher** ( `tui/machines.py` ): every machine subscribed, this one through its host agent ( `U.direct` ); an
  agent that does not know `watch` is said older, not asked; deltas applied; `LISTENERS` told of each event;
  `want_resources( on )` writes on the channel.
- **errand web**: `_hear` turns events into notices ( lists changed; the detail keys of the processes that wrote, of
  the runs put; `*` for a table ), `/events` streams them ( Server-Sent Events, a comment every 20 s, the stream
  counting as use ); the machines tab asks for resources, released 30 s after. The page listens ( `EventSource` ),
  reads `/state` on a list notice and `/detail` on one for the row shown; a look every 30 s stays; the run's
  duration ticks every second from the machine's clock, asking nobody.
- **The TUI** draws when a listener heard something, on a key, or every second ( its clocks ); it asks resources only
  on its machines tab.

Tests: `errand/tests/test_events.py` ( the bell; a subscription: full state then deltas, nothing read again while
idle, resources when asked; the watcher's deltas and listeners; `/events` end to end ); `test_tui.py`, `test_web.py`
( the page's constant, a screen read over the whole stream ), `test_status.py`, `test_runs_tree.py` pass. Seen:
idle, the page read once in 12 s ( an event ) instead of six times; a foam run on lmo, 90 notices in ~50 s, the page
following it as it went.

Not done: the console of a running run is read again on an output notice, not streamed itself ( ADR's option of the
notice ); the caches tab still asks its machines every 30 s while shown ( ADR 0022 ).
