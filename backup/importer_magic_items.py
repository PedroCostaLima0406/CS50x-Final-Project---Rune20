"""Import SRD magic items into the app item catalog."""

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
    raise FileNotFoundError("No magic item JSON source could be found")


def normalize_description(item):
    description = item.get("desc") or item.get("description")
    if isinstance(description, list):
        return " ".join(description)
    if isinstance(description, str) and description.strip():
        return description.strip()
    return "No description."


def normalize_item_type(item):
    category = item.get("equipment_category") or item.get("gear_category")
    if isinstance(category, dict) and category.get("name"):
        return category["name"]
    return "Magic Item"


json_sources = [
    root / "5e-SRD-Magic-Items.json",
    "https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en/5e-SRD-Magic-Items.json",
]

items = load_json(json_sources)

conn = psycopg2.connect(os.getenv("DB_URL") + "?sslmode=require")
cur = conn.cursor()

for item in items:
    name = item.get("name")
    if not name:
        continue

    description = normalize_description(item)
    item_type = normalize_item_type(item)
    rarity = item.get("rarity", {}).get("name", "Common") if isinstance(item.get("rarity"), dict) else str(item.get("rarity", "Common"))
    weight = item.get("weight") or 0
    value = item.get("cost", {}).get("quantity", 0) if isinstance(item.get("cost"), dict) else 0

    cur.execute(
        """
        INSERT INTO item_catalog (name, description, item_type, rarity, weight, value)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING
        """,
        (name, description, item_type, rarity, weight, value),
    )

conn.commit()
cur.close()
conn.close()
