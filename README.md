# GT Recipe Book

The app contains **no recipe data at all** and starts empty. Add recipes with the New button, or bring
existing ones in with **Backup & data > Import backup** (a file exported from this app).

## Start it
You need Python 3 (nothing else to install).
- **Windows:** double-click `start.bat`
- **Mac / Linux:** run `./start.sh` (or `python3 server.py`)

It opens the app in your browser and prints two addresses:
- `http://localhost:8080` on this computer
- `http://192.168.x.x:8080` for your phone (same Wi-Fi). Type it into the phone's browser, then
  Add to Home Screen (iPhone: Share menu, Android: menu > Install app).

Recipes are saved in `data/recipes.json` (created on the first save) and your PC and phone share them.
Keep the server running while you use the app. Anyone on your Wi-Fi who opens the address can edit;
run `python3 server.py --local` to allow only this computer. Other options: `--port 9000`, `--no-browser`.

## Ids: why renames and imports don't create duplicates
Every recipe and ingredient gets a permanent random id (a UUID) when it is created, and keeps it forever.
The name is only a label. Recipes refer to ingredients and preps by id, and imports match items by id,
never by name. So:
- Renaming an item changes its label on every device after the next sync/import, not its identity.
- Importing the same backup twice, or backups from different devices that started from the same data,
  adds nothing new.
- A backup file carries its ids, so two devices that both import the same backup hold the same items.

## Import = merge (nothing is wiped)
**Import backup** merges a file into what is already there:
- Items that only exist here are kept, always.
- Items that only exist in the file are added.
- Items in both: the one edited most recently wins (every change is timestamped).
- Deleting an item records the deletion, so it also reaches other devices when you import. If a recipe
  still uses an item that was deleted elsewhere, the item is kept so nothing breaks.
- If two devices separately create items with the same name, they are different items (different ids).
  Both are kept and the app tells you how many names are now doubled, so you can rename or delete one.

Moving recipes between devices that don't share a server: **Export backup** on one, **Import backup** on the other.

## Updating from an older version
Unzip over your existing folder; the zip contains no `data/` folder, so your recipes are never touched.
On first start the app gives every existing recipe and ingredient its permanent id. The id is worked out
from the old name, so the same old item gets the same id on every device and in every old backup, and
importing a new-format backup of the same data afterwards adds no duplicates. The server keeps a copy of the previous file in `data/backups/` first. Backups exported by
older versions can still be imported.

## The data file
- `data/recipes.json` holds `recipes` and `ingredients`. You can edit it while the server runs; changes
  show up in the app within a few seconds. If you break the JSON, the server keeps the last good copy
  until you fix it, and refuses to start (without touching the file) if it is broken at launch.
- Saves are atomic, and `data/backups/` keeps timestamped copies (one every 10 minutes while you edit,
  plus one before every import; the last 30 are kept). To roll back, copy a backup over `data/recipes.json`.
- Two people editing the same recipe at the same moment: the last save wins.

## Without the server (optional)
If the folder is put on a static web host (GitHub Pages, Netlify, ...), or `index.html` is opened directly,
the app keeps recipes in that browser only (a note in the app says so) and can be installed and used
offline. Devices don't sync in this mode; use Export/Import to move recipes between them. On iPhone,
install to the home screen and export a backup now and then, because Safari can clear data for sites
you haven't opened in a while.
