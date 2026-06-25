"""Import SRD spells into the app spell catalog."""

import json
import os
from pathlib import Path
from urllib.request import urlopen

import psycopg2
from dotenv import load_dotenv

root = Path(__file__).resolve().parent
load_dotenv(root.parent / ".env")


def load_json(source_candidates):
    for source in source_candidates:
        if isinstance(source, Path):
            if source.exists():
                with source.open("r", encoding="utf-8") as file:
                    return json.load(file)
        else:
            with urlopen(source) as response:
                return json.loads(response.read().decode("utf-8"))
    raise FileNotFoundError("No spell JSON source could be found")


def normalize_description(spell):
    description = spell.get("desc")
    if isinstance(description, list):
        return " ".join(description)
    if isinstance(description, str) and description.strip():
        return description.strip()
    return "No description"


def normalize_school(spell):
    school = spell.get("school")
    if isinstance(school, dict) and school.get("name"):
        return school["name"]
    if isinstance(school, str) and school.strip():
        return school.strip()
    return "Unknown"


json_sources = [
    root / "5e-SRD-Spells.json",
    "https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Spells.json",
]

spells = load_json(json_sources)

conn = psycopg2.connect(os.getenv("DB_URL") + "?sslmode=require")
cur = conn.cursor()

for spell in spells:
    name = spell.get("name")
    if not name:
        continue

    description = normalize_description(spell)
    level = spell.get("level", 0)
    school = normalize_school(spell)
    casting_time = spell.get("casting_time", "Unknown")
    spell_range = spell.get("range", "Unknown")
    components = ",".join(spell.get("components", [])) if isinstance(spell.get("components"), list) else str(spell.get("components", ""))
    duration = spell.get("duration", "Unknown")

    cur.execute(
        """
        INSERT INTO spell_catalog (name, description, level, school, casting_time, range, components, duration)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING
        """,
        (name, description, level, school, casting_time, spell_range, components, duration),
    )

conn.commit()
cur.close()
conn.close()
