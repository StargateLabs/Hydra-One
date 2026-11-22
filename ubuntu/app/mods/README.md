# mods/ — the overlay

Our app is upstream Strata plus a **mods** overlay. Upstream files stay upstream;
everything we added lives here and is applied at start-up, so a new upstream
release is "upstream + overlay + suite", never a fork merge
([ADR-0001](../docs/adr/0001-mods-overlay-on-upstream.md)).

| Path | What it is |
| --- | --- |
| `serve/` | The 403 custom `serve` modules of the live line (hash list: `OVERLAY.json`). Copied into the tree next to upstream's `serve/`. |
| `hooks.py` | The custom integration: managers created by `install_managers`, and the 87 custom route blocks of the live `serve/server.py` (`handle_get` / `handle_post`). `install(server_module)` wraps `Service.__init__` and `make_handler`. |
| `ROUTES.json` | Generated contract: every live-only route block (method, line, condition, paths). `test_hooks.py` checks the hooks cover it. |
| `test_hooks.py` | Fakes only: no engine, no socket, no live write. |

## What the hooks own

`install(server_module)` does three things and edits no upstream file:

1. copies the few server globals the route bodies need (`SERVER_GLOBALS`) into this module;
2. wraps `Service.__init__` so that `install_managers(svc)` adds the custom managers
   (update center, local integrations, VoiceStudio, HYDRA, power manager);
3. wraps `make_handler` so the returned handler tries `handle_get` / `handle_post`
   first and falls through to upstream's own routing.

The wrapper `do_POST` repeats upstream's `_authorized()` gate before the hooks:
upstream checks it inside `_post`, which runs only after the hooks.

## Which upstream blocks the hooks also own

Beside the custom routes, four upstream blocks are replaced because our web app
depends on their behaviour: the dashboard page (`/`, `/api-monitor`), `/v1/models`
(our `strata` alias and the optional backend), `/config` (the Control tab's shape)
and `/web/` (upstream serves only css/js/svg; our page also uses png/jpg/ico).
`ROUTES.json` lists them like every custom block.

## Rules

- A route belongs in `hooks.py` only when upstream does not serve it. Seven blocks
  of the live `do_POST` (`/settings`, `/config`, `/unload`, `/load`, the auth gate,
  the `/v1/` foreign-page gate and the unload/load ownership gate) are served by
  upstream 0.2.9 and stay upstream.
- Route bodies keep the live behaviour byte-for-byte except `self` → `handler` and
  a bare `return` → `return True`. Do not "improve" them here; that is a separate
  change with its own tests.
- A path that must be reachable is proven by `ROUTES.json` + `test_hooks.py`, not by
  reading the diff.
- Run the contract tests from the repository root:

  ```
  python -m unittest mods.test_hooks -v
  ```
