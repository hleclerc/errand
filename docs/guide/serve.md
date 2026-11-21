# Servers kept while used: errand serve

```bash
errand serve --gpus 1 --gpu-ram 10G -- ollama serve     # started if need be; prints its address
errand serve                                           # the services of this machine
errand serve stop ollama
```

Some work is a server: an LLM that answers an application, a viewer that serves the frames of a run.
It should start when somebody asks for it, never twice, stop when nobody uses it, and, on a machine
shared with computations, hold its share of the card only while it works.

`errand serve` does that. The server runs under a **keeper**, a process of this machine's agent that
outlives the command that asked for it: it is listed by `errand status`, stopped with the rest, and
never left behind. Its share of the machine goes through the [queue](./machine), like a run's.

- **Started on demand, never twice.** Two `errand serve` at once start one server.
- **Stopped when nobody uses it**: after `--idle` ( 10 minutes by default ) with no connection open
  and the server not busy.
- **Its share given back while it rests.** In use, its claim is firm. Idle, it is kept warm: a
  computation that needs the card asks it to go, and it goes.
- **One address, kept.** The port is chosen once for the name and kept, so a client, a tunnel or a
  bookmark keeps working from one start to the next.

## Two sides, errand in between

<svg class="port-diagram" viewBox="0 0 760 390" role="img" aria-label="Clients connect to the announced ports, where errand's keeper listens; the keeper relays to the server's ports">
  <text x="0" y="16" class="head">announced ports</text>
  <text x="0" y="33" class="dim">yours to fix, or chosen once and kept</text>
  <text x="590" y="16" class="head">the server's ports</text>
  <text x="590" y="33" class="dim">chosen at each start, or fixed</text>
  <rect x="0" y="62" width="170" height="34" rx="6" class="box"/><text x="12" y="84">curl, a script</text>
  <rect x="0" y="108" width="170" height="34" rx="6" class="box"/><text x="12" y="130" class="mono">ollama run</text>
  <rect x="0" y="154" width="170" height="34" rx="6" class="box"/><text x="12" y="176">your laptop, ssh -L</text>
  <rect x="0" y="214" width="170" height="34" rx="6" class="box"/><text x="12" y="236">a gRPC client</text>
  <rect x="0" y="282" width="170" height="34" rx="6" class="box"/><text x="12" y="304" class="dim">another account</text>
  <path d="M170 79 C 205 79, 210 120, 245 120" class="wire"/>
  <path d="M170 125 L 245 120" class="wire"/>
  <path d="M170 171 C 205 171, 210 120, 245 120" class="wire"/>
  <path d="M170 231 L 245 231" class="wire"/>
  <path d="M170 299 C 200 299, 205 270, 225 262" class="refused"/>
  <path d="M220 253 l 12 12 M232 253 l -12 12" class="cross"/>
  <rect x="250" y="50" width="260" height="270" rx="10" class="keeper"/>
  <text x="380" y="74" text-anchor="middle" class="head">errand ( the keeper )</text>
  <text x="270" y="152" class="dim">listens as long as it lives,</text>
  <text x="270" y="168" class="dim">server up or not</text>
  <text x="270" y="190" class="dim">holds a connection while it</text>
  <text x="270" y="206" class="dim">waits for its share of the card</text>
  <text x="270" y="262" class="dim">counts them: one open = in use</text>
  <text x="270" y="278" class="dim">closes other accounts' ( Linux )</text>
  <text x="270" y="294" class="dim">asks the probe: busy?</text>
  <text x="270" y="310" class="dim">starts and stops the server</text>
  <circle cx="250" cy="120" r="8" class="port"/><text x="266" y="104" class="mono">http 127.0.0.1:11435</text>
  <circle cx="250" cy="231" r="8" class="port"/><text x="266" y="236" class="mono">grpc :50051</text>
  <circle cx="510" cy="120" r="8" class="port"/><text x="494" y="104" text-anchor="end" class="mono">{port:http}</text>
  <circle cx="510" cy="231" r="8" class="port"/><text x="494" y="236" text-anchor="end" class="mono">{port:grpc}</text>
  <path d="M518 120 L 590 120" class="wire"/>
  <path d="M518 231 L 590 231" class="wire"/>
  <rect x="590" y="90" width="170" height="170" rx="6" class="box"/>
  <text x="602" y="114">the server</text>
  <text x="602" y="138" class="dim">listens on 127.0.0.1,</text>
  <text x="602" y="154" class="dim">on the ports errand</text>
  <text x="602" y="170" class="dim">gave it; only errand</text>
  <text x="602" y="186" class="dim">connects there</text>
  <text x="602" y="216" class="dim">runs with the cards</text>
  <text x="602" y="232" class="dim">granted ( CUDA_VISIBLE_</text>
  <text x="602" y="248" class="dim">DEVICES... )</text>
  <path d="M380 320 L 380 342" class="link"/>
  <rect x="250" y="342" width="260" height="46" rx="6" class="box"/>
  <text x="380" y="361" text-anchor="middle">the machine's queue</text>
  <text x="380" y="378" text-anchor="middle" class="dim">its claim: firm in use, warm at rest</text>
</svg>

Each port of a service has two sides.

- **The announced side** is where clients connect. errand listens there itself, from the first
  `errand serve` until the service stops, whether the server is up or not. A connection that comes
  while the server waits for its share of the card is accepted and held, then relayed once the
  server answers. This side is yours to fix ( `11435` ), or errand chooses it once and keeps it for
  the name.
- **The server's side** is where the server listens, on 127.0.0.1. Only errand connects there. errand
  gives it to the server as `{port:NAME}` in its command and its environment, chooses a free one at
  each start, or takes the one you fix.

errand sits between the two to see every connection: that is how it knows the server is used
whatever its protocol, holds connections while the card is taken, and closes those from other
accounts.

Both sides can be fixed, but they cannot be the same number: errand listens on one and the server on
the other. To have the server where its clients expect it ( Ollama's `11434` ), fix the
**announced** side to that number, and let the server's be chosen.

## Ad hoc, or declared

On the command line, the server's command after `--`:

```bash
errand serve --name ollama --gpus 1 --gpu-ram 10G --idle 10m --port 11435 \
             --busy-if 'curl -s localhost:{port}/api/ps | grep -q "\"name\""' \
             -- env OLLAMA_HOST=127.0.0.1:{port} ollama serve
```

Or declared once, in `~/.config/errand/services.py` ( it belongs to a machine and a user, not to a
project ), or in any `errand-*.py` of a project:

```python
# ~/.config/errand/services.py
import errand

errand.services[ "ollama" ] = errand.Service(
    [ "ollama", "serve" ],
    env   = { "OLLAMA_HOST": "127.0.0.1:{port}" },
    gpus  = 1, gpu_ram = "10G", label = "ollama",
    busy  = errand.http_json( "/api/ps", lambda r: bool( r[ "models" ] ) ),
    idle  = "10m",
    ports = 11435 )            # leave it out: errand chooses one, once, and keeps it
```

```bash
errand serve ollama         # its address, once it answers
```

`{port}`, in the command and in `env`, is the server's side of the port; `$PORT` holds it too. The
cards granted are given as a run gets them ( `CUDA_VISIBLE_DEVICES`... ).

## Several ports, named

A server that listens on several ports names each of them; the command gets each one's server side
as `{port:NAME}`, and the environment as `$PORT_NAME`:

```python
errand.services[ "triton" ] = errand.Service(
    [ "tritonserver", "--model-repository", "/models",
      "--http-port", "{port:http}", "--grpc-port", "{port:grpc}", "--metrics-port", "{port:metrics}" ],
    gpus  = 1,
    ports = { "http":    8000,          # announced 8000, the server's chosen at each start
              "grpc":    "8001:18001",  # both fixed: announced 8001, the server on 18001
              "metrics": None } )       # both chosen, the announced one kept
```

```bash
errand serve triton                 # triton  http http://127.0.0.1:8000  grpc http://127.0.0.1:8001  metrics ...
errand serve triton --url grpc      # http://127.0.0.1:8001
errand serve --port http=8000 --port grpc=8001:18001 -- tritonserver --http-port {port:http} ...
```

A port is `"ANNOUNCED:SERVER"`, either side left empty for errand to choose ( `":18001"`, `"8000:"` ),
an int for the announced side, or `None`. A single port without a name is called `port`, and `{port}`
is its server side; with several, `{port}` alone is refused, and so is a `{port:NAME}` that names
none of them, when the service is declared rather than when it starts. A fixed server side that is
already taken stops the start with `port grpc: the server's side, 18001, is taken`.

The service is in use as long as a connection is open on any of its ports; `ready`, by default, is
every port answering.

## Only your connections

On 127.0.0.1, a port is open to every account of the machine. errand closes, at once, a connection
that comes from another account: on Linux it reads, in `/proc/net/tcp`, which uid opened it. A tunnel
of yours ( `ssh -L`, `errand serve connect` ) is yours, and passes. `keeper.log` notes each one closed.

```python
errand.Service( ..., others = True )      # every account of the machine may connect
```

`--others` on the command line. Elsewhere ( macOS, Windows ) errand cannot tell, and relays every
connection; the server's own access control is then the protection.

The server's side is not guarded this way: another account that finds it connects to the server
directly. It changes at each start, unless fixed. A server that can listen on a Unix socket, or run
in a network namespace of its own, closes that door too; errand does not do it for you yet.

## Ollama, from start to answer

Clients talk to the **announced** port ( `11435` here, or the one errand chose and kept ), never to
`{port}`: that is the server's side, and changes at each start.

```bash
$ errand serve ollama
ollama  http://127.0.0.1:11435  ( warm )

$ curl -s http://127.0.0.1:11435/api/generate \
       -d '{ "model": "qwen3:14b", "prompt": "Why is the sky blue?", "stream": false }'
{"model":"qwen3:14b","response":"Sunlight scatters off air molecules...", ...}
```

Without a `port =`, errand chooses one the first time and keeps it. `--url` prints only the address,
for a script, and starts the server if need be:

```bash
export OLLAMA_HOST=$( errand serve ollama --url )     # http://127.0.0.1:41873, the same at each start
ollama run qwen3:14b "Why is the sky blue?"            # the ollama command line is a client too
```

From Python, with the `ollama` package or anything that speaks HTTP:

```python
import subprocess, ollama

url = subprocess.check_output( [ "errand", "serve", "ollama", "--url" ], text = True ).strip()
client = ollama.Client( host = url )
print( client.generate( model = "qwen3:14b", prompt = "Why is the sky blue?" )[ "response" ] )
```

From your laptop, through ssh, to the same announced port:

```bash
ssh -N -L 11435:127.0.0.1:11435 lmo &      # once; then http://127.0.0.1:11435 here
ssh lmo errand serve ollama --ensure       # started if need be ( or `connect`, below )
```

What follows, on lmo's card:

```text
waiting      the card is held by a computation: the claim waits its turn, a request waits with it
starting     ollama serve, until its port answers ( a few seconds of GPU discovery )
in use       a request is open: the claim is firm
busy         no request open, a model still loaded ( OLLAMA_KEEP_ALIVE, 5 min by default )
warm         nothing loaded: a computation that needs the card evicts it, in about a second
stopped      after `idle` warm, or evicted
```

`OLLAMA_KEEP_ALIVE` sets how long a model stays loaded after its last request, and so how long the
server stays `busy`; `idle` counts after that. Point `OLLAMA_MODELS` at the models already pulled
( `/usr/share/ollama/.ollama/models` for a system install ) to use them without a copy.

## How errand sees that it is used

Every connection goes through the keeper: errand listens on the announced port and relays each
connection to the server. So it counts the open connections itself, on every system.

- **A connection open** means used, silent or not: a server that thinks for an hour before
  answering is not abandoned.
- **The probe saying busy** means used, with no connection: Ollama with a model loaded. `busy` is a
  function of the port ( `errand.http_json( path, predicate )` for a JSON endpoint ) or `--busy-if`, a
  shell command that exits 0 when busy. **A probe that fails or does not answer counts as busy**: a
  saturated server is in the middle of something.
- Neither: the `idle` clock runs, and starts again from zero at the next connection.

Throughput is never looked at. A client that keeps a connection open for nothing ( an HTTP
keep-alive ) keeps the server longer: the risk is taken on that side, never killing a computation.

## Waiting for its share

A service that waits for a card waits in the queue like any run, in order: the queue is first come,
first served, for everybody. Meanwhile its port is already open: a connection that arrives is
accepted and **waits**, then is relayed once the server answers. The keeper gives up the wait when
nobody waits for it any more ( no connection, no `errand serve` waiting ) for `idle`.

## It stops

- after `idle` without connection nor busy;
- warm, when a computation needs its share ( `errand queue` shows it `kept warm: gives way` );
- with `errand serve stop NAME`, or Ctrl-C under `errand serve -f`;
- when the server ends by itself. It is not restarted: the next `errand serve` starts it again.

It is stopped as everything errand starts: INT, then TERM, then KILL after `grace` ( 10 s ), on its
whole process group. Then its claim is released.

## Through ssh: connect

```bash
errand serve connect ollama
```

ensures the service, then relays this process's stdin and stdout to it ( `connect ollama PORT` for
another port than the first ). It is what a key in
`authorized_keys` forces, for a tunnel that starts the server when it is used:

```text
command="errand serve connect ollama",no-pty ssh-ed25519 AAAA… boucles@laptop
```

## From here: forward

```bash
errand serve forward ollama --host lmo            # or --env E: the machine of that environment
```

prints `http://127.0.0.1:PORT` (`--port N` to choose it). Every connection to that port goes to
the service over there: through the agents' connection that errand already holds, one channel
per connection, with no new ssh login and no tunnel to set up. The first connection starts the
service there, waiting in the queue if needed. As for a page, only a service **declared** on that
machine can be reached, never a port named from here. Ctrl-C stops the forward, not the service:
it stops on its own once idle.

From Python, `errand.serve.forward( target, name )` returns the listening socket, e.g. to put a
service of another machine behind a page.

## Seen

```text
$ errand serve
  ollama           busy       127.0.0.1:11435    1 connection
$ errand status
running   ( on lmo: this machine )
  lmo: service ollama busy  127.0.0.1:11435, 1 connection
$ errand queue
  ollama ( service )  gpus=1, gpu_ram=10G  gpu 0  12 min  pid 4121
```

## errand hold

A claim held for a process that is not a run, for as long as its input stays open:

```bash
errand hold --gpus 1 --gpu-ram 10G -n "my server"
```

prints `granted 0` ( the cards ) once it has it, reads `warm` ( it may give way ) and `busy` ( it may
not ) on its input, prints `evict` when a computation needs the room while it is warm, and releases
when its input closes. `errand serve` is built on the same claim; `hold` is for whoever wants to
drive it themselves.

## A page that asks for a service

A run's page served as it is ( `errand.Static`, see [Steps](./steps) ) can ask for services: a
renderer that draws the current view, a field computed on demand. Each one may run on the machine
the person chooses in the page: here, where the run wrote the directory, or any machine errand
knows ( ADR 0026, 0027 ).

### The package says how a service runs

The code of a service comes from a package installed on the machine, never from the page. The
package ships, beside the code, a file of data, `errand-services.json`, and names its module by an
entry point:

```toml
[project.entry-points."errand.services"]
mytool = "mytool.services"
```

```json
{ "format": 1, "package": { "name": "mytool", "pip": "mytool" },
  "services": {
    "field": { "protocol": 1, "text": "Computes a field of the scene on demand.",
               "version_of": [ "field.py" ],
               "run": [ "{python}", "-m", "mytool.services.field", "--port", "{port}" ], "idle": "5m" } } }
```

- `run` is a list of words. errand resolves its placeholders on the machine that runs it:
  - `{python}`: the Python of the env that has the package;
  - `{file:REL}`: a file of the package, where it is installed there;
  - `{tool:NAME}`: a program found there, or fetched;
  - `{port}`: the port, for the keeper.
- `needs` ( `gpus`, `gpu_kind`, `platforms`, `ram` ) and `tools` say what the machine must have. For
  a tool, the description gives:
  - `look`: where it usually is;
  - `version_from`: where to read its version in files ( `Info.plist`, a directory's name, dpkg,
    snap );
  - `min`: the oldest version that will do;
  - `fetch`: a pinned download per platform ( URL, sha256, the program inside ).
- **The version** of a service is 8 hex digits of a sha256 over its protocol and the files
  `version_of` lists. The producer computes it when it writes a directory, and errand computes the
  same on each machine by reading those files. errand never imports the package.

### The directory says what it asks for

```json
{ "format": 2, "services": {
    "field": { "version": "3fa29c1e", "protocol": 1, "optional": true,
               "package": { "name": "mytool", "version": "1.4" }, "described": { …a copy of the package's entry… } } } }
```

The directory holds names ( `field#3fa29c1e` ) and a copy of the description, which serves only to
propose an installation on a machine that lacks the package. It never runs anything, and the
directory carries no code.

### The page reaches them through its own address

| request | answer |
|---|---|
| `GET .errand/services` | per service: `version`, `on` ( the machine chosen ), `state`, `why`, `store`, `found`, `lines` |
| `GET .errand/machines` | the machines offered, here first, then the run's, then errand's other machines |
| `GET .errand/machines/<M>[?refresh=1]` | what M's agent found, per service ( it reads files and runs nothing ) |
| `POST .errand/services/<name>` `{"on": M}` | the machine chosen for that service, kept per view |
| `POST .errand/copy` `{"on": M}` | the view's files copied into errand's cache on M ( data only ), kept up to date |
| `POST .errand/machines/<M>/paths` `{"tool", "path"}` | a place for M's agent to look for a tool |
| `.errand/svc/<name>/<path>` | relayed to `name#version` on the machine chosen ( any method, a body, a WebSocket ), started there first if needed |

The states are:

- `running` or `ready`: declared at this version;
- `installable`: the lines below make it ready;
- `unknown`: a version could not be read from files;
- `unavailable`: greyed, with the reason;
- `wrong version` or `unverified`: see below;
- `unreachable`: the machine's agent did not answer.

The relayed request carries **`X-Errand-Root`**: the directory as the service's machine sees it
( the original, a shared file system, or errand's copy ), percent-encoded.

**Only what both sides name runs.** A page reaches a service only if its `services.json` lists
`name#version` *and* the machine declares exactly that. Nothing a page sends declares a command.

### The lines to type

For a service that is not ready on a machine, errand composes the lines from what that machine has,
and the page shows them. Nothing is run until a person types them:

```text
$ errand serve look --on lmo runs/foam.sviz
lmo  linux-x86_64  RTX 2080 Ti   the store: original /home/hugo/runs/foam.sviz
  blender#3fa29c1e         installable
      · /usr/bin/blender · 4.1.1 ( dpkg ( package blender ) ) — this service needs 5.0 or later
      · sdot 2026.11.3 in /home/hugo/miniforge3/envs/lmo-jax — provides blender#3fa29c1e, the version this store asks for
      # blender 5.2.2 from download.blender.org into errand's cache on lmo ( checked against its sha256 8409…a168 ); nothing in it is run
      errand serve fetch --on lmo https://download.blender.org/…/blender-5.2.2-linux-x64.tar.xz#sha256=8409…
      # the service blender#3fa29c1e, as sdot 2026.11.3 in lmo-jax describes it, GPU 1, stopped after 10m unused
      errand serve install --on lmo --gpus 1 --idle 10m blender#3fa29c1e -- /home/hugo/.cache/errand/tools/8409…/unpacked/… -b …
```

- `errand serve fetch --on M URL#sha256=H`: a file, checked against its hash and kept by its
  contents. `fetch pip:PKG==V` installs a package into a new env of errand's
  ( `--into ENV` for an existing one ). A source outside `errand.sources` ( PyPI, conda-forge,
  download.blender.org by default; change the list in `services.py` ) is refused unless you repeat
  it with `--source URL`.
- `errand serve install --on M NAME#VERSION -- WORDS` declares the service as typed, into
  `services-installed.json` on M. It records the package that provides that version, and that
  package's files are checked again before every start. If they changed, the state is
  `wrong version` and the service does not start. With no package behind it, the declaration is
  `unverified`. Without `-- WORDS`, the command is composed from the package there, shown, and
  asked.
- `errand serve probe --on M -- PROG --version` runs a program once to read a version that no file
  says. Nothing else runs a program to look at it.

`errand serve` and `errand status` list every declared service, `ready` before it ever ran.

**Without errand** ( the directory under `python -m http.server`, or sent to someone ):
`.errand/services` answers 404, and the page works on its files alone. By convention, a page then
takes a service's address from its URL ( `?svc.field=http://127.0.0.1:9000` ), and a service
started by hand is told its directory with `--root DIR`, since no relay adds `X-Errand-Root`. Such
a service answers CORS for `127.0.0.1` and `localhost`, because the page is on another port.

- **The queue is per user and per machine.** A server started under another account ( a systemd
  service ) is not seen, and its share of the card is not counted. Nor is a run started with
  `--no-queue`: it takes the card without asking, and a service that loads a model next to it may
  find the card full.
- **The server's side of a port is open to every account of the machine**, and so is the announced
  side outside Linux ( see [Only your connections](#only-your-connections) ).
- **From another machine**: `errand serve forward` ( above ), or `errand serve connect` behind an ssh key.

## Next

[Sharing a machine](./machine) · [Agents](./agents) · [What is running](./status)
