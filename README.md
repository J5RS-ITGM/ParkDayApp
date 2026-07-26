# Park Day — family Disney trip planner (v4.0)

Self-contained PWA + tiny sync backend. Three families, one live plan.

## Layout
- `index.html`, `manifest.json`, `sw.js`, icons → static app, served from
  `/home/j5rescue/htdocs/j5rescue.com/FamilyFunWeek/`
- `sync-server/` → FastAPI + SQLite sync service (Docker, loopback :8787),
  reverse-proxied at `/FamilyFunWeek/api/`

## Deploy (store box)
```
deploy-parkday                      # static app: pull + copy + chown
cd /opt/parkday/sync-server
docker compose up -d --build        # sync backend
```
nginx location block: see `sync-server/nginx-snippet.txt` (CloudPanel vhost editor).

## Push alerts (v5.0)
Bell (🔔) on ride cards: pick a wait threshold, get one push when it drops
below (max one per ride per hour). Server polls ThemeParks.wiki every 3 min.
Setup: generate VAPID keys (docker compose run --rm parkday-sync python gen_vapid.py),
paste into docker-compose.yml, docker compose up -d --build. iOS needs the
installed app (iOS 16.4+); notifications permission prompted on first bell.

## Password
Client gate and server share the same secret: SHA-256 of the family password.
- Client: `GATE_HASH` in index.html
- Server: `PARKDAY_KEY` in sync-server/docker-compose.yml
Change both together, then `docker compose up -d` to restart.

## Sync model
Whole plan stored server-side as one blob with a rev counter. Clients pull
every 20 s + on focus, push 1.5 s after edits. Merge is per-entity
(kid/day/list): newest edit wins, deletions tombstoned 45 days, a newer
edit revives a deleted entity. Offline edits queue and reconcile on
reconnect. Conflicting edits to the SAME day/list/kid: last writer wins.
