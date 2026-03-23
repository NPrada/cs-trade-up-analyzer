"""

CS Trade Up Analyzer

src/market_handler.py

Developed by Keagan Bowman
Copyright 2024

Steam endpoint interaction scripts. Meant to gather pricing information and find the cheapest skins in a case.

"""

from models.weapon_classifiers import WearsToInt, WeaponIntToStr, get_valid_wears, wear_int_enum_to_str_enum
import requests as req
import db_handler
import time
import json


def find_cheapest() -> None:
    # gather all crates
    crates = db_handler.get_all_crates()

    # loop through all crates
    for crate in crates:
        # gather skins based on rarity in crate
        skins_by_rarity = {}
        for skin in db_handler.get_skins_by_crate(crate.internal_id):
            try:
                skins_by_rarity[skin.rarity].append(skin)
            except KeyError:
                skins_by_rarity[skin.rarity] = [skin]

        # loop through each rarity
        for rarity in skins_by_rarity.keys():
            # loop through each wear rating
            for wear in range(WearsToInt.FACTORYNEW.value, WearsToInt.BATTLESCARRED.value + 1):
                cheapest = None
                lowest_price = None

                # loop through all skins in this rarity
                for skin in skins_by_rarity[rarity]:
                    # attempt to get price from the DB
                    prices = db_handler.get_prices(skin.internal_id, wear)

                    # if there is no valid price, skip this
                    if prices is None:
                        continue

                    total = 0
                    current_price = 0

                    for i in prices:
                        price, count, _ = i

                        total += count
                        current_price = price

                        if count >= 10:
                            break

                    # check if this price is lower than the current lowest
                    if lowest_price is None or (current_price is not None and total >= 10 and current_price < lowest_price):
                        cheapest = skin
                        lowest_price = current_price

                # if the cheapest isn't none, we add it to the db
                if cheapest is not None:
                    db_handler.add_cheapest(crate.internal_id, cheapest.internal_id, rarity, wear, lowest_price)

    db_handler.WORKING_DB.commit()


def get_prices(steam_creds: tuple[str, str]) -> None:
    search_url = "https://steamcommunity.com/market/search/render/"

    # build lookup: hash_name -> (skin_id, wear_int)
    skins = db_handler.get_all_skins()
    hash_to_skin = {}
    for skin in skins:
        for wear in get_valid_wears(skin.min_wear, skin.max_wear, as_int=True):
            weapon = WeaponIntToStr[int(skin.weapon_type)]
            if skin.skin_name == "Lab Rats":
                weapon = "Souvenir " + weapon
            hash_name = f"{weapon} | {skin.skin_name.strip()} ({wear_int_enum_to_str_enum[wear].value})"
            hash_to_skin[hash_name] = (skin.internal_id, wear.value)

    print(f"Looking for {len(hash_to_skin)} skin+wear combinations...")

    start = 0
    page_size = 100
    total_count = None
    matched = 0

    while total_count is None or start < total_count:
        params = {"query": "", "appid": 730, "start": start, "count": page_size, "norender": 1}

        data = None
        retry_delay = 30
        while data is None:
            try:
                r = req.get(url=search_url, params=params, timeout=30)
                data = r.json()
            except Exception:
                data = None
            if data is None:
                print(f"\t> Rate limited or bad response, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)

        if total_count is None:
            total_count = data.get("total_count", 0)
            print(f"Total market items: {total_count} (~{-(-total_count // page_size)} pages)")

        results = data.get("results", [])
        if not results:
            if start >= (total_count or 0):
                break
            print(f"\t> Empty results page at start={start}, skipping...")
            start += page_size
            continue

        for item in results:
            hash_name = item.get("hash_name", "")
            if hash_name not in hash_to_skin:
                continue

            skin_id, wear = hash_to_skin[hash_name]
            # sell_price is in cents (USD), sell_listings is total listing count
            sell_price = item.get("sell_price", 0) / 100.0
            sell_listings = item.get("sell_listings", 0)

            # store as [[price, count, ""]] to match the format expected by find_cheapest
            price_data = json.dumps([[sell_price, sell_listings, ""]])
            buy_data = json.dumps([])

            if db_handler.get_prices(skin_id, wear) is None:
                db_handler.add_price(skin_id, wear, -1, price_data, buy_data, commit=True)
            else:
                db_handler.update_price_by_skin(skin_id, wear, price_data, buy_data, commit=True)

            matched += 1

        page = start // page_size + 1
        print(f"\t> Page {page}: scanned {min(start + page_size, total_count)}/{total_count}, matched {matched}/{len(hash_to_skin)}")

        start += page_size

        if start < total_count:
            time.sleep(3.5)
