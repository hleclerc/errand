# Steps : round 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Faits vérifiés : chaque cas a sa feuille ( `errand-outputs/…/<run>/`, `output.txt`, `result.yaml` ),
qui revient avec le record ; `$ERRAND_OUT_DIR` n'est donné qu'avec `-o` ; `$ERRAND_PROC_DIR/leaf`
dit déjà à la TUI quelle feuille tourne ( `seen.note` ). `errand.track` existe déjà ( un genre
d'entrée, nombres suivis d'un run à l'autre ) : `step` est **pendant** un run, `track` **entre** les runs.

## Q1 : un seul appel, trois sortes de contenu

```python
errand.step( f"iteration {i}", done = i / n, residual = r, energy = e )
```

- le texte : l'état courant, lisible ( « iteration 41 » ) ;
- `done` : fraction de 0 à 1 → barre et fin estimée ;
- les valeurs nommées ( nombres ) : une **courbe** chacune, dans l'ordre des appels, datée.

Chaque appel est un événement daté ajouté au journal ; le dernier est l'état. Tout est optionnel
( `errand.step( residual = r )` trace sans changer le texte ). Le texte d'avant reste tant qu'on n'en
donne pas d'autre. Shell : `step "iteration 41" done=0.41 residual=3e-7`.

➡️ **Recommandé :** oui, `step( text = None, *, done = None, **values )`, valeurs = nombres seulement.

**Réponse :**

---

## Q2 : les fichiers qui évoluent ( HTML, PNG, … )

Une sortie HTML ou une image que le process réécrit au fil du calcul n'est pas un événement : c'est
un fichier du run. Le process le **désigne** une fois :

```python
errand.view( "convergence.html" )        # relatif à la feuille du run ( ou chemin absolu )
```

et errand le met en tête du détail dans la TUI ( `o` l'ouvre : navigateur pour du HTML, `$PAGER`
sinon ), et `errand run` dit une fois « vue : …/convergence.html » ( cliquable dans les terminaux qui
le font ). La future vue HTML ( session à part, décidée avec la TUI ) l'affichera en direct, rechargée
quand le fichier change.

Alternative : `errand.step( view = "convergence.html" )`, même appel pour tout.

➡️ **Recommandé :** un appel à part, `errand.view( path, title = None )` ; shell `view convergence.html`.
Rien de plus pour l'instant ( pas de serveur, pas de rechargement : c'est la vue HTML ).

**Réponse :**

Oui bien vu. Par contre, il est possible qu'on voit un fichier changé pas terminé... il faudra faire attention à faire un écrasement atomique...

---

## Q3 : où vit le journal

`<feuille>/steps.jsonl`, une ligne par événement :

```json
{"t": 1763220000.12, "text": "iteration 41", "done": 0.41, "residual": 3e-07}
{"t": 1763220000.95, "residual": 2.1e-07}
```

Dans la feuille, il revient avec le record, reste avec le run dans l'historique ( la TUI trace les
courbes d'un run fini ), et disparaît avec lui. Les vues désignées ( Q2 ) y sont aussi :
`{"t": …, "view": "convergence.html"}`.

Le process trouve la feuille par `$ERRAND_STEPS` ( chemin du fichier ), posé par `run_case` pour
chaque cas, avec ou sans agent. Sans cette variable ( process lancé hors errand ) : `step` ne fait
rien et ne lève jamais.

➡️ **Recommandé :** oui, un seul fichier `steps.jsonl` dans la feuille, trouvé par `$ERRAND_STEPS`.

**Réponse :**

---

## Q4 : fréquence

`step` dans une boucle serrée ( 1e6 itérations ) : écrire à chaque appel coûte et fait un journal
énorme. On écrit au plus **10 fois par seconde** ; entre deux écritures on garde le dernier appel
( texte, `done`, dernière valeur de chaque courbe ), écrit au suivant ou à la sortie du process
( `atexit` ) : rien de final n'est perdu, les courbes sont échantillonnées à 10 Hz au plus. Sans
plafond de taille ( ~3 Mo par heure au pire ).

Option : `errand.step( …, every = 0 )` pour tout garder.

➡️ **Recommandé :** 10 Hz au plus, dernier état jamais perdu, pas d'option tant qu'on n'en a pas besoin.

**Réponse :**

---

## Q5 : ce que montre la TUI

- la ligne du process : le texte, ou `▕████▌   ▏ 41 %` quand il y a `done` ;
- le détail : texte, barre + fin estimée ( depuis le premier `done` ), « il y a 3 s » ( un process
  figé se voit ), puis une ligne par courbe : nom, dernière valeur, sparkline `▁▂▃▅▇` des ~60
  derniers points, échelle log quand les valeurs sont positives et couvrent plus de deux décades
  ( un résidu ) ; les vues désignées en tête des fichiers ;
- un run fini de l'historique : les mêmes courbes, lues dans sa feuille.

➡️ **Recommandé :** oui, comme ci-dessus.

**Réponse :**

---

## Q6 : ce que montre `errand run`

Sur un terminal : une ligne en bas, réécrite sur place sous la sortie qui défile,
`⏵ iteration 41 · ▕████▌   ▏ 41 % · 2 min · residual 3.0e-07 ↘`, effacée à la fin du cas.
Hors terminal ( redirigé, CI ) : rien ( le journal est dans le record ). Par ssh / agent : la ligne
remonte avec la sortie.

➡️ **Recommandé :** oui ; et `errand status` ajoute le texte après « running ».

**Réponse :**

---
