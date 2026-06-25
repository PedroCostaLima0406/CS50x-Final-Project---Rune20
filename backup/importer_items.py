"""Import SRD equipment into the app item catalog."""

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
    raise FileNotFoundError("No equipment JSON source could be found")


def get_equipment_type(item):
    category = item.get("equipment_category") or item.get("gear_category")
    if isinstance(category, dict) and category.get("name"):
        return category["name"]

    categories = item.get("equipment_categories")
    if isinstance(categories, list) and categories:
        first_category = categories[0]
        if isinstance(first_category, dict) and first_category.get("name"):
            return first_category["name"]

    for field in ("weapon_category", "armor_category", "tool_category", "vehicle_category"):
        value = item.get(field)
        if value:
            return str(value)

    return "Other"


def get_description(item):
    description = item.get("desc") or item.get("description")
    if isinstance(description, list):
        return " ".join(description)
    if isinstance(description, str) and description.strip():
        return description.strip()
    return "No description."


json_sources = [
    root / "5e-SRD-Equipment.json",
    "https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2024/en/5e-SRD-Equipment.json",
]

items = load_json(json_sources)

conn = psycopg2.connect(os.getenv("DB_URL") + "?sslmode=require")
cur = conn.cursor()

for item in items:
    name = item.get("name")
    if not name:
        continue

    description = get_description(item)
    item_type = get_equipment_type(item)
    rarity = item.get("rarity", {}).get("name", "Common") if isinstance(item.get("rarity"), dict) else str(item.get("rarity", "Common"))
    weight = item.get("weight") or 0
    cost = item.get("cost", {}) if isinstance(item.get("cost"), dict) else {}
    value = cost.get("quantity", 0) if isinstance(cost, dict) else 0

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
