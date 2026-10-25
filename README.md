# Tournament Software — Railway

Flask tournament manager based on v11. Existing formats, match scoring, pairing,
PDF/Excel exports and JSON tournament imports remain available to the administrator.

## Access

- **Administrator:** creates and edits tournaments, records scores, imports/exports,
  manages read-only accounts and publishes individual player links.
- **Viewer account:** sees the tournament archive, schedules, results, group tables,
  brackets and rankings. All editing endpoints are denied on the server.
- **Players:** no login; open `/players/<random-token>` for a single published
  tournament. No archive listing, management controls, JSON backup or account access.
  Pages refresh every 30 seconds while visible, retaining search and scroll position.
  Disable publication to revoke access; enabling again generates a new link.

All stored tournaments are visible to signed-in accounts, including ongoing events.
The schedule retains v11 match order and court assignments; it does not invent
clock times. Existing v11 double-elimination and Swiss generation behavior is retained.

## Railway deployment

1. Create a project and connect `klimczaksc/tournament-software`, branch `main`.
   Build from the repository root; Dockerfile handles the existing subdirectory.
2. Attach a persistent volume at **/data**. Use **one replica** for this SQLite app.
   The database (including hashed passwords) and uploaded logos are on this volume.
3. Set environment variables:
   - `DATA_DIR=/data`
   - `SECRET_KEY`: a randomly generated secret (at least 32 bytes).
   - `SETUP_TOKEN`: another independent, randomly generated secret.
   - `COOKIE_SECURE=1`
   Never commit these values to GitHub.
4. Deploy, check `/health`, then generate a Railway public domain.
5. Open `https://YOUR-DOMAIN/setup?token=YOUR-SETUP-TOKEN` privately. Create the
   first administrator (password minimum 12 characters). This endpoint permanently
   closes once the first administrator exists; remove SETUP_TOKEN afterwards.
6. Log in at `/login`. Use **Konta** to create read-only accounts or deactivate
   them/reset their passwords. Deactivation and resets invalidate existing sessions.
7. In a tournament, enable **Link dla graczy**, save, and copy the displayed URL.

The supplied ZIP contains **no tournament database or recorded events**. To migrate
old events, export each tournament as JSON from the old app and use **Import JSON**
as administrator. Alternatively migrate an existing v11 `tournament.db` and uploads
onto the volume before first start; startup adds the accounts table without deleting
existing tournaments. Imported JSON events are private until explicitly published.

## Operations

Set up Railway volume backups in the dashboard; JSON exports cover tournaments,
not user accounts or logos. Keep SECRET_KEY stable across restarts. SQLite requires
a single service replica. Rate limits use process memory with a single Gunicorn
worker; counters reset on restart. Sessions expire after 12 hours. CSRF protection
applies to all forms and JSON writes. TLS is supplied by the Railway domain.

## Local development

```
cd tournament_software_world_champs_v11
python -m pip install -r requirements.txt
# Set SETUP_TOKEN in your shell before starting.
python app.py
```

Local port: 5069. DATA_DIR defaults to the app directory; a local session secret
is generated when SECRET_KEY is absent. Keep databases, uploads and secrets out
of git. For tests: `pip install pytest && pytest test_online.py`.
