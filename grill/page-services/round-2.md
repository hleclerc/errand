# Services d'une page, par machine : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Décisions du tour 1 : [decisions.md](decisions.md). Ce tour suit tes réponses : le code copié dans le store (Q2),
toutes les machines (Q4), pas de `--version` (Q6), plus de `spec.json` (Q7), les paquets proposés (Q8).

---

## Q9 : Le code du service copié dans le `.sviz` : avec quelle confiance ?

Ton idée : copier le fichier du service dans le store, pour ne pas dépendre de l'installation. C'est surtout vrai pour
`blender` : `blender.py` tourne sous le Python de Blender avec numpy seul, **sans sdot**. Une machine qui a Blender mais
pas sdot (un Mac quelconque, un collègue) pourrait faire les rendus. Pour `sdot.ao` / `sdot.region`, ça n'aide pas :
ils importent sdot.

Mais un code copié dans le store, c'est exactement ce qu'un store malhonnête peut fabriquer (le hash ne prouve rien :
le faussaire le recalcule). Il faut donc deux niveaux, visibles :

- **garanti par un paquet** : un paquet installé sur la machine M (ou sur la machine qui sert la page) fournit
  le même `name#version` → la description et le code viennent du paquet, rien du store n'est exécuté ;
- **venu du store** : aucun paquet ne le garantit → la page le dit en clair (« ce code vient du store, écrit par …, aucun
  paquet de lmo ne le garantit ») ; la ligne copie le fichier dans le cache d'errand sur M, par son contenu
  (`errand serve fetch --on lmo <vue>/services/blender.py#sha256=…`), puis l'installation pointe vers cette copie. La
  déclaration ne dépend plus ni du store ni de sdot ; la personne a consenti à *ce* contenu-là, comme pour un Blender
  téléchargé.

Le store porte alors `services/<name>/…` (les fichiers autonomes du service) et la description de chaque service
(la copie de l'entrée de `errand-services.json`), seulement quand le producteur dit que le service est **autonome**.

➡️ **Recommandé :** les deux niveaux ; le store embarque les fichiers des services marqués autonomes (`blender`) ; le
niveau « venu du store » se voit dans la page, dans la ligne (commentaire) et dans `errand status` (`from store`).

**Réponse :**

On ne s'est pas compris. Je parlais uniquement du fichier déclaratif json. Le code doit idéalement venir de dépôts, ou éventuellement d'une install locale (`pip -e` par exemple)

---

## Q10 : Une machine qui n'a pas de copie du store

Toutes les machines sont proposées (Q4). Mais le service lit le store par son chemin (`X-Errand-Root`) : sur n14, il n'y
a peut-être pas de copie.

- **(a) errand y porte le store** quand on choisit n14 : copie dans une zone de cache d'errand sur n14 (par vue,
  tenue à jour comme une vue ramenée, ADR 0017), taille montrée avant ; `X-Errand-Root` désigne cette copie ;
- **(b) le service lit le store à travers le relais** (`X-Errand-Root` devient une URL vers la page) : plus de copie,
  mais chaque service doit lire en HTTP, et un gros store passe par le tunnel à chaque requête ;
- **(c) griser n14** (« pas de copie du store ») : contraire à « toutes les machines ».

➡️ **Recommandé :** (a). La disponibilité du store est un critère du tri (Q14) : une machine qui l'a (ici, la machine du
run, un FS partagé) passe avant une machine où il faut le porter, et la taille à porter est dite.

**Réponse :**

Il faut proposer d'y copier le contenu.

---

## Q11 : Lire une version sans rien exécuter

Le paquet décrit, pour chaque outil, **où lire sa version** dans des fichiers, par plateforme :

- `Info.plist` (`CFBundleShortVersionString`) pour `Blender.app` ;
- le nom du répertoire (`blender-(\d+\.\d+\.\d+)-linux`) pour une archive dépliée, et pour le cache d'errand (la
  version y est connue : on l'a téléchargée) ;
- la base dpkg (`/var/lib/dpkg/status`, paquet `blender`) pour un Blender d'apt ; `snap` : `/snap/blender/current/meta/snap.yaml` ;
- `*.dist-info/METADATA` pour un paquet Python.

Si aucune règle ne s'applique : « version inconnue (`/opt/foo/blender`) ». La page propose alors une ligne explicite,
que la personne tape :

```
errand serve probe --on lmo -- /opt/foo/blender --version     # exécute ce programme avec --version, une fois
```

Le résultat est gardé par (chemin, taille, date) ; *Refresh* relit les fichiers mais ne réexécute jamais rien.

➡️ **Recommandé :** tel quel ; l'utilisateur peut aussi donner la version à la main avec le chemin
(`--path blender=/opt/foo/blender@5.2.2`).

**Réponse :**

---

## Q12 : Sans `spec.json`, comment le gardien sait quoi lancer

Aujourd'hui `ensure` écrit `spec.json` parce que le gardien est un autre processus et que la déclaration peut venir
d'ailleurs que du fichier de l'utilisateur : des fichiers d'un **projet** (`errand-*.py`, selon le `cwd`) ou de la
**ligne de commande** (`errand serve --gpus 1 -- ollama serve`, ad hoc).

Proposition : **toute** source passe par une déclaration lisible par nom :

- `services.py` et `services-installed.json` : le gardien relit par nom ;
- ad hoc (ligne de commande) : écrit dans `services-installed.json` avec `"adhoc": true`, retiré quand il s'arrête ;
- projet : relu depuis le projet (le chemin du projet gardé dans `state.json`, qui reste : pid, port, état).

Alors `errand status` = l'union des déclarations, plus les états.

➡️ **Recommandé :** tel quel ; `spec.json` disparaît, `state.json` reste.

**Réponse :**

---

## Q13 : Installer le paquet qui manque

`errand-services.json` dit comment avoir le paquet (`"package": {"pip": "sdot==2026.11.3", "index": "https://pypi.org/simple"}`,
ou un canal conda). Où errand propose-t-il de l'installer ?

- **(a) un env dédié, fait par errand** : `errand-svc-sdot-2026.11.3`, un venv uv (errand sait déjà faire : `layers.Uv`,
  build records ADR 0004), qui ne touche à aucun autre env ;
- **(b) dans un env existant**, choisi dans la page parmi les envs de la machine (`lmo-jax`) ;
- les deux : (a) par défaut, (b) proposé quand un env existant a déjà une partie des dépendances (jax, numpy…).

Et la description qu'errand utilise pour proposer ces lignes sur une machine qui n'a pas le paquet : celle d'un paquet
installé **ici** (de confiance), sinon celle copiée dans le store (niveau « venu du store », Q9, dit en clair).

➡️ **Recommandé :** (a) par défaut, (b) en choix ; description d'ici d'abord, du store sinon, dite.

**Réponse :**

---

## Q14 : Les besoins qu'un service peut exprimer, et le tri

Dans `errand-services.json`, par service, des besoins **déclaratifs** :

- `platforms` (`macos-arm64`, `linux-x86_64`…) ;
- `gpus` (nombre), `gpu_ram`, `gpu_kind` (`cuda` / `metal` / any), `ram` ;
- `tools` (`blender >= 5.0`), `package` (`sdot`) — satisfaits, installables, ou impossibles ;
- le store lui-même (Q10).

Tri des machines dans le menu, par service :

1. **prêt** (déclaré à la bonne version) — ici d'abord ;
2. **installable** (tous les besoins satisfaits ou satisfiables par des lignes) — ici d'abord, puis le moins de
   lignes / le moins à porter ;
3. **grisé** avec la raison (« pas de carte », « linux-arm64 : pas de Blender pour cette plateforme »).

➡️ **Recommandé :** ces besoins et ce tri ; un service sans besoin particulier : ici d'abord, les autres dans l'ordre
des lieux d'errand.

**Réponse :**

---
