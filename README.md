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

Sur Vercel, l'application doit utiliser une base persistante Turso/libSQL.
Le stockage SQLite temporaire est volontairement refuse sur Vercel pour eviter de demarrer avec une base vide.

Variables Vercel requises:

- `TURSO_DATABASE_URL`
- `TURSO_AUTH_TOKEN`

Alias acceptes:

- `LIBSQL_URL`
- `LIBSQL_AUTH_TOKEN`

Exporter la base depuis Render:

```bash
cp /var/data/planning.db /tmp/planning.db
```

Telecharger ensuite `/tmp/planning.db` depuis le shell Render, puis importer dans Turso:

```bash
python scripts/import_sqlite_to_libsql.py planning.db
```

Verification attendue apres import:

- `sisters = 16`
- `tasks = 60`
- `plans = 4`
