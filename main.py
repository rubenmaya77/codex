import math
from collections import deque

# ==============================================================================
# CONFIGURACIÓN Y CONSTANTES DEL JUEGO
# ==============================================================================

CROP_SPECS = {
    "WHEAT":      {"seed_cost": 10,  "growth_days": 2,  "base_yield": 1.5,  "fertilizer_mult": 1.5},
    "CARROT":     {"seed_cost": 20,  "growth_days": 2,  "base_yield": 1.33, "fertilizer_mult": 1.5},
    "TOMATO":     {"seed_cost": 50,  "growth_days": 8,  "base_yield": 1.0,  "fertilizer_mult": 2.0},
    "STRAWBERRY": {"seed_cost": 100, "growth_days": 10, "base_yield": 0.5,  "fertilizer_mult": 2.0},
    "MELON":      {"seed_cost": 80,  "growth_days": 10, "base_yield": 0.5,  "fertilizer_mult": 3.0}
}

SAFE_SELL_LIMITS = {
    "WHEAT": 6, "CARROT": 4, "TOMATO": 3,
    "STRAWBERRY": 1, "MELON": 1, "MILK": 1, "WOOL": 1, "FERTILIZER": 2
}

BASE_PRICES = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60,
    "STRAWBERRY": 120, "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100
}

SHOP_DEMAND_MAP = {
    "BAKERY": ["WHEAT"],
    "PIZZERIA": ["WHEAT", "TOMATO"],
    "ICE_CREAM": ["MILK", "STRAWBERRY"],
    "SOUP_KITCHEN": ["CARROT", "TOMATO"],
    "TEXTILE_MILL": ["WOOL"]
}

# ==============================================================================
# LÓGICA ECONÓMICA Y DE MERCADO
# ==============================================================================

def get_high_demand_crops_from_town(obs):
    unlocked_shops = obs.get("town", {}).get("unlocked_shops", [])
    target_crops = set()
    for shop in unlocked_shops:
        shop_type = shop.get("type") if isinstance(shop, dict) else shop
        if shop_type in SHOP_DEMAND_MAP:
            for crop in SHOP_DEMAND_MAP[shop_type]:
                target_crops.add(crop)
    return target_crops

def evaluate_optimal_crop(obs, has_fertilizer=False):
    day = obs.get("day", 1)
    days_left = 30 - day
    player = obs["player"]
    money = obs["farms"][player]["money"]
    market_prices = obs["market"]["prices"]
    town_demands = get_high_demand_crops_from_town(obs)

    best_crop = "WHEAT"
    max_daily_return = -float("inf")

    for crop, spec in CROP_SPECS.items():
        if spec["growth_days"] >= days_left or money < spec["seed_cost"]:
            continue

        price = market_prices.get(crop, 1)
        yield_amount = spec["base_yield"] * (spec["fertilizer_mult"] if has_fertilizer else 1.0)
        demand_boost = 1.25 if crop in town_demands else 1.0

        net_daily_return = ((yield_amount * price * demand_boost) - spec["seed_cost"]) / spec["growth_days"]

        if net_daily_return > max_daily_return:
            max_daily_return = net_daily_return
            best_crop = crop

    return best_crop

def get_drip_sell_orders(obs, min_price_ratio=0.45):
    sell_orders = []
    day = obs.get("day", 1)
    shed = obs.get("private", {}).get("shed", {})
    prices = obs.get("market", {}).get("prices", {})

    for item, qty in shed.items():
        if qty <= 0:
            continue
        current_price = prices.get(item, 1)
        base_price = BASE_PRICES.get(item, 50)

        if day >= 28:
            sell_orders.append(["SELL", item, min(qty, 10)])
            continue

        min_acceptable = math.ceil(base_price * min_price_ratio)
        if current_price >= min_acceptable and current_price > 1:
            limit = SAFE_SELL_LIMITS.get(item, 1)
            if current_price > base_price * 1.2:
                limit = int(limit * 1.5)
            sell_qty = min(qty, limit)
            if sell_qty > 0:
                sell_orders.append(["SELL", item, sell_qty])

    return sell_orders

# ==============================================================================
# SISTEMA DE NAVEGACIÓN Y OPERACIONES EN CAMPO (PATHFINDING)
# ==============================================================================

def get_next_step_towards(start, target):
    """Calcula el primer paso en dirección a las coordenadas del objetivo."""
    sx, sy = start
    tx, ty = target

    if sx < tx: return ["MOVE", "RIGHT"]
    if sx > tx: return ["MOVE", "LEFT"]
    if sy < ty: return ["MOVE", "DOWN"]
    if sy > ty: return ["MOVE", "UP"]
    return ["PASS"]

def decide_farmer_action(me, target_crop, seeds_stock, day):
    fx, fy = me["farmer"]
    tiles = me["tiles"]
    height = len(tiles)
    width = len(tiles[0])

    harvest_target = None
    water_target = None
    empty_target = None

    # Escanear el terreno para priorizar tareas
    for y in range(height):
        for x in range(width):
            tile = tiles[y][x]
            if tile is not None and isinstance(tile, dict):
                # Prioridad 1: Cosechar cultivos listos
                if tile.get("stage") == "MATURE" or tile.get("harvestable", False):
                    harvest_target = (x, y)
                    break
                # Prioridad 2: Regar plantas secas
                elif tile.get("water", 0) == 0 and water_target is None:
                    water_target = (x, y)
            elif tile is None and empty_target is None:
                # Prioridad 3: Buscar casilla vacía para sembrar
                empty_target = (x, y)

    # 1. Si estamos sobre un cultivo maduro -> Cosechar
    current_tile = tiles[fy][fx]
    if current_tile and isinstance(current_tile, dict) and current_tile.get("harvestable", False):
        return ["HARVEST"]

    # 2. Si hay algo para cosechar en la granja -> Moverse hacia allá
    if harvest_target:
        return get_next_step_towards((fx, fy), harvest_target)

    # 3. Si estamos en casilla vacía con semillas -> Plantar
    if current_tile is None and seeds_stock > 0 and day < 28:
        return ["PLANT", target_crop]

    # 4. Si hay casillas vacías y tenemos semillas -> Moverse a sembrar
    if empty_target and seeds_stock > 0 and day < 28:
        return get_next_step_towards((fx, fy), empty_target)

    # 5. Si hay plantas secas -> Moverse a regar
    if water_target:
        return get_next_step_towards((fx, fy), water_target)

    return ["PASS"]

# ==============================================================================
# AGENTE PRINCIPAL (ENTRY POINT PARA KAGGLE)
# ==============================================================================

def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    day = obs.get("day", 1)

    shed_inventory = private.get("shed", {})
    seeds_inventory = private.get("seeds", {})
    has_fertilizer = shed_inventory.get("FERTILIZER", 0) > 0

    target_crop = evaluate_optimal_crop(obs, has_fertilizer=has_fertilizer)

    # 1. Mercado (Compras / Ventas)
    market_orders = get_drip_sell_orders(obs, min_price_ratio=0.45)
    
    if day < 28:
        current_seed_stock = seeds_inventory.get(target_crop, 0)
        target_seed_cost = CROP_SPECS[target_crop]["seed_cost"]
        if current_seed_stock == 0 and me["money"] >= target_seed_cost:
            market_orders.append(["BUY_SEED", target_crop, 1])

    # 2. Decisiones de Campo (Movimiento, Cosecha, Siembra)
    seeds_stock = seeds_inventory.get(target_crop, 0)
    farmer_action = decide_farmer_action(me, target_crop, seeds_stock, day)

    return {
        "farmer": farmer_action,
        "hands": [],
        "market": market_orders[:10]
    }