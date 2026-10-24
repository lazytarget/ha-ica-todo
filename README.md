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
- [ ] Translate strings [se, en]
- [ ] Implement config flows step for Reauth / refresh tokens
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
- [ ] Implement the different `CONFLICT_MODES`
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
- [ ] Document installation/configuration
- [ ] Document use-case examples
- [ ] Document Automation examples


## Automations

### Events

All events include `config_entry_id`, so automations can tell ICA accounts apart.

| Event | Fired when | Data |
|---|---|---|
| `ica_shopping_list_item_added` | An item is added to a tracked shopping list | see below |
| `ica_shopping_list_item_completed` | An item is checked off | see below |
| `ica_shopping_list_item_reopened` | A checked off item is unchecked | see below |
| `ica_shopping_list_item_removed` | An item is removed | see below |
| `ica_shopping_list_changed` | Once per sync with changes, summarizing them | `added`, `completed`, `reopened`, `removed` (lists of rows) plus the shared fields below |
| `ica_favorite_offers` | New offers match one of your favorite items | `offer_ids`, `offers` |
| `ica_new_offers` | New offers are found in your favorite stores | `new_offers` |

Shopping list events share these fields:

- `entity_id`: the To-do entity of the list, e.g. `todo.ica_handla`
- `shopping_list_id`, `shopping_list_name`
- `origin`: `ica` if the change was made outside Home Assistant (e.g. in the ICA app), `home_assistant` if made from Home Assistant
- `product_name` and `item` (the full ICA row: `quantity`, `unit`, `isStrikedOver`, `offerId`, ...), on the per-item events

Changes made in Home Assistant are sent to ICA right away. Changes made in the ICA app are picked up when the integration polls ICA (every 5 minutes by default), or right away with `ica.refresh_shopping_lists`. No item events are fired the first time a list is fetched.

### Services

- `ica.refresh_shopping_lists`: fetches the tracked shopping lists from ICA right away, e.g. when arriving at the store or from a dashboard button. Much lighter than `ica.refresh_all`.
- `ica.get_offers`: returns the currently valid offers in your favorite stores. Use `store_ids` to limit to some stores and `favorites_only: true` to only get offers matching your favorite items.
- `ica.get_baseitems` / `ica.add_baseitem`: get or add favorite items.
- `ica.add_offers_to_shopping_list` / `ica.upsert_shopping_list`: add offers or items to a shopping list.
- `ica.lookup_product`, `ica.search_articles`, `ica.get_recipe`: lookups.
- `ica.refresh_all`: force a refresh of all data.

To read the items of a list, use Home Assistant's built-in `todo.get_items`.

### Examples

Notify when someone adds an item from the ICA app:

```yaml
triggers:
  - trigger: event
    event_type: ica_shopping_list_item_added
    event_data:
      origin: ica
actions:
  - action: notify.mobile_app_my_phone
    data:
      message: "{{ trigger.event.data.product_name }} added to {{ trigger.event.data.shopping_list_name }}"
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
