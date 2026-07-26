# Park Day — Disney Trip Planner (PWA)

Family trip planner for Walt Disney World. Single-file app, no build step, no backend.

## Features
- Kid profiles with heights (inches) — every ride card shows who clears the height requirement
- Allergy profiles — dining cards flag family allergens; honest "no data" badge where unknown
- Day planner per park with meal times, filters, and reorderable items
- "Foods to try" lists with restaurant links; linked items auto-surface on the matching park day
- Live wait times + full ride/restaurant roster sync via ThemeParks.wiki (free, no key)
- Offline-capable PWA (service worker), installable on iOS/Android

## Files
- `index.html` — the entire app (data, styles, logic)
- `manifest.json`, `sw.js`, `icon.svg`, `icon-512.png`, `apple-touch-icon.png` — PWA shell

## Deploy
Static hosting only. Either:
- Copy the folder to a web root, e.g. `htdocs/j5rescue.com/parkday/` → https://j5rescue.com/parkday/
- Or connect the repo to Cloudflare Pages (build command: none, output dir: /)

## Data & privacy
All user data (kids, plans, lists) is stored in the browser's localStorage on each device.
Nothing is sent to any server. Deleting the hosted files destroys no one's data.

## Removal
Delete the folder (or the Pages project). No DB, no services, no cron.
