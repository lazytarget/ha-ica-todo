# ha-ica-todo

ICA integration for Home assistant. 
Forked from https://github.com/dennisgranasen/ha-ica-todo. But very much rewritten since...

NOTE: Currently under development and might be unstable!


## User Stories

- [x] Regex pattern matching for specifying Quantity and Unit
- [x] Assign due date based on current offer for items synced from ICA
- [x] Assign appropriate ArticleGroupId. Using existing values in /common, /baseitems, or do a local or API lookup
- [x] Get current offers in favorite stores. If any "productEan" matches one of my favorite products "baseitems", then automatically add it, with a due date => Can be done by writing an automation and listening on ica_event

**Integration**
- [x] Shopping list picker for which lists to track
- [ ] Implement services and events to use for automations (notifications, etc.)
- [x] Translate strings [sv, en]
- [x] Implement config flows step for Reauth / refresh tokens
- [x] Update config entry with token, if doing full auth
- [x] Refresh login when expiry was passed
- [x] Refresh login when 401 was returned during fetching of data
- [x] Invoke a new login if an attempted "Refresh login", failed
- [x] Implement Blueprint automation for tracking new offers

**Shopping lists**
- [x] Categorize added items into the correct article group!
- [ ] Time limited offers to be automatically added (if exists under favorites)
- [ ] Checking off items should sync between store-lists (including time limited offers)
- [ ] Adding items to Trello checklist should create them in the "Master"-list
- [ ] Adding items to a shopping list  should sync them to Trello checklist too?
- [ ] User should use the "store"-list when shopping, which should contain existing offers for that store, and the wanted items from "Master"-list
- [ ] Adding items to the "Master"-list should calculate the sum of quantities and update accordingly
- [x] Implement the different `CONFLICT_MODES`
- [ ] Allow for (scheduled) notification, when favorite item(s) are on discount/offer
- [ ] Avoid getting all shopping lists before updating individual lists. Since integration has config on the ID's. Only fetch during config_flow
- [ ] Check if the 'Ica To-Go app' can be reverse engineered. That way we could possibly scan ONCE, for both for ICA purchase and for Grocy tracking.

    ```
    Seems to authicate via ims.icagruppen.se, via Mobilt BankID. Which will probably unlock the door. Not sure how much to fool around here since everything is tracable.
    App gets current offers for the store. But starting to scan items will add them to the cart. Which kind of commits that you want to purchase them...
    Not sure what to benefit whit this app as of now
    ```

**Barcode/QR/Bower**
- [ ] Check API possibilities for scanning/shopping items with the phone?
- [ ] Check if can integrate with the 'Bower recycling app'

**Recipes**
- [ ] Able to export Ica recipe into Trello
- [ ] Find recipes that match ingredients that are currently on offer (or in a shopping list)
- [ ] Service to list recipes possible with the current pantry inventory

**Docs**
- [x] Document installation/configuration (see below)
- [ ] Document use-case examples
- [ ] Document Automation examples


---

# Documentation

## Overview

Custom integration (`domain: ica`, cloud polling) that connects a Home Assistant instance to an ICA (Sweden) account. It exposes ICA shopping lists as `todo` entities and keeps them in sync with ICA, categorizing items, attaching offers and recipes, and firing events when new offers appear.

## Installation

1. **HACS**: add `https://github.com/LazyTarget/ha-ica-todo` as a custom repository (type *Integration*), install "ICA shopping list", restart Home Assistant.
   **Manual**: copy `custom_components/ica` into your HA `config/custom_components/` folder and restart.
2. Go to *Settings → Devices & services → Add integration → ICA*.

## Configuration

Set up via the UI (config flow):

| Field | Description |
|---|---|
| Personal ID number | 10 or 12 digits, no hyphen |
| ICA PIN code | 4-6 digits |
| Update interval | Minutes between fetches from ICA (default 5) |

Authentication tokens are stored in the config entry and refreshed automatically (re-login on expiry or HTTP 401). If the login stops working (e.g. a changed PIN), Home Assistant shows a *Reconfigure* notice where you enter the new PIN.

After setup, *Configure* (options) lets you change:

| Option | Description |
|---|---|
| Update interval | Minutes between fetches from ICA |
| JSON data in description | Show extra item data (quantity, offer, EAN, ...) as JSON in each item's description |
| Shopping lists | Which ICA shopping lists to track as to-do lists |

Saving the options reloads the integration; changing the tracked lists also refetches them.

Cached ICA data is stored in `.storage/ica.*.json` and is deleted when the integration is removed. Neither the cache file names nor the logs contain your personal ID number, PIN or tokens.

## Entities

All entities belong to one *ICA* device per account.

- One `todo` entity per tracked shopping list. Items are categorized into ICA article groups; due dates are derived from current offers. Each list entity has the attributes `offline_id` (the list's ICA offline ID), `config_entry_id` and `comment` (the list comment in ICA, if any). The favourites entity has no such attributes.
- `todo.ica_favorite_articles`: your ICA base items (favorites).

## Services

| Service | Purpose |
|---|---|
| `ica.refresh_all` | Force a refresh of all cached data |
| `ica.get_recipe` | Fetch a recipe by `recipe_id` (returns response) |
| `ica.lookup_product` | Look up a product by barcode/EAN (returns response) |
| `ica.get_baseitems` | List base items (favorites) for an ICA account (returns response) |
| `ica.add_baseitem` | Add a base item by name or barcode |
| `ica.create_shopping_list` | Create a list on an ICA account (`title`, optional `comment`; `track` adds it as a todo entity and reloads the integration) |
| `ica.delete_shopping_list` | Permanently delete a list from your ICA account |
| `ica.upsert_shopping_list` | Add/update `rows` (plain text or JSON objects) in a list entity |
| `ica.add_offers_to_shopping_list` | Add offers by `offer_ids` to a list entity |

`upsert_shopping_list` and `add_offers_to_shopping_list` take a `conflict_mode` for items that already exist:

- `APPEND`: add as a new row (default)
- `MERGE`: combine with the existing row, summing quantities (with unit conversion, e.g. kg/g, l/dl, defaulting to `st`) and matching on normalized product name / offline id
- `IGNORE`: leave the existing row untouched

Example JSON row: `{"productName": "Banan", "productEan": "4011800420710", "quantity": 2, "unit": "st"}`

## Events

`ica_new_offers` is fired when new offers are detected in your favorite stores. Use it as an automation trigger.

`ica_lists_changed` is fired after `ica.create_shopping_list` (with `track`) or `ica.delete_shopping_list` has reloaded the integration and the todo entities are registered. Also fired immediately for an untracked create. Payload:

```json
{"config_entry_id": "...", "created": ["<offline_id>"], "deleted": [], "entities": {"<offline_id>": "todo.ica_..."}}
```

`entities` maps created offline IDs to entity IDs (missing if the reload failed or the list is not tracked).

`ica_list_items_changed` is fired when a refresh finds added, removed or changed rows in a list compared with the previous data (e.g. items added in the ICA app). Not fired on the first load of a list. Payload:

```json
{"entity_id": "todo.ica_...", "offline_id": "...", "added": [{"uid": "...", "summary": "..."}], "removed": ["<uid>"], "changed": [{"uid": "...", "summary": "...", "changed_props": ["quantity"]}]}
```

## Upgrading from v0.10 or earlier

The config entry is migrated automatically on first start:

- Update interval, tracked lists and the JSON description setting move to the options.
- Cache files are renamed so they no longer contain your personal ID number, and debug dumps (`ica.offers_changed*`, `ica.products_changed*`) are deleted.
- Entities are grouped under an *ICA* device. Existing entity IDs are kept.

Requires Home Assistant 2025.1 or later.

## Blueprint

`custom_components/ica/blueprints/ica_track_new_offers.yaml` triggers on `ica_new_offers`, filters by store/offer/article name, matches your favorite items (name or EAN), and can notify or add to a shopping list.

## Development

- Layout: `coordinator.py` (polling, caching, offer events), `todo.py` (entities + list services), `services.py` (global services), `utils.py` (merge, unit conversion, name normalization, timestamps), `caching.py` (file cache), `authenticator.py` / `icaapi*.py` / `http_requests.py` (ICA API client), `openfoodfacts.py`, `config_flow.py` (setup, reauth, options).
- Setup: `python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
- Tests: `.venv/bin/pytest` (config/options/reauth flows, migration, entities, services, coordinator, cache and the `utils` helpers; the ICA API is faked in `tests/conftest.py`). CI runs them on every PR.
- Lint: `pre-commit run -a` (ruff check + format, yamllint).
- Releases: Release Drafter builds notes from PR labels; publishing a release triggers `.github/workflows/release.yaml`, which writes the version into `manifest.json` and attaches `ica.zip`.
