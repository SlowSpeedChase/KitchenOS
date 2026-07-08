# Drafts → KitchenOS Recipe Action

Paste an AI-written recipe into the **Drafts** app on any machine, tap one action, and it lands in your KitchenOS recipe vault — no SSH, no copy-to-the-Mac.

## How it works

```
Drafts "Send Recipe to KitchenOS" action   (any Mac/iPhone/iPad)
        │  POST {title, content}
        ▼
Selene  POST /webhook/api/recipe            (Mac mini, port 5678, via Tailscale)
        │  • stores the note in Selene (dedup)
        │  • replies immediately  ← Drafts never waits on the parse
        │  • forwards the text to KitchenOS in the background
        ▼
KitchenOS  POST /api/recipes/import-text     (Mac mini, port 5001, local)
        │  • parses the text with Ollama (~1–3 min)
        ▼
   recipe saved to the Obsidian vault, with the original text kept
   in a collapsible "Import Source" block
```

Because Selene replies in milliseconds and the slow Ollama parse runs in the background, the Drafts action returns instantly. If KitchenOS is down, the note is still safe in Selene and the failed forward is logged for a retry.

## Prerequisites

- **Tailscale** installed on the Mac mini and on every device you'll send from (same Tailnet).
- **Selene prod server** running on the Mac mini (port 5678) — `curl http://localhost:5678/health` should return `{"status":"ok",...}`.
- **KitchenOS API server** running on the Mac mini (port 5001) — `curl http://localhost:5001/health` → `{"status":"ok"}`.
- **Ollama** running on the Mac mini (`curl http://localhost:11434/api/tags`).
- The **Drafts** app installed on the sending device.

The endpoint host is the Mac mini's Tailscale MagicDNS name: `chases-mac-mini.taila69703.ts.net`.

## Step 1: Create the Drafts action

1. Open **Drafts** → tap the **action list** (right-side panel) → **Manage Actions** (or the **+** in the actions bar).
2. Tap **+** to create a new action. Name it **`Send Recipe to KitchenOS`**.
3. (Optional) Give it an icon/color so it's easy to find.
4. Add one action step: **Script** is *not* needed — use the built-in **HTTP / URL** step described below.

## Step 2: Add the HTTP request step

Add a **"Send to ... / HTTP"**–type step (in Drafts this is the **"Script"**-category step called **`HTTP Request`**, or use a **`URL`** step that POSTs JSON). Configure it:

| Field | Value |
|-------|-------|
| **URL** | `http://chases-mac-mini.taila69703.ts.net:5678/webhook/api/recipe` |
| **Method** | `POST` |
| **Encoding / Content-Type** | `application/json` |
| **Body** | `{"title": "[[title]]", "content": "[[draft]]"}` |

- `[[title]]` expands to the draft's first line (the recipe name).
- `[[draft]]` expands to the full draft text (the recipe).

> If your Drafts step builds the body from form fields instead of raw JSON, set two JSON parameters: `title` = `[[title]]`, `content` = `[[draft]]`.

## Step 3: (Recommended) Show the result

Add a second step so you get confirmation:

- **Show Alert / Notification** with the HTTP response, or
- A simple **"Recipe sent to KitchenOS"** banner.

A successful send returns:

```json
{"status": "created", "id": 409}
```

(`"status": "duplicate"` means you already sent this exact text before — Selene dedups by content.)

## Step 4: Use it

1. Create or paste a recipe into a new draft. The **first line becomes the recipe name**; everything else is the recipe body (ingredients, steps, notes — any layout the model can read).
2. Run the **Send Recipe to KitchenOS** action.
3. Within ~1–3 minutes the recipe appears in your vault (`Recipes/`), with nutrition, an ingredients table, and a collapsible **Import Source** block holding your original text.

### Example draft

```
Chamomile Strawberry Black Bean Brownies

Fudgy black bean brownies with strawberry jam swirl.

INGREDIENTS
- 15 oz black beans, drained
- 1/2 cup butter
- 4 oz dark chocolate
...

STEPS
1. Blend the black beans until smooth.
2. Melt butter and chocolate.
...
```

## Fixing a bad parse

The model occasionally mis-reads something. Two ways to fix it:

1. **Edit in Obsidian** — the saved recipe is plain markdown; just correct it.
2. **Re-send a corrected paste** — run the action again with the same recipe name. KitchenOS overwrites the file (backing up the previous version first), so the corrected version wins.

The original text you sent is always preserved in the **Import Source** block at the bottom of the recipe, so nothing is ever lost.

## iOS Shortcut alternative

If you prefer the **Share Sheet** over Drafts, create a Shortcut instead:

1. **Shortcuts** app → **+** → name it **Send Recipe to KitchenOS**.
2. **Receive** **Text** from **Share Sheet** (and **Quick Look**/clipboard if you want to run it manually).
3. **Get Contents of URL**:
   - URL: `http://chases-mac-mini.taila69703.ts.net:5678/webhook/api/recipe`
   - Method: **POST**, Request Body: **JSON**
   - `title`: first line of the Shortcut Input (use **Split Text** by **New Lines** → **First Item**)
   - `content`: the Shortcut Input
4. (Optional) **Show Notification** with the response.

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `Title and content are required` (HTTP 400) | The body must contain both `title` and `content`. Check the JSON keys — `content`, not `text`. |
| Action hangs or times out | Selene should reply instantly. A hang means Selene is unreachable: check Tailscale is connected on the device, and `curl http://localhost:5678/health` on the Mac. |
| Send succeeds but no recipe appears | The background forward to KitchenOS may have failed. On the Mac: `tail -f ~/Dev/selene/logs/selene.log` and look for `module: recipe-route` / "KitchenOS import failed", and verify `curl http://localhost:5001/health`. |
| Recipe appears but fields look wrong | Normal for an occasional parse miss — fix in Obsidian or re-send a corrected paste (see "Fixing a bad parse"). |
| `"status": "duplicate"` | You already sent this exact text. Change something or edit the existing recipe directly. |

## Related

- KitchenOS endpoint: `api_server.py` → `/api/recipes/import-text`
- Selene route: `~/Dev/selene/src/routes/recipe.ts` → `/webhook/api/recipe`
- Selene feature guide: `~/Dev/selene/docs/guides/features/recipe-to-kitchenos.md`
- iOS YouTube extraction (different flow): `docs/setup/iOS_SHORTCUT_SETUP.md`
