# L'onglet runs en arbre : décisions

## Tour 1 ( 2026-11-19 )

- **Arbre**: dossiers du chemin du fichier ( otrec/, sdot-ffi/, … ; un dossier à un seul enfant fusionné ) → fichier → entrée → jeux de paramètres → runs ; chaque niveau repliable.
- **Machine, env**: des colonnes ( runs, et « dernier » au niveau du jeu ), pas un niveau ; un run ramené par `-o` ( là-bas et ici ) compté une fois.
- **Paramètres**: un tableau sous l'entrée, une ligne par jeu distinct, une colonne par paramètre, alignées ; statut, date, durée du dernier, nombre de runs ; tri par en-tête ; une ligne se déplie en ses runs ; les résultats déclarés ( `result.yaml` ) en colonnes aussi. Même jeu = mêmes paramètres ( env et machine n'en font pas partie ). Sans paramètres : les runs directement.
- **Ordre**: la dernière activité d'abord à chaque niveau ; à l'ouverture replié aux dossiers du haut, sauf ce qui tourne ou attend ; « en cours » / « en attente » restent en tête ; replis retenus.
- **Effacer**: « ne garder que le plus récent » ( par jeu et par env ) et « effacer », à chaque niveau ; ce qui part : le dossier du run sur sa machine ( par son agent, à distance ) et sa copie ici ; jamais un run qui tourne ou attend ; confirmation ( combien, où, la place ). **Effacé pour de bon, tout de suite** ( pas de corbeille ) — Hugo : « b. Et il faudra effacer aussi à distance. »
- **TUI**: le même arbre, tableau en colonnes, `s` trie, `d` efface, `D` garde le plus récent, même confirmation.
- **Travail**: ADR 0023 d'abord ; puis le modèle, la page web, la TUI, effacer.

## Tour 2 ( 2026-11-19 )

- **Garder le plus récent**: le plus récent, et aussi le dernier PASS s'il est différent ( par jeu et par env ).
- **Confirmation**: la fenêtre rouge habituelle ( kill, caches ) : combien de runs, quelles machines, la place, « définitif » ; Entrée confirme, Échap annule.
- **Machine injoignable**: effacer ce qui peut l'être ( copies ici, machines joignables ), dire le reste ; ces runs restent listés, marqués ; pas de file d'attente.
