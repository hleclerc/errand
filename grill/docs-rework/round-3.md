# Refonte de la doc errand : round 3, le sommaire

> Laisse **Réponse** vide pour accepter. `?` demande plus de détail. Sinon, écris tes corrections.

Ce round est le sommaire complet, page par page, avec ce qui bouge. Une URL qui change garde une page « This page moved » (le motif déjà utilisé par le site). Je ne touche pas à `layers/slurm.md` ni à l'ADR 0009 (l'autre session) ; je garde les ajouts récents de cette session dans `agents.md` et `layers/windows.md`. Les fichiers `examples/` ne bougent pas.

---

## Q1 : Start

| page | état | contenu |
|---|---|---|
| `index.md` (accueil) | réécrite | accroche C ; avant / après ; trois scénarios (cluster + conteneur, `errand status`, laptop fermé + `attach`) ; « You stay in control » court ; 6 cartes : *Any stack of layers* · *Built from what you declare* · *Files there and back* · *Nothing left behind* · *Close the laptop* · *Warm between commands* ; une ligne « also runs pytest / Catch2 / cargo suites test by test → » |
| `guide/what-is-errand.md` | réécrite | la phrase, l'étymologie, pour qui, *Stop babysitting your runs* (what you stop doing), *You stay in control* (complet), *What it is not* (pas un orchestrateur de prod, pas un scheduler, pas un build system, pas un lanceur de tests), forme d'un projet |
| `guide/installing.md` | retouchée | ton |
| `guide/start.md` → titre *Quickstart* | réécrite | une commande ici ; `errand init` + un env cluster ; `--pull` / `-o` ; `errand status` ; `--batch` et `attach` ; plus de section suites (une ligne + lien) |

➡️ **Recommandé :** OK.

**Réponse :**

---

## Q2 : Places

| page | état |
|---|---|
| `guide/environments.md` | retouchée (ton, titres descriptifs) |
| `guide/layers/index.md` + pages par couche | retouchées ; la liste des couches corrigée : **`Oar`, `Pbs`, `Sge`, `Lsf` n'existent pas dans le code**, je les retire du README et des pages. `slurm.md` intacte |
| `guide/upkeep.md` | retouchée |
| `guide/tags.md` | déplacée en fin de partie, titre *Choosing among environments (tags)*, présentée comme avancée, sans sortir du quickstart ce qui n'y est plus |

➡️ **Recommandé :** OK.

**Réponse :**

---

## Q3 : Running

| page | état |
|---|---|
| `guide/running.md` | réécrite : `errand run <file \| command>`, ses options, `errand shell` ; ce qui concerne `x::y` part dans la partie tests |
| `guide/output.md` → *Results and records* | retouchée : `-o`, `$ERRAND_OUT_DIR`, `--pull`, `also`, l'arbre `errand-outputs/runs/` |
| `guide/detached.md` → *Let it run: --batch and attach* | réécrite ; y entre « Close the laptop » venant d'`agents.md` |
| `guide/matrices.md` → *Several runs: grids* | retouchée : `--grid` sur les envs et les arguments ; ce qui est propre à `Param` part dans *Writing entries* |
| `guide/mpi.md` | retouchée |

➡️ **Recommandé :** OK.

**Réponse :**

---

## Q4 : Nothing left behind (nouvelle partie)

| page | état | contenu |
|---|---|---|
| `guide/status.md` *What is running* | **nouvelle** | `errand status` / `--all` ; ce qui est montré (runs, allocations, VM, zygotes, ce qui attend : `waiting: slurm job … pending`), orphelins et « unowned » ; arrêter : Ctrl-C, `errand agents stop`, `errand vm stop` ; le principe en trois lignes (un agent sur chaque machine garde la trace de ce qu'il lance ; s'il meurt, le suivant arrête ce qu'il avait laissé) |
| `guide/agents.md` *Agents and keeping warm* | réécrite | ce qu'est un agent, hub / direct, keep-alive (démarrage plus rapide, sans chiffre), `Preload`, Ctrl-C à travers les couches, vrai terminal ; la partie `status` part dans `status.md` |
| `guide/machine.md` *Sharing a machine* | retouchée | file par machine, `-x`, `--cpus`, `--gpus`, `errand queue`, `errand wait` |
| Slurm allocations, Windows VMs | liens dans la barre latérale vers `layers/slurm` et `layers/windows` (pas de doublon) |
| `guide/tui.md` *The screen* | **remplacée** par un encart : « being redesigned as a process and machine monitor », rien sur l'ancien écran |

➡️ **Recommandé :** OK.

**Réponse :**

---

## Q5 : Test suites and entries

| page | état |
|---|---|
| `guide/runners/index.md` *Running a suite test by test* | retouchée : `x::y`, quel runner prend quel fichier en une phrase, `-e`, `default_run` ; la section « guessing » réduite |
| `guide/runners/{pytest,catch2,cargo,scripts,writing}.md` | inchangées sauf ton / liens |
| `guide/runners/adopting.md` | **vient de** `tutorials/adopt-a-suite.md` (stub à l'ancienne URL) |
| `guide/declaring-work.md` *Writing entries* | raccourcie, encart « being reworked into a protocol (ADR 0003) », absorbe l'essentiel du tutoriel 4 et `Param` ; `tutorials/first-entry.md` devient un stub |

➡️ **Recommandé :** OK. Pas de réécriture de fond ici (la discussion sur les runners viendra à part).

**Réponse :**

---

## Q6 : Project, Reference, Tutorials, README

- **Project** : `configuration.md`, `storage.md` (retouchées ; `storage` mentionne `~/.cache/errand/ledger`, `alloc`, `vm`, `agents`).
- **Reference** : `cli.md` complétée avec tous les verbes réels (`status`, `agents`, `vm stop`, `queue`, `wait`, `watch`, `forget`, `attach`, `envs`, `setup`, `init`, `list`, `tui`) et les variables `ERRAND_AGENT`, `ERRAND_HUB_KEEP_ALIVE`… ; `python-api.md` (layers vérifiés contre `__all__`) ; `expressions.md`.
- **Tutorials** : 1 *Four environments* · 2 *Numbers over two machines* (ex-3) · 3 **nouveau** *A cluster, a Windows VM, and what is running*, écrit à partir du code, sans exécution réelle (je le signale dans le résumé).
- **README** : ≈ 60 lignes.
- **`docs/README.md`** (notes pour qui maintient le site) : layout mis à jour.

➡️ **Recommandé :** OK.

**Réponse :**

---
