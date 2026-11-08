# État des constructions d'errand : décisions

- **Lieu du record**: dans `.errand/` de la machine qui porte l'artefact, une clé par artefact et non par env ; les `env-*.yaml` du Mac sont abandonnés. Éviter le fouillis et les collisions de noms ( layout : tour 2 ).
- **Détection**: la solution doit être universelle, pas propre à Apptainer ; les sommes de contrôle sont acceptées quand elles ne coûtent pas trop ( forme exacte : tour 2 ).
- **Adoption**: le record dit `origin: adopted`, avec la date et l'empreinte vue comme base de comparaison ; `errand envs` affiche `adopted`.
- **Build à côté**: construire dans un `.new`, renommer après succès, effacer un `.new` raté. À généraliser aux autres artefacts si possible ( tour 2 ).
- **Échec du build**: le run s'arrête, en disant qu'un artefact existe, de quand il date, et que `--no-setup` l'utilise.
- **Nouvel essai**: à chaque run, même si rien n'a changé.
- **Traces**: un yaml d'état et le dernier log par artefact, réécrits à chaque tentative, pas d'historique.
- **Nom de ce qui se construit à côté ( Q8 )**: pas de supposition sur les extensions ; les layers disent les noms exacts à ne pas toucher au `rsync`. Le `.sif` n'est pas à rapatrier ni à synchroniser systématiquement ( détails : tour 3 ).
- **Détection ( Q9 )**: empreinte des entrées + tampon de l'artefact ( `stat`, id d'image, `conda-meta/history`… ). Pas de record : adoption ; tampon différent : record annulé, adoption ; empreinte différente : stale ; sinon ok.
- **Adoption suspecte ( Q10 )**: entrée plus récente que l'artefact : on reconstruit ce qui se construit à côté, on avertit pour le reste.
- **Build à côté ( Q11 )**: Apptainer ; Docker et Windows l'ont déjà ; les envs ( conda, venv, uv ) restent en place, avec l'échec visible dans le record.
- **Image précédente ( Q12 )**: une seule, gardée après un succès, écrasée au build suivant.
- **Rangement ( Q13 )**: `.errand/builds/<couche>-<nom>-<hash>.yaml` et `.log`, un fichier par artefact, hash de l'identité complète.
- **Exclusions ( Q14-Q16 )**: union des noms exacts de tous les envs du projet, ancrés à la racine ; `*.sif` retiré de `RSYNC_EXCLUDES` ; `push` affiche ce qu'il efface là-bas.
- **Suite ( Q17 )**: ADR 0004, puis implémentation, sans commit.
- **Écart à la règle de Q9, à l'implémentation**: l'empreinte passe avant le tampon ; sinon un `__pycache__` dans `site-packages` transformerait un nouveau requirement en adoption qui ne l'installe pas.
