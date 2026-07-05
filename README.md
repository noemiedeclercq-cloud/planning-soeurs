# planning-soeurs

Application Flask pour gerer le planning des taches.

## Lancer en local

```bash
pip install -r requirements.txt
python app.py
```

## Configuration Render

Start command recommande:

```bash
gunicorn app:app
```

Variables d'environnement conseillees:

- `PLANNING_PASSWORD`: active l'ecran de connexion avec ce mot de passe.
- `SECRET_KEY`: cle secrete Flask pour les sessions.

Base de donnees:

- En local, l'app utilise `planning.db` dans le dossier du projet.
- Sur Render, l'app utilise `/var/data/planning.db`.
- Il faut donc monter un Persistent Disk Render sur `/var/data` pour conserver les donnees entre les redeploiements.
- `DATABASE_PATH` ou `PLANNING_DB_PATH` permet de forcer un chemin SQLite precis.

## Configuration Vercel

Le point d'entree serverless est `api/index.py`, configure par `vercel.json`.

Sur Vercel, la base SQLite est creee dans le dossier temporaire de la fonction. C'est compatible avec l'environnement serverless, mais ce stockage est ephemere entre redeploiements et redemarrages de fonction. Pour une persistance durable, utiliser Render avec disque persistant ou migrer vers une base externe.
