# Rune20

A web application for managing Dungeons & Dragons 5th Edition characters and campaigns in real-time. Built with **Flask** and **PostgreSQL**.

Final project for **CS50x 2025**.

---

## Features

### For Players

- **Interactive Character Sheet** — Two-column layout with fully editable fields for stats, level, XP, HP, gold, skills, notes, and background. All changes are saved to the database on blur with no page reload required.
- **D20 Stat Wheel** — Custom SVG sigil displaying STR, DEX, CON, INT, WIS, and CHA as six orbiting circles around a central D20 icosahedron. Scales responsively on mobile.
- **Live HP Bar** — Health bar updates instantly as you type or use the ±1/±5 quick-action buttons, with colour transitions (red -> orange -> dark red) and a pulse animation at low health.
- **Spell & Inventory Management** — Add spells and items from global catalogs, or attach custom-created equipment. Remove them individually from the sheet.
- **Dice Roller** — Roll any formula (e.g. `1d20+5`, `3d6-1`, `2d10`) from the character sheet. Results are broadcast to the campaign log immediately.


### For Dungeon Masters

- **Campaign Dashboard** — Create campaigns, generate unique invite codes, and see all joined players and their characters.
- **Real-time Dice Log** — Polls player rolls every 5 seconds and auto-scrolls the log, so the DM always sees the latest action.


### Security & Infrastructure

- **CSRF Protection** — All state-changing requests use WTForms CSRF tokens.
- **Password Hashing** — Credentials stored using `werkzeug.security` (PBKDF2-SHA256).
- **Input Validation** — RegEx guards on all user-supplied fields (names, formulas, credentials) before any database interaction.
- **SSL Database Connection** — PostgreSQL connections enforce `sslmode=require`.
- **Custom Error Pages** — Handlers for 403, 404, 405, 500, and CSRF failures.
- **Mobile Responsive** — Stat wheel, HP controls, and navigation all adapt to narrow viewports.

---

## File Structure

```text
rune20/
│
├── app.py                      # Flask app, all routes, API endpoints, and template filters
├── helpers.py                  # login_required decorator and error helper
├── requirements.txt            # Python dependencies
│
├── static/
│   ├── scripts.js              # All client-side logic: live edits, HP bar, dice roller, log polling
│   └── stylesheet.css          # Full stylesheet: layout grid, stat wheel, HP bar, responsive rules
│
└── templates/
    ├── layout.html             # Base template: header, nav, flash banners, CSRF meta tag
    ├── index.html              # Character list with quick-action cards
    ├── character_sheet.html    # Main sheet: D20 stat wheel, HP bar, inventory, spells, notes and background
    ├── character_creation.html # New character form
    ├── campaigns.html          # Owned and joined campaign overview
    ├── campaign_detail.html    # DM view: player list, dice log, campaign roller
    ├── campaign_creation.html  # New campaign form
    ├── join_campaign.html      # Join via campaign invite code
    ├── custom_items.html       # Custom item inventory
    ├── custom_item_creation.html
    ├── custom_item_edit.html
    ├── account.html            # Account info and logout
    ├── login.html
    ├── register.html
    └── error.html              # error card (403, 404, 500, etc)
```

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/characters/<id>/update` | Update a single character field |
| `GET`  | `/campaign/<id>/dice_logs` | Fetch all dice rolls for a campaign |
| `POST` | `/entity/add/<character_id>` | Add a spell, item, or custom item |
| `POST` | `/entity/remove` | Remove a spell, item, or custom item |
| `POST` | `/roll_dice` | Roll a formula and save to campaign log |
| `POST` | `/exit_campaign` | Remove a character from a campaign |
| `POST` | `/delete_character` | Delete a character |
| `POST` | `/delete_campaign` | Delete a campaign |
| `POST` | `/delete_custom_item` | Delete a custom item |

---

## Database Schema

PostgreSQL relational schema with the following key tables:

| Table | Purpose |
|-------|---------|
| `users` | Username, hashed password, email |
| `characters` | Stats, HP, XP, level, campaign FK, owner FK |
| `campaigns` | Name, description, invite code, DM FK |
| `dice_logs` | Formula, result, timestamp, campaign FK, character FK |
| `item_catalog` | Global item reference (type, rarity, weight, value) |
| `spell_catalog` | Global spell reference (level, school, components, etc.) |
| `custom_items` | User-created items scoped by `created_by` |
| `character_inventory` | Join table: characters <-> items/custom_items + quantity |
| `character_spells` | Join table: characters <-> spells + learned_at timestamp |

---

## Setup & Installation

### Prerequisites (local running)

- Python 3.10+

### 1. Clone

```bash
git clone <repository-url>
cd rune20
```

### 2. Virtual Environment

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment Variables

Create a `.env` file in the project root:

```env
DB_URL=postgresql://<user>:<password>@<host>:<port>/<dbname>
SECRET_KEY=<a-long-random-secret-key>
```

### 5. Run Locally

```bash
flask run
```

### Deployed version usage

1. Set `DB_URL` and `SECRET_KEY` as environment variables in your platform's dashboard — do **not** commit `.env`.
2. Use a production WSGI server instead of the Flask dev server:
   ```bash
   pip install gunicorn
   gunicorn app:app
   ```
3. Ensure your PostgreSQL provider allows external connections and that `sslmode=require` is supported (it is enabled by default in `app.py`).
4. Set `SESSION_TYPE = "filesystem"` or switch to a database-backed session store for multi-worker deployments.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `Flask` | Web framework |
| `Flask-WTF` | CSRF protection |
| `Flask-Session` | Server-side session storage |
| `psycopg2-binary` | PostgreSQL driver |
| `python-dotenv` | `.env` file loader |
| `Werkzeug` | Password hashing, routing utilities |
| `requests` | HTTP utility (helpers) |

---

## License

Non-official fan project. Not affiliated with or endorsed by Wizards of the Coast. D&D 5e content references are used for personal, non-commercial purposes.