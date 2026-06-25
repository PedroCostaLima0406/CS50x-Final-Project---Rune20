import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import re
import string
import random
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for, g, jsonify
from flask_session import Session

from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf, CSRFError

from werkzeug.security import check_password_hash, generate_password_hash

from helpers import error, login_required


load_dotenv()

def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(os.getenv("DB_URL") + "?sslmode=require")
    return g.db


def has_dice_log_formula_column(conn):
    """Checks whether dice_logs has a formula column."""

    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'dice_logs'
            AND column_name = 'formula'
            LIMIT 1
        """)
        return cur.fetchone() is not None


def generate_join_code(length=10):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))


def generate_unique_join_code(conn, length=10, max_tries=10):
    with conn.cursor() as cur:
        for i in range(max_tries):
            code = generate_join_code(length)
            cur.execute("""
                SELECT 1 FROM campaigns
                WHERE join_code = %s
            """, (code,))

            if not cur.fetchone():
                return code
    raise Exception("could not generate unique join code")



# Configure application
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
csrf = CSRFProtect(app)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


email_pattern = r"^[\w\.-]+@[\w\.-]+\.\w{2,}$"
password_pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,20}$"
username_pattern = r"^(?=.{3,20}$)[a-zA-Z](?!.*[._]{2})[a-zA-Z0-9._]*[a-zA-Z0-9]$"
character_name_pattern = r"^(?!.*[-']{2,})(?! )[A-Za-z0-9 -']{2,30}(?<! )$"
campaign_name_pattern = r"^[A-Za-z0-9 _-]{3,50}$"
custom_item_name_pattern = r"^(?!.*[-']{2,})(?! )[A-Za-z0-9()' -]{2,50}(?<! )$"
dice_roll_pattern = r"\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*"



@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.route("/account")
@login_required
def account():
    """Shows account information"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT username, email FROM users
            WHERE id = %s
        """, (user_id,))
        row = cur.fetchone()
        if row is None:
            return error("user not found", 404)

        username = row["username"]
        email = row["email"]

        return render_template("account.html", username=username, email=email)
    except psycopg2.Error as e:
        app.logger.exception("character_detail database error")
        return error("unexpected error", 500)
    except Exception as e:
        app.logger.exception("character_detail unexpected error")
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/api/characters/<int:character_id>/update", methods=["POST"])
@login_required
def update_character(character_id):
    """Updates a character's sheet"""

    user_id = session["user_id"]

    data = request.get_json()
    field = data.get("field")
    value = data.get("value")

    field_map = {
        "strength": "strength", "dexterity": "dexterity", "constitution": "constitution",
        "intelligence": "intelligence", "wisdom": "wisdom", "charisma": "charisma",
        "hit_points": "hit_points", "max_hit_points": "max_hit_points", "temp_hp": "temp_hp",
        "background": "background", "notes": "notes", "skills_notes": "skills_notes",
        "race": "race", "class": "class", "level": "level",
        "xp": "xp", "gold": "gold"
    }

    if field not in field_map:
        return {"status": "error", "message": "Invalid field"}, 400
    column = quote_identifier(field_map[field])

    # verifies fields that can't be negative ints
    non_negative_int_fields = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
                       "hit_points", "max_hit_points", "temp_hp", "level", "xp"}

    if field in non_negative_int_fields:
        if not value.isdigit():
            return {"status": "error", "message": f"{field} must be a non-negative integer."}, 400
        value = int(value)

    if field == "gold":
        try:
            value = int(value)
        except ValueError:
            return {"status": "error", "message": "Gold must be an integer."}, 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        sql = f"""UPDATE characters
            SET {column} = %s
            WHERE id = %s
            AND owner_id = %s"""
        cur.execute(sql, (value, character_id, user_id,))

        conn.commit()
        return {"status": "success"}
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": "unexpected error"}, 500
    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": "unexpected error"}, 500
    finally:
        if cur:
            cur.close()


@app.route("/campaigns/create", methods=["GET", "POST"])
@login_required
@csrf.exempt
def campaign_creation():
    """Allows users to create campaigns"""

    if request.method == "GET":
        return render_template("campaign_creation.html")

    else:
        user_id = session["user_id"]

        name = (request.form.get("name") or "").strip()
        description = request.form.get("description")

        if not name or not re.fullmatch(campaign_name_pattern, name):
            return error("please provide a valid campaign name", 400)

        conn = None
        cur = None
        try:
            conn = get_db()
            join_code = generate_unique_join_code(conn)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO campaigns (name, description, join_code, created_by)
                VALUES (%s, %s, %s, %s)
            """, (name, description, join_code, user_id,))
            conn.commit()

            return redirect(url_for("campaigns"))
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        except Exception as e:
            if conn:
                conn.rollback()
            return error(str(e), 500)
        finally:
            if cur:
                cur.close()


@app.route("/campaigns/<int:campaign_id>")
@login_required
def campaign_detail(campaign_id):
    """Shows campaign information and dice log"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # campaign information
        cur.execute("""
            SELECT *
            FROM campaigns
            WHERE created_by = %s
            AND id = %s
        """, (user_id, campaign_id,))
        campaign = cur.fetchone()

        if not campaign:
            return error("Invalid campaign id, please select an owned campaign", 400)

        # campaign characters and players
        cur.execute("""
            SELECT characters.name, characters.id, users.username
            FROM characters JOIN users
            ON characters.owner_id = users.id
            WHERE characters.campaign_id = %s
            ORDER BY characters.name ASC
        """, (campaign_id,))
        campaign_characters = cur.fetchall()

        # campaign's dice roll log
        select_formula = "dice_logs.formula" if has_dice_log_formula_column(conn) else "NULL AS formula"
        cur.execute(f"""
            SELECT dice_logs.id, dice_logs.roll_result, {select_formula}, characters.name, dice_logs.created_at
            FROM dice_logs JOIN characters
            ON dice_logs.character_id = characters.id
            WHERE characters.campaign_id = %s
            ORDER BY dice_logs.created_at DESC
            LIMIT 100
        """, (campaign_id,))
        dice_log = cur.fetchall()

        return render_template("campaign_detail.html", campaign=campaign, campaign_characters=campaign_characters, dice_log=dice_log)
    except psycopg2.Error as e:
        app.logger.exception("campaign_detail database error")
        return error("unexpected error", 500)
    except Exception as e:
        app.logger.exception("campaign_detail unexpected error")
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/campaigns", methods=["GET", "POST"])
@login_required
def campaigns():
    """Shows campaigns owned and entered by user"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # campaigns owned by user
        cur.execute("""
            SELECT id, name, created_at
            FROM campaigns
            WHERE created_by = %s
            ORDER BY created_at DESC
        """, (user_id,))
        owned_campaigns = cur.fetchall()

        # joined campaigns
        cur.execute("""
            SELECT campaigns.name, campaigns.created_at, characters.name AS cha_name, characters.id, users.username
            FROM campaigns JOIN characters ON campaigns.id = characters.campaign_id
            JOIN users ON campaigns.created_by = users.id
            WHERE characters.owner_id = %s
            ORDER BY campaigns.created_at DESC
        """, (user_id,))
        joined_campaigns = cur.fetchall()

        return render_template("campaigns.html", owned_campaigns=owned_campaigns, joined_campaigns=joined_campaigns)
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/characters/create", methods=["GET", "POST"])
@login_required
def character_creation():
    """Allows users to create characters"""

    if request.method == "GET":
        return render_template("character_creation.html")

    else:
        user_id = session["user_id"]

        name = (request.form.get("name") or "").strip()
        race = (request.form.get("race") or "").strip()
        class_ = (request.form.get("class") or "").strip()
        skills = (request.form.get("skills") or "").strip()
        background = request.form.get("background")
        notes = request.form.get("notes")

        if not name or not re.fullmatch(custom_item_name_pattern, name):
            return error("please provide a valid character name", 400)

        if not race or not class_ or not skills or not background or not notes:
            return error("please provide valid character information", 400)

        conn = None
        cur = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO characters (name, race, "class", background, notes, skills_notes, owner_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, race, class_, background, notes, skills, user_id,))
            conn.commit()

            return redirect(url_for("index"))
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        except Exception as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        finally:
            if cur:
                cur.close()


@app.route("/characters/<int:character_id>")
@login_required
def character_detail(character_id):
    """Shows character information"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT c.name AS name, c.race AS race, c."class" AS class, c.level AS level, c.xp AS xp, c.gold AS gold,
            c.strength AS str, c.dexterity AS dex, c.constitution AS con, c.intelligence AS int, c.wisdom AS wis, c.charisma AS cha,
            c.hit_points AS hp, c.max_hit_points AS max_hp, c.temp_hp AS temp_hp, c.background AS background, c.notes AS notes, c.skills_notes AS skills,
            chi.item_id AS i_id, chi.custom_item_id AS ci_id, chi.quantity AS i_quantity,
            ic.name AS i_name, ic.description AS i_desc, ic.item_type AS i_type, ic.rarity AS i_rarity, ic.weight AS i_weight, ic.value AS i_value,
            ci.name AS ci_name, ci.description AS ci_desc,
            campaigns.id AS camp_id, campaigns.name AS camp_name, campaigns.description AS camp_desc, campaigns.created_at AS camp_creation,
            users.username AS camp_creator,
            cs.spell_id AS s_id, cs.learned_at AS s_learn,
            sc.name AS s_name, sc.description AS s_desc, sc.level AS s_level, sc.school AS s_school, sc.casting_time AS s_cast, sc.range AS s_range,
            sc.components AS s_comp, sc.duration AS s_duration

            FROM characters c LEFT JOIN character_inventory chi ON c.id = chi.character_id
            LEFT JOIN item_catalog ic ON ic.id = chi.item_id
            LEFT JOIN custom_items ci ON ci.id = chi.custom_item_id
                AND ci.created_by = %s
            LEFT JOIN campaigns ON c.campaign_id = campaigns.id
            LEFT JOIN users ON users.id = campaigns.created_by
            LEFT JOIN character_spells cs ON cs.character_id = c.id
            LEFT JOIN spell_catalog sc ON sc.id = cs.spell_id

            WHERE c.id = %s
            AND c.owner_id = %s
        """, (user_id, character_id, user_id,))
        rows = cur.fetchall()
        if not rows:
            return error("Character not found or permission denied", 404)

        # character's information
        character = {
            'id': character_id,
            'name': rows[0]['name'],
            'race': rows[0]['race'],
            'class': rows[0]['class'],
            'level': rows[0]['level'],
            'xp': rows[0]['xp'],
            'gold': rows[0]['gold'],
            'stats': {
                'strength': rows[0]['str'],
                'dexterity': rows[0]['dex'],
                'constitution': rows[0]['con'],
                'intelligence': rows[0]['int'],
                'wisdom': rows[0]['wis'],
                'charisma': rows[0]['cha'],
            },
            'hit_points': rows[0]['hp'],
            'max_hit_points': rows[0]['max_hp'],
            'temp_hp': rows[0]['temp_hp'],
            'background': rows[0]['background'],
            'notes': rows[0]['notes'],
            'skills_notes': rows[0]['skills'],
            'campaign': {
                'id': rows[0]['camp_id'],
                'name': rows[0]['camp_name'],
                'description': rows[0]['camp_desc'],
                'created_at': rows[0]['camp_creation'],
                'creator': rows[0]['camp_creator']
            } if rows[0]['camp_id'] else None
        }


        # character's inventory
        items = []
        seen_items = set()

        custom_items = []
        seen_custom_items = set()

        # character's spells
        spells = []
        seen_spells = set()

        for row in rows:
            # standard items
            if row['i_id'] and row['i_id'] not in seen_items:
                items.append({
                    'id': row['i_id'],
                    'name': row['i_name'],
                    'description': row['i_desc'],
                    'type': row['i_type'],
                    'rarity': row['i_rarity'],
                    'weight': row['i_weight'],
                    'value': row['i_value'],
                    'quantity': row['i_quantity']
                })
                seen_items.add(row['i_id'])

            # custom items
            if row['ci_id'] and row['ci_id'] not in seen_custom_items:
                custom_items.append({
                    'id': row['ci_id'],
                    'name': row['ci_name'],
                    'description': row['ci_desc'],
                    'quantity': row['i_quantity']
                })
                seen_custom_items.add(row['ci_id'])

            # spells
            if row['s_id'] and row['s_id'] not in seen_spells:
                spells.append({
                    'id': row['s_id'],
                    'name': row['s_name'],
                    'description': row['s_desc'],
                    'level': row['s_level'],
                    'school': row['s_school'],
                    'casting_time': row['s_cast'],
                    'range': row['s_range'],
                    'components': row['s_comp'],
                    'duration': row['s_duration'],
                    'learned_at': row['s_learn']
                })
                seen_spells.add(row['s_id'])

        # gets item, spell and custom items catalog
        cur.execute("""
            SELECT * FROM item_catalog
            ORDER BY item_type, name
        """)
        item_catalog = cur.fetchall()

        cur.execute("""
            SELECT *
            FROM custom_items
            WHERE created_by = %s
            ORDER BY name
        """, (user_id,))
        custom_item_catalog = cur.fetchall()

        cur.execute("""
            SELECT * FROM spell_catalog
            ORDER BY school, name
        """)
        spell_catalog = cur.fetchall()

        return render_template("character_sheet.html", character=character, items=items, custom_items=custom_items, spells=spells, item_catalog=item_catalog, custom_item_catalog=custom_item_catalog, spell_catalog=spell_catalog)
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/custom_items/create", methods=["GET", "POST"])
@login_required
def custom_item_creation():
    """Allows users to create custom items"""

    if request.method == "GET":
        return render_template("custom_item_creation.html")

    else:
        user_id = session["user_id"]

        name = (request.form.get("name") or "").strip()
        description = request.form.get("description")

        if not name or not re.fullmatch(custom_item_name_pattern, name):
            return error("please provide a valid item name", 400)

        conn = None
        cur = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO custom_items (name, description, created_by)
                VALUES (%s, %s, %s)
            """, (name, description, user_id,))
            conn.commit()

            return redirect(url_for("index"))
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        except Exception as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        finally:
            if cur:
                cur.close()


@app.route("/custom_items", methods=["GET", "POST"])
@login_required
def custom_items():
    """Allows users to view created custom items"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # custom items created by user
        cur.execute("""
            SELECT *
            FROM custom_items
            WHERE created_by = %s
        """, (user_id,))
        custom_items = cur.fetchall()

        return render_template("custom_items.html", custom_items=custom_items)
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/custom_items/edit", methods=["GET", "POST"])
@login_required
def custom_item_edit():
    """Allows users to edit a custom item created by them"""

    user_id = session["user_id"]
    custom_item_id_raw = request.args.get("custom_item_id") or request.form.get("custom_item_id")

    if not custom_item_id_raw or not str(custom_item_id_raw).isdigit():
        return error("invalid item id", 400)

    custom_item_id = int(custom_item_id_raw)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # custom item's information
        cur.execute("""
            SELECT *
            FROM custom_items
            WHERE id = %s
        """, (custom_item_id,))
        custom_item = cur.fetchone()

        if not custom_item:
            return error("item not found", 404)

        if int(custom_item["created_by"]) != int(user_id):
            return error("permission denied", 403)
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()

    if request.method == "GET":
        return render_template("custom_item_edit.html", custom_item=custom_item)

    else:
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description")

        if not name or not description or not re.fullmatch(custom_item_name_pattern, name):
            return error("invalid name and/or description", 400)

        conn = None
        cur = None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                UPDATE custom_items
                SET name = %s, description = %s
                WHERE id = %s
                AND created_by = %s
            """, (name, description, custom_item_id, user_id,))

            if cur.rowcount == 0:
                return error("invalid item or permission denied", 404)
            conn.commit()
            flash("You have updated your custom item.")

            return redirect(url_for("custom_items"))
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        except Exception as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        finally:
            if cur:
                cur.close()


@app.route("/delete_campaign", methods=["POST"])
@login_required
def delete_campaign():
    """Allows users to delete an owned campaign"""

    user_id = session["user_id"]
    campaign_id = request.form.get("campaign_id")

    if not campaign_id:
        return error("unexpected error", 400)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM campaigns
            WHERE id = %s
            AND created_by = %s
        """, (campaign_id, user_id,))

        if cur.rowcount == 0:
            return error("Campaign not found or permission denied", 404)
        conn.commit()
        flash("You have deleted your campaign.")

        return redirect(url_for("campaigns"))
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    except Exception as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/delete_character", methods=["POST"])
@login_required
def delete_character():
    """Allows users to delete an owned character"""

    user_id = session["user_id"]
    character_id = request.form.get("character_id")

    if not character_id:
        return error("unexpected error", 400)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM characters
            WHERE id = %s
            AND owner_id = %s
        """, (character_id, user_id,))

        if cur.rowcount == 0:
            return error("Character not found or permission denied", 404)
        conn.commit()
        flash("You have deleted your character.")

        return redirect(url_for("index"))
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    except Exception as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/delete_custom_item", methods=["POST"])
@login_required
def delete_custom_item():
    """Allows users to delete a custom item created by them"""

    user_id = session["user_id"]
    custom_item_id = request.form.get("custom_item_id")

    if not custom_item_id:
        return error("unexpected error", 400)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM custom_items
            WHERE id = %s
            AND created_by = %s
        """, (custom_item_id, user_id,))

        if cur.rowcount == 0:
            return error("Custom item not found or permission denied", 404)
        conn.commit()
        flash("You have deleted your custom item.")

        return redirect(url_for("custom_items"))
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    except Exception as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()



@app.route("/campaign/<int:campaign_id>/dice_logs")
@login_required
def dice_log(campaign_id):
    """Gets the dice log for a given campaign"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT 1 FROM campaigns
            WHERE id = %s AND (created_by = %s OR EXISTS (
            SELECT 1 FROM characters WHERE campaign_id = %s AND owner_id = %s
        ))
        """, (campaign_id, user_id, campaign_id, user_id,))
        if cur.fetchone() is None:
            return jsonify({"error": "access denied"}), 403

        select_formula = "dice_logs.formula" if has_dice_log_formula_column(conn) else "NULL AS formula"
        cur.execute(f"""
            SELECT dice_logs.roll_result, {select_formula}, dice_logs.created_at, COALESCE(dice_logs.display_name, characters.name) AS name
            FROM dice_logs JOIN characters
            ON dice_logs.character_id = characters.id
            WHERE dice_logs.campaign_id = %s
            ORDER BY dice_logs.created_at DESC
            LIMIT 50
        """, (campaign_id,))
        rows = cur.fetchall()

        return jsonify(rows)
    except psycopg2.Error as e:
        return jsonify({"error": "database error"}), 500
    except Exception as e:
        return jsonify({"error": "unexpected error"}), 500
    finally:
        if cur:
            cur.close()


@app.route("/entity/add/<int:character_id>", methods=["POST"])
@login_required
def add_entity(character_id):
    """Allows users to add an entity to an owned character's inventory or spells catalog"""

    user_id = session["user_id"]

    data = request.get_json()
    entity_type = data.get("entity_type")
    entity_id = data.get("entity_id")

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT 1 FROM characters
            WHERE id = %s AND owner_id = %s
            """, (character_id, user_id,))
        if cur.fetchone() is None:
            return jsonify({"status": "error", "message": "Permission denied"}), 403

        if entity_type in ["item","custom_item"]:
            column = "item_id" if entity_type == "item" else "custom_item_id"
            cur.execute(f"""
                SELECT quantity FROM character_inventory
                WHERE character_id = %s
                AND {column} = %s
            """, (character_id, entity_id,))
            existing = cur.fetchone()

            if existing:
                cur.execute(f"""
                    UPDATE character_inventory
                    SET quantity = quantity + 1
                    WHERE character_id = %s
                    AND {column} = %s
                """, (character_id, entity_id,))
            else:
                # add item or custom item to character's inventory
                cur.execute(f"""
                    INSERT INTO character_inventory (character_id, {column})
                    VALUES (%s, %s)
                """, (character_id, entity_id,))


        elif entity_type == "spell":
            # add spell to character's spells
            cur.execute("""
                INSERT INTO character_spells (character_id, spell_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (character_id, entity_id,))

        else:
            return jsonify({"status": "error", "message": "Invalid entity or entity type"}), 400

        conn.commit()
        return jsonify({"status": "success"})
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": "unexpected error"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "message": "unexpected error"}), 500
    finally:
        if cur:
            cur.close()


@app.route("/entity/remove", methods=["POST"])
@login_required
def delete_entity():
    """Allows users to delete an entity from an owned character's inventory or spells catalog"""

    user_id = session["user_id"]

    character_id = request.form.get("character_id")
    item_id = request.form.get("item_id")
    custom_item_id = request.form.get("custom_item_id")
    spell_id = request.form.get("spell_id")

    if not character_id:
        return jsonify({"success": False, "error": "No character id"}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        if item_id:
            # remove item from character's inventory, first checking for quantity
            cur.execute("""
                SELECT quantity
                FROM character_inventory
                JOIN characters ON characters.id = character_inventory.character_id
                WHERE character_inventory.character_id = %s
                AND character_inventory.item_id = %s
                AND characters.owner_id = %s
            """, (character_id, item_id, user_id,))
            result = cur.fetchone()

            if result and result[0] > 1:
                cur.execute("""
                    UPDATE character_inventory
                    SET quantity = quantity - 1
                    WHERE character_id = %s AND item_id = %s
                """, (character_id, item_id,))

            else:
                cur.execute("""
                    DELETE FROM character_inventory
                    USING characters
                    WHERE character_inventory.character_id = characters.id
                    AND character_inventory.character_id = %s
                    AND character_inventory.item_id = %s
                    AND characters.owner_id = %s
                """, (character_id, item_id, user_id,))
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Item not found or permission denied"}), 404

        elif custom_item_id:
            # remove custom item from character's inventory, first checking for quantity
            cur.execute("""
                SELECT quantity
                FROM character_inventory
                JOIN characters ON characters.id = character_inventory.character_id
                WHERE character_inventory.character_id = %s
                AND character_inventory.custom_item_id = %s
                AND characters.owner_id = %s
            """, (character_id, custom_item_id, user_id,))
            result = cur.fetchone()

            if result and result[0] > 1:
                cur.execute("""
                    UPDATE character_inventory
                    SET quantity = quantity - 1
                    WHERE character_id = %s AND custom_item_id = %s
                """, (character_id, custom_item_id))

            else:
                cur.execute("""
                    DELETE FROM character_inventory
                    USING characters
                    WHERE character_inventory.character_id = characters.id
                    AND character_inventory.character_id = %s
                    AND character_inventory.custom_item_id = %s
                    AND characters.owner_id = %s
                """, (character_id, custom_item_id, user_id,))
                if cur.rowcount == 0:
                    return jsonify({"success": False, "error": "Custom item not found or permission denied"}), 404

        elif spell_id:
            # remove spell from character's spells
            cur.execute("""
                DELETE FROM character_spells
                USING characters
                WHERE character_spells.character_id = characters.id
                AND character_spells.character_id = %s
                AND character_spells.spell_id = %s
                AND characters.owner_id = %s
            """, (character_id, spell_id, user_id,))
            if cur.rowcount == 0:
                return jsonify({"success": False, "error": "Spell not found or permission denied"}), 404

        else:
            return jsonify({"success": False, "error": "No valid id provided"}), 400

        conn.commit()
        return jsonify({"success": True})
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "error": "unexpected error"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"success": False, "error": "unexpected error"}), 500
    finally:
        if cur:
            cur.close()


@app.route("/exit_campaign", methods=["POST"])
@login_required
def exit_campaign():
    """Allows users to exit an entered campaign"""

    user_id = session["user_id"]

    character_id = request.form.get("character_id")

    if not character_id:
        return error("unexpected error", 400)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE characters SET campaign_id = %s
            WHERE owner_id = %s
            AND id = %s
        """, (None, user_id, character_id,))

        if cur.rowcount == 0:
            return error("Character not found or permission denied", 404)
        conn.commit()
        flash("You have exited the campaign.")

        return redirect(url_for("campaigns"))
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    except Exception as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/")
@login_required
def index():
    """Shows characters owned by user"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # characters owned by user
        cur.execute("""
            SELECT characters.id, characters.name, characters.level, characters.campaign_id, campaigns.name AS c_name
            FROM characters LEFT JOIN campaigns ON characters.campaign_id = campaigns.id
            WHERE characters.owner_id = %s
            ORDER BY characters.name
        """, (user_id,))
        characters = cur.fetchall()

        return render_template("index.html", characters=characters)
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/join_campaign", methods=["GET", "POST"])
@login_required
def join_campaign():
    """Allows users to join campaigns"""

    user_id = session["user_id"]

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT name, id FROM characters
            WHERE owner_id = %s
            ORDER BY name
        """, (user_id,))
        characters = cur.fetchall()
    except psycopg2.Error as e:
        return error("unexpected error", 500)
    except Exception as e:
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()

    if request.method == "GET":
        if not characters:
            flash("You need to create a character before joining a campaign")
            return redirect(url_for("character_creation"))

        return render_template("join_campaign.html", characters=characters)

    else:
        character_id = request.form.get("character_id")
        code = (request.form.get("code") or "").strip()

        if not character_id or not code:
            return error("invalid input", 400)

        character_ids = [str(character['id']) for character in characters]
        if character_id not in character_ids:
                return error("invalid character", 400)

        cur = None
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id FROM campaigns
                WHERE join_code = %s
            """, (code,))
            campaign = cur.fetchone()
            if not campaign:
                return error("invalid join code and/or campaign", 400)

            # checks if character is already in a campaign
            cur.execute("""
                SELECT campaign_id FROM characters
                WHERE id = %s AND owner_id = %s
            """, (character_id, user_id,))
            result = cur.fetchone()
            if result and result["campaign_id"] is not None:
                return error("Character is already in a campaign. Exit first to join a new one.", 400)

            campaign_id = campaign["id"]
            cur.execute("""
                UPDATE characters SET campaign_id = %s
                WHERE owner_id = %s
                AND id = %s
            """, (campaign_id, user_id, character_id,))
            conn.commit()
            flash("You have joined the campaign.")

            return redirect(url_for("campaigns"))
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        except Exception as e:
            if conn:
                conn.rollback()
            return error("unexpected error", 500)
        finally:
            if cur:
                cur.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    """Allows user to log into an existing account"""

    # forget any user_id
    session.clear()

    if request.method == "GET":
        return render_template("login.html")

    else:
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password")

        if not username or not password or not email:
            return error("invalid user information", 400)

        if not re.fullmatch(email_pattern, email) or not re.fullmatch(password_pattern, password) or not re.fullmatch(username_pattern, username):
            return error("invalid user information", 400)

        conn = None
        cur = None
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, password_hash FROM users
                WHERE username = %s
                AND email = %s
            """, (username, email,))
            row = cur.fetchone()

            if not row or not check_password_hash(row["password_hash"], password):
                return error("invalid username, email and/or password", 403)

            # remember which user has logged in
            session["user_id"] = row["id"]

            # redirects to homepage
            return redirect(url_for("index"))
        except psycopg2.Error as e:
            return error("unexpected error", 500)
        except Exception as e:
            return error("unexpected error", 500)
        finally:
            if cur:
                cur.close()


@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    """Allows user to log out of an account"""

    # forget any user_id
    session.clear()
    flash("You have been logged out.")

    # redirect user to login form
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """Allows users to create an account"""

    # register non-registred users into the database for log in
    if request.method == "GET":
        return render_template("register.html")

    else:
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username or not password or not confirmation or not email:
            return error("invalid information", 400)

        if password != confirmation:
            return error("passwords don't coincide", 400)

        # checks for valid regex pattern
        if re.fullmatch(email_pattern, email) and re.fullmatch(password_pattern, password) and re.fullmatch(username_pattern, username):
            conn = None
            cur = None
            try:
                password_hash = generate_password_hash(password)

                # adds user information into the database
                conn = get_db()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO users (username, email, password_hash)
                    VALUES (%s, %s, %s)
                """, (username, email, password_hash,))
                conn.commit()

                return redirect(url_for("login"))
            except psycopg2.IntegrityError:
                if conn:
                    conn.rollback()
                return error("username or email address already in use", 400)
            except psycopg2.Error as e:
                if conn:
                    conn.rollback()
                return error("unexpected error", 500)
            except Exception as e:
                if conn:
                    conn.rollback()
                return error("unexpected error", 500)
            finally:
                if cur:
                    cur.close()
        else:
            return error("invalid username, email or password format", 400)


@app.route("/remove_character", methods=["POST"])
@login_required
def remove_character():
    """Allows campaign owners to remove a given character from the campaign"""

    user_id = session["user_id"]

    character_id = request.form.get("character_id")
    if not character_id:
        return error("unexpected error", 400)

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        # checks if character belongs to a campaign owned by the user
        cur.execute("""
            SELECT c.campaign_id
            FROM characters c JOIN campaigns cam
            ON c.campaign_id = cam.id
            WHERE c.id = %s AND cam.created_by = %s
        """, (character_id, user_id,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            return error("permission denied or character not in a campaign", 400)

        cur.execute("""
            UPDATE characters SET campaign_id = NULL
            WHERE id = %s
        """, (character_id,))
        conn.commit()
        flash("You have removed the character.")

        return redirect(url_for("campaigns"))
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    except Exception as e:
        if conn:
            conn.rollback()
        return error("unexpected error", 500)
    finally:
        if cur:
            cur.close()


@app.route("/roll_dice", methods=["POST"])
@login_required
def roll_dice():
    """Allows players to roll dice"""

    user_id = session["user_id"]

    data = request.get_json()
    campaign_id = data.get("campaign_id")
    character_id = data.get("character_id")
    formula = data.get("formula")
    display_name = data.get("display_name")

    if not all([campaign_id, character_id, formula]):
        return jsonify({"error": "Missing data"}), 400

    match = re.fullmatch(dice_roll_pattern, formula)
    if not match:
        return jsonify({"error": "Invalid dice roll formula"}), 400

    normalized_formula = re.sub(r"\s+", "", formula)

    num_dice = int(match.group(1)) if match.group(1) else 1
    dice_type = int(match.group(2))
    modifier = int(match.group(3).replace(" ", "")) if match.group(3) else 0

    if num_dice > 100 or dice_type > 1000:
        return jsonify({"error": "Too many dice or faces"}), 400

    rolls = [random.randint(1, dice_type) for _ in range(num_dice)]
    total = sum(rolls) + modifier

    conn = None
    cur = None
    try:
        conn = get_db()

        has_formula_column = has_dice_log_formula_column(conn)
        if not has_formula_column:
            try:
                with conn.cursor() as cur:
                    cur.execute("ALTER TABLE dice_logs ADD COLUMN IF NOT EXISTS formula TEXT")
                conn.commit()
                has_formula_column = True
            except psycopg2.Error:
                conn.rollback()

        with conn.cursor() as cur:
            # permission check: character belongs to campaign and user owns the character or campaign
            cur.execute("""
                SELECT 1
                FROM characters c JOIN campaigns cam
                ON c.campaign_id = cam.id
                WHERE c.id = %s
                AND cam.id = %s
                AND (c.owner_id = %s OR cam.created_by = %s)
            """, (character_id, campaign_id, user_id, user_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "permission denied"}), 400

            if has_formula_column:
                cur.execute("""
                    INSERT INTO dice_logs (campaign_id, character_id, roll_result, display_name, formula)
                    VALUES (%s, %s, %s, %s, %s)
                """, (campaign_id, character_id, total, display_name, normalized_formula,))
            else:
                cur.execute("""
                    INSERT INTO dice_logs (campaign_id, character_id, roll_result, display_name)
                    VALUES (%s, %s, %s, %s)
                """, (campaign_id, character_id, total, display_name,))
            conn.commit()

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT name FROM characters WHERE id = %s", (character_id,))
            character = cur.fetchone()

        if character is None:
            return jsonify({"error": "character not found"}), 404

        return jsonify({
            "name": character["name"],
            "display_name": display_name,
            "formula": normalized_formula,
            "roll_result": total,
            "created_at": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "unexpected error"}), 500


@app.template_filter('stat_position_class')
def stat_position_class(index):
    """Positions character's stats"""

    positions = [
        "top",         # 0: STR
        "top-right",   # 1: DEX
        "bottom-right",# 2: CON
        "bottom",      # 3: INT
        "bottom-left", # 4: WIS
        "top-left"     # 5: CHA
    ]
    return positions[index % len(positions)]


@app.template_filter('format_datetime')
def format_datetime(value):
    """Formats timestamps consistently across the UI."""

    if value is None:
        return ""

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y %H:%M")

    return str(value)


@app.template_filter('field_label')
def field_label(value):
    """Converts snake_case keys into readable labels."""

    if value is None:
        return ""

    return str(value).replace("_", " ").strip().title()


@app.errorhandler(403)
def forbidden(e):
    return error("forbidden", 403)


@app.errorhandler(404)
def page_not_found(e):
    return error("page not found", 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return error("method not allowed", 405)


@app.errorhandler(500)
def internal_server_error(e):
    return error("internal server error", 500)


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return error("session expired or invalid csrf token", 400)

