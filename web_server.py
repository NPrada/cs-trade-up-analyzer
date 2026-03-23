"""

CS Trade Up Analyzer

web_server.py

Flask web server that exposes the trade-up database via a REST API
and serves the single-page web UI.

"""

import sys
import os
import json
import pathlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, jsonify, request, send_from_directory
import db_handler
from models.weapon_classifiers import (
    WeaponIntToStr,
    rarity_int_to_game_rarity,
    wear_int_to_enum,
    wear_int_enum_to_str_enum,
    get_valid_wears,
    str_to_wear,
    game_rarity_to_rarity,
)

app = Flask(__name__)
WORKING_PATH = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))

WEAR_NAMES = {0: "Factory New", 1: "Minimal Wear", 2: "Field-Tested", 3: "Well-Worn", 4: "Battle-Scarred"}
RARITY_NAMES = {0: "Consumer", 1: "Industrial", 2: "Mil-Spec", 3: "Restricted", 4: "Classified", 5: "Covert", 6: "Exceedingly Rare"}


def estimate_wear(min_wear: float, max_wear: float, average_wear: float) -> float:
    estimate = ((max_wear - min_wear) * average_wear) + min_wear
    if estimate > max_wear:
        estimate = max_wear
    return estimate


def skin_to_dict(skin):
    return {
        "id": skin.internal_id,
        "name": skin.skin_name,
        "weapon": WeaponIntToStr.get(skin.weapon_type, "Unknown"),
        "rarity": skin.rarity,
        "rarity_name": RARITY_NAMES.get(skin.rarity, "Unknown"),
        "min_wear": skin.min_wear,
        "max_wear": skin.max_wear,
        "crate_id": skin.crate_id,
    }


def tradeup_to_dict(tradeup):
    result = {
        "id": tradeup.internal_id,
        "goal_skin": skin_to_dict(tradeup.goal_skin),
        "goal_wear": tradeup.goal_wear,
        "goal_wear_name": WEAR_NAMES.get(tradeup.goal_wear, "Unknown"),
        "goal_rarity": tradeup.goal_rarity,
        "goal_rarity_name": RARITY_NAMES.get(tradeup.goal_rarity, "Unknown"),
        "goal_weapon": WeaponIntToStr.get(tradeup.goal_weapon, "Unknown"),
        "skin_1_count": tradeup.skin_1_count,
        "skin_2_count": 10 - tradeup.skin_1_count,
        "chance": tradeup.chance,
        "roi_10": tradeup.roi_10,
        "profit_10": tradeup.profit_10,
        "roi_100": tradeup.roi_100,
        "profit_100": tradeup.profit_100,
        "price_warning": tradeup.price_warning,
        "skin_1_price": tradeup.skin_1_price,
        "skin_2_price": tradeup.skin_2_price,
        "skin_1_max_wear": tradeup.skin_1_max_wear,
        "skin_2_max_wear": tradeup.skin_2_max_wear,
        "skin_1_margin": tradeup.skin_1_margin,
        "skin_2_margin": tradeup.skin_2_margin,
        "input_price": tradeup.input_price,
        "skin_1": skin_to_dict(tradeup.skin_1),
        "skin_2": skin_to_dict(tradeup.skin_2) if tradeup.skin_2 else None,
    }

    # Attach goal skin market price
    goal_price_data = db_handler.get_prices(tradeup.goal_skin.internal_id, tradeup.goal_wear)
    if goal_price_data:
        result["goal_price"] = float(goal_price_data[0][0]) * 0.95
        result["possible_profit"] = round(result["goal_price"] - tradeup.input_price, 2)
    else:
        result["goal_price"] = None
        result["possible_profit"] = None

    return result


@app.route("/")
def index():
    return send_from_directory(os.path.join(WORKING_PATH, "web"), "index.html")


@app.route("/api/tradeups")
def list_tradeups():
    # Parse filters from query string
    rarity = request.args.get("rarity", type=int)
    wear = request.args.get("wear", type=int)
    weapon = request.args.get("weapon", type=int)
    min_wear = request.args.get("min_wear", default=0.001, type=float)
    max_wear = request.args.get("max_wear", default=1.0, type=float)
    min_price = request.args.get("min_price", default=0.0, type=float)
    max_price = request.args.get("max_price", default=9999999999.0, type=float)
    roi_min = request.args.get("roi_min", default=0.0, type=float)
    roi_max = request.args.get("roi_max", default=9999999999.0, type=float)
    max_margin = request.args.get("max_margin", default=1.0, type=float)
    sort_by = request.args.get("sort_by", default="chance")
    page = request.args.get("page", default=0, type=int)

    # Validate sort_by to prevent SQL injection
    allowed_sorts = {"chance", "roi_10", "profit_10", "input_price"}
    if sort_by not in allowed_sorts:
        sort_by = "chance"

    criteria = [
        "((? <= skin_1_max_wear AND ? >= skin_1_max_wear) AND (? <= skin_2_max_wear AND ? >= skin_2_max_wear))",
        "input_price >= ? AND input_price <= ?",
        "? <= roi_10 AND ? >= roi_10",
        "(? <= skin_1_margin AND ? <= skin_2_margin)",
    ]
    values = [min_wear, max_wear, min_wear, max_wear, min_price, max_price, roi_min, roi_max, max_margin, max_margin]

    if rarity is not None:
        criteria.append("goal_rarity = ?")
        values.append(rarity)

    if wear is not None:
        criteria.append("goal_wear = ?")
        values.append(wear)

    if weapon is not None:
        criteria.append("goal_weapon = ?")
        values.append(weapon)

    criteria_str = " AND ".join(criteria)
    offset = page * 10

    cursor = db_handler.WORKING_DB.cursor()
    cursor.execute(
        f"SELECT internal_id FROM tradeups WHERE {criteria_str} ORDER BY {sort_by} DESC LIMIT 10 OFFSET ?",
        tuple(values + [offset]),
    )
    rows = cursor.fetchall()

    cursor.execute(f"SELECT COUNT(*) FROM tradeups WHERE {criteria_str}", tuple(values))
    total = cursor.fetchone()[0]
    cursor.close()

    tradeups = []
    for row in rows:
        t = db_handler.get_tradeup_by_id(row[0])
        if t:
            tradeups.append(tradeup_to_dict(t))

    return jsonify({"tradeups": tradeups, "total": total, "page": page, "per_page": 10})


@app.route("/api/tradeups/<int:tradeup_id>")
def get_tradeup(tradeup_id):
    tradeup = db_handler.get_tradeup_by_id(tradeup_id)
    if tradeup is None:
        return jsonify({"error": "Trade-up not found"}), 404

    result = tradeup_to_dict(tradeup)

    # Build profit breakdown
    case_1_skins = db_handler.get_skins_by_crate_and_rarity(tradeup.skin_1.crate_id, tradeup.goal_rarity)
    case_2_skins = []
    if tradeup.skin_2:
        case_2_skins = db_handler.get_skins_by_crate_and_rarity(tradeup.skin_2.crate_id, tradeup.goal_rarity)

    total_tickets = (len(case_1_skins) * tradeup.skin_1_count) + (len(case_2_skins) * (10 - tradeup.skin_1_count))
    average_wear = (
        (tradeup.skin_1_max_wear * tradeup.skin_1_count) + ((10 - tradeup.skin_1_count) * tradeup.skin_2_max_wear)
    ) / 10

    case_1_obj = db_handler.get_crate_from_internal(tradeup.skin_1.crate_id)
    case_2_obj = db_handler.get_crate_from_internal(tradeup.skin_2.crate_id) if tradeup.skin_2 else None

    def build_skin_outcomes(skins, count):
        outcomes = []
        for skin in skins:
            wear_est = estimate_wear(skin.min_wear, skin.max_wear, average_wear)
            valid_wears = get_valid_wears(skin.min_wear, wear_est)
            wear_str = valid_wears[-1] if valid_wears else "Unknown"
            wear_int = str_to_wear.get(wear_str, None)
            wear_int_val = wear_int.value if wear_int else 4

            prices = db_handler.get_prices(skin.internal_id, wear_int_val)
            if prices:
                price = float(prices[0][0]) * 0.95
                profit = price - tradeup.input_price
            else:
                price = None
                profit = None

            chance = (count / total_tickets * 100) if total_tickets > 0 else 0

            outcomes.append({
                "skin": skin_to_dict(skin),
                "wear": str(wear_str),
                "price": price,
                "profit": profit,
                "chance": chance,
            })
        return outcomes

    breakdown = []
    if case_1_obj:
        breakdown.append({
            "crate_name": case_1_obj.crate_name,
            "crate_id": case_1_obj.internal_id,
            "outcomes": build_skin_outcomes(case_1_skins, tradeup.skin_1_count),
        })
    if case_2_obj:
        breakdown.append({
            "crate_name": case_2_obj.crate_name,
            "crate_id": case_2_obj.internal_id,
            "outcomes": build_skin_outcomes(case_2_skins, 10 - tradeup.skin_1_count),
        })

    profit_chance = sum(
        o["chance"]
        for group in breakdown
        for o in group["outcomes"]
        if o["profit"] is not None and o["profit"] > 0
    )

    result["breakdown"] = breakdown
    result["profit_chance"] = profit_chance
    result["loss_chance"] = 100 - profit_chance

    return jsonify(result)


@app.route("/api/weapons")
def get_weapons():
    return jsonify(WeaponIntToStr)


@app.route("/api/skins/search")
def search_skins():
    query = request.args.get("q", "").lower()
    weapon = request.args.get("weapon", type=int)
    results = db_handler.get_skins_by_search_name(query, weapon)[:25]
    return jsonify(results)


def main():
    db_path_file = os.path.join(WORKING_PATH, "data/.db-path")
    if os.path.exists(db_path_file):
        with open(db_path_file, "r") as f:
            db_path = f.readline().strip()
    else:
        db_path = os.path.join(WORKING_PATH, "data/cs_tradeup.db")

    print("Connecting to database...")
    db_handler.establish_db(db_path)
    print("Starting web server at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()
