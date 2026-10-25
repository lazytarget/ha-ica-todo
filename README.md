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
- [x] Implement services and events to use for automations (notifications, etc.)
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
| `ica.refresh_shopping_lists` | Fetch the tracked lists from ICA right away (optionally for one `integration`), e.g. to pick up changes made in the ICA app when arriving at the store. Much lighter than `ica.refresh_all` (returns response, optional) |
| `ica.get_offers` | Currently valid offers in the favorite stores, optionally for one `integration`, some `store_ids`, or `favorites_only` (returns response) |
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

`ica_favorite_offers` is fired together with it when new offers match one of your favorite items (base items). Matching is by EAN (ignoring leading zeros), or by name for favorites without an EAN (plural forms are normalized). Payload: `config_entry_id`, `offer_ids` and `offers`.

`ica_lists_changed` is fired after `ica.create_shopping_list` (with `track`) or `ica.delete_shopping_list` has reloaded the integration and the todo entities are registered. Also fired immediately for an untracked create. Payload:

```json
{"config_entry_id": "...", "created": ["<offline_id>"], "deleted": [], "entities": {"<offline_id>": "todo.ica_..."}}
```

`entities` maps created offline IDs to entity IDs (missing if the reload failed or the list is not tracked).

`ica_list_items_changed` is fired when the rows of a tracked list differ from the previous data. Not fired the first time a list is fetched, as every row would count as added. Payload:

```json
{
  "config_entry_id": "...", "entity_id": "todo.ica_...", "offline_id": "...",
  "shopping_list_name": "...", "origin": "ica",
  "added": [{"uid": "...", "summary": "Mjölk", "item": {"...": "full ICA row"}}],
  "removed": [{"uid": "...", "summary": "Mjölk", "item": {}}],
  "changed": [{"uid": "...", "summary": "Mjölk", "changed_props": ["quantity"], "item": {}}],
  "completed": [{"uid": "...", "summary": "Mjölk", "item": {}}],
  "reopened": []
}
```

- `origin` is `ica` when the change was made outside Home Assistant (e.g. in the ICA app, found when polling) and `home_assistant` when it was made from Home Assistant (found when the sync response updates the cache). Use it to react only to changes made in the app, without reacting to your own changes.
- `completed` and `reopened` are the rows that were checked off or unchecked. They are also listed in `changed`.
- `item` is the full ICA row (`quantity`, `unit`, `isStrikedOver`, `offerId`, ...), without the offer details that the todo entity adds.
- Changes made in the ICA app are picked up when the integration polls ICA (every 5 minutes by default), or right away with `ica.refresh_shopping_lists`.

#### Events per item

Turn on *Events per item* in the integration options to also get one event for every row, besides `ica_list_items_changed`. It is off by default, as a change to many rows (e.g. a whole recipe) then fires many events.

| Event | Fired when |
|---|---|
| `ica_shopping_list_item_added` | An item is added to a tracked list |
| `ica_shopping_list_item_removed` | An item is removed |
| `ica_shopping_list_item_completed` | An item is checked off |
| `ica_shopping_list_item_reopened` | A checked off item is unchecked |

Payload: `config_entry_id`, `entity_id`, `offline_id`, `shopping_list_name`, `origin` (as above), `product_name` and `item` (the full ICA row).

### Examples

Notify when someone adds an item from the ICA app:

```yaml
triggers:
  - trigger: event
    event_type: ica_list_items_changed
    event_data:
      origin: ica
conditions:
  - "{{ trigger.event.data.added | count > 0 }}"
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: >
        {{ trigger.event.data.added | map(attribute='summary') | join(', ') }}
        added to {{ trigger.event.data.shopping_list_name }}
```

Notify when your favorite items go on offer:

```yaml
triggers:
  - trigger: event
    event_type: ica_favorite_offers
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Favorites on offer
      message: >
        {% for o in trigger.event.data.offers %}
        - {{ o.name }}: {{ o.offerPriceText }}
        {% endfor %}
```

A weekly summary of favorite items on offer:

```yaml
triggers:
  - trigger: time
    at: "08:00:00"
conditions:
  - condition: time
    weekday: [mon]
actions:
  - action: ica.get_offers
    data:
      favorites_only: true
    response_variable: offers
  - if: "{{ offers.data | count > 0 }}"
    then:
      - action: notify.mobile_app_my_phone
        data:
          message: "{{ offers.data | map(attribute='name') | join(', ') }}"
```

See also the blueprint [ica_track_new_offers.yaml](custom_components/ica/blueprints/ica_track_new_offers.yaml) for adding matching offers to a shopping list.

## Upgrading from v0.9.0 or earlier

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
