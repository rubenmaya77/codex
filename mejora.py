import math
from collections import deque
from typing import List, Tuple, Dict, Optional

# ==============================================================================
# CONFIGURACIÓN Y CONSTANTES
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

# Memoria persistente para predicción de precios (se mantiene entre llamadas)
_PRICE_HISTORY = {}  # {item: [prices]}

# ==============================================================================
# PREDICCIÓN DE PRECIOS (simple media móvil)
# ==============================================================================

def update_price_history(obs):
    """Actualiza el historial con los precios actuales del mercado."""
    prices = obs.get("market", {}).get("prices", {})
    for item, price in prices.items():
        if item not in _PRICE_HISTORY:
            _PRICE_HISTORY[item] = []
        _PRICE_HISTORY[item].append(price)
        # Mantener solo los últimos 10 días para no crecer infinitamente
        if len(_PRICE_HISTORY[item]) > 10:
            _PRICE_HISTORY[item].pop(0)

def predict_price(item: str) -> float:
    """Predice el precio futuro (mañana) usando media de los últimos precios."""
    hist = _PRICE_HISTORY.get(item, [])
    if len(hist) < 2:
        return BASE_PRICES.get(item, 50)  # fallback
    # Media de los últimos 3 (si existen)
    recent = hist[-3:]
    return sum(recent) / len(recent)

# ==============================================================================
# DEMANDA DE TIENDAS
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

# ==============================================================================
# SELECCIÓN DE CULTIVO ÓPTIMO (con predicción y planificación)
# ==============================================================================

def evaluate_optimal_crop(obs, has_fertilizer=False):
    day = obs.get("day", 1)
    days_left = 30 - day
    player = obs["player"]
    money = obs["farms"][player]["money"]
    market_prices = obs["market"]["prices"]
    town_demands = get_high_demand_crops_from_town(obs)

    best_crop = "WHEAT"
    max_score = -float("inf")

    for crop, spec in CROP_SPECS.items():
        # Descartar si no hay tiempo suficiente para crecer
        if spec["growth_days"] >= days_left or money < spec["seed_cost"]:
            continue

        # Precio esperado (usar predicción si hay historial, sino precio actual)
        current_price = market_prices.get(crop, 1)
        predicted_price = predict_price(crop)  # puede ser más alto o bajo

        # Usar el precio predicho si es mayor que el actual (optimista), sino el actual
        effective_price = max(current_price, predicted_price * 0.9)  # un margen de seguridad

        # Rendimiento con/sin fertilizante
        base_yield = spec["base_yield"]
        if has_fertilizer:
            # Aplicar fertilizante solo si el cultivo es de alto valor y el retorno lo justifica
            if crop in ("MELON", "STRAWBERRY", "TOMATO"):
                yield_amount = base_yield * spec["fertilizer_mult"]
            else:
                yield_amount = base_yield  # no vale la pena gastar fertilizante
        else:
            yield_amount = base_yield

        # Bonificación por demanda de tienda
        demand_boost = 1.25 if crop in town_demands else 1.0

        # Beneficio neto total (no diario) para considerar si podemos completar el ciclo
        net_profit = (yield_amount * effective_price * demand_boost) - spec["seed_cost"]

        # Penalizar si el cultivo no se puede cosechar antes del día 30
        if day + spec["growth_days"] > 30:
            net_profit *= 0.5  # menos atractivo

        # Puntuación: beneficio neto / días de crecimiento (retorno diario)
        daily_return = net_profit / spec["growth_days"]

        # Bonus si la demanda es alta
        if crop in town_demands:
            daily_return *= 1.1

        if daily_return > max_score:
            max_score = daily_return
            best_crop = crop

    return best_crop

# ==============================================================================
# NAVEGACIÓN CON BFS (evita obstáculos)
# ==============================================================================

def get_neighbors(pos, tiles):
    x, y = pos
    height = len(tiles)
    width = len(tiles[0])
    dirs = [(0,1),(0,-1),(1,0),(-1,0)]
    result = []
    for dx, dy in dirs:
        nx, ny = x+dx, y+dy
        if 0 <= nx < width and 0 <= ny < height:
            tile = tiles[ny][nx]
            if isinstance(tile, dict):
                t_type = tile.get("type", "")
                # No podemos pisar maleza ni cultivos en crecimiento? Asumimos que sí, pero mejor evitar
                if t_type == "WEED":
                    continue
                # Si es un cultivo en etapa inmadura, no se puede pisar? Probablemente sí, pero evitamos para no dañar?
                # En el juego real, se puede pisar sobre cultivos, pero para simplificar, lo permitimos.
                pass
            result.append((nx, ny))
    return result

def bfs_path(start, target, tiles):
    """Devuelve el siguiente paso para ir de start a target evitando maleza."""
    if start == target:
        return None
    height = len(tiles)
    width = len(tiles[0])
    visited = set()
    queue = deque()
    queue.append((start, []))  # (pos, path)
    visited.add(start)

    while queue:
        (x, y), path = queue.popleft()
        if (x, y) == target:
            if path:
                return path[0]  # primer paso
            return None
        for nx, ny in get_neighbors((x, y), tiles):
            if (nx, ny) not in visited:
                visited.add((nx, ny))
                new_path = path + [((nx - x), (ny - y))]  # guardamos delta
                queue.append(((nx, ny), new_path))
    return None  # no hay camino

def get_next_step_towards(start, target, tiles):
    """Calcula el primer paso en dirección al objetivo usando BFS si es necesario."""
    if start == target:
        return ["PASS"]

    # Intento directo
    sx, sy = start
    tx, ty = target
    # Movimiento directo sin obstáculos
    if sx < tx:
        dx, dy = 1, 0
    elif sx > tx:
        dx, dy = -1, 0
    elif sy < ty:
        dx, dy = 0, 1
    else:
        dx, dy = 0, -1

    # Verificar si la casilla de destino directo es transitable
    nx, ny = sx + dx, sy + dy
    if 0 <= nx < len(tiles[0]) and 0 <= ny < len(tiles):
        tile = tiles[ny][nx]
        if isinstance(tile, dict) and tile.get("type") == "WEED":
            # Si hay maleza, usar BFS
            step = bfs_path(start, target, tiles)
            if step:
                dx, dy = step
                if dx == 1: return ["MOVE", "RIGHT"]
                if dx == -1: return ["MOVE", "LEFT"]
                if dy == 1: return ["MOVE", "DOWN"]
                if dy == -1: return ["MOVE", "UP"]
            return ["PASS"]
        else:
            # Movimiento directo posible
            if dx == 1: return ["MOVE", "RIGHT"]
            if dx == -1: return ["MOVE", "LEFT"]
            if dy == 1: return ["MOVE", "DOWN"]
            if dy == -1: return ["MOVE", "UP"]
    else:
        # Fuera de límites, usar BFS
        step = bfs_path(start, target, tiles)
        if step:
            dx, dy = step
            if dx == 1: return ["MOVE", "RIGHT"]
            if dx == -1: return ["MOVE", "LEFT"]
            if dy == 1: return ["MOVE", "DOWN"]
            if dy == -1: return ["MOVE", "UP"]
    return ["PASS"]

# ==============================================================================
# DECISIONES DEL AGRICULTOR (con prioridades y BFS)
# ==============================================================================

def decide_farmer_action(me, target_crop, seeds_stock, day, tiles):
    fx, fy = me["farmer"]
    height = len(tiles)
    width = len(tiles[0])

    # Escanear estado
    harvest_target = None
    water_target = None
    empty_target = None
    weed_target = None

    for y in range(height):
        for x in range(width):
            tile = tiles[y][x]
            if not isinstance(tile, dict):
                continue
            t_type = tile.get("type", "")
            if t_type == "WEED" and weed_target is None:
                weed_target = (x, y)
            elif t_type == "CROP" or "stage" in tile:
                if tile.get("stage") == "MATURE" or tile.get("harvestable", False):
                    if harvest_target is None:
                        harvest_target = (x, y)
                elif tile.get("water", 0) == 0 and water_target is None:
                    water_target = (x, y)
            elif t_type == "SOIL" and empty_target is None:
                empty_target = (x, y)

    current_tile = tiles[fy][fx]
    c_type = current_tile.get("type", "") if isinstance(current_tile, dict) else ""

    # Acciones en la casilla actual
    if c_type == "WEED":
        return ["CLEAN"]
    if c_type == "CROP" and current_tile.get("harvestable", False):
        return ["HARVEST"]
    if c_type == "SOIL" and seeds_stock > 0 and day < 28:
        return ["PLANT", target_crop]

    # Navegación priorizada
    if weed_target:
        return get_next_step_towards((fx, fy), weed_target, tiles)
    if harvest_target:
        return get_next_step_towards((fx, fy), harvest_target, tiles)
    if empty_target and seeds_stock > 0 and day < 28:
        return get_next_step_towards((fx, fy), empty_target, tiles)
    if water_target:
        return get_next_step_towards((fx, fy), water_target, tiles)

    return ["PASS"]

# ==============================================================================
# DECISIONES DE LAS MANOS (limpieza y riego)
# ==============================================================================

def decide_hands_actions(me, tiles):
    """Asigna tareas a las manos: una limpia maleza, la otra riega cultivos secos."""
    hands_actions = []
    # Posiciones de las manos
    hands_pos = me.get("hands", [])
    if not hands_pos:
        return []

    # Buscar maleza y cultivos secos
    weed_pos = None
    dry_crop_pos = None
    height = len(tiles)
    width = len(tiles[0])
    for y in range(height):
        for x in range(width):
            tile = tiles[y][x]
            if not isinstance(tile, dict):
                continue
            t_type = tile.get("type", "")
            if t_type == "WEED" and weed_pos is None:
                weed_pos = (x, y)
            elif t_type == "CROP" and tile.get("water", 0) == 0 and dry_crop_pos is None:
                dry_crop_pos = (x, y)

    # Para cada mano, asignar una tarea
    for idx, pos in enumerate(hands_pos):
        if idx == 0:  # Mano 1: limpiar maleza
            if weed_pos:
                if pos == weed_pos:
                    hands_actions.append(["CLEAN"])
                else:
                    hands_actions.append(get_next_step_towards(pos, weed_pos, tiles))
            else:
                hands_actions.append(["PASS"])
        else:  # Mano 2: regar cultivos secos
            if dry_crop_pos:
                if pos == dry_crop_pos:
                    hands_actions.append(["WATER"])
                else:
                    hands_actions.append(get_next_step_towards(pos, dry_crop_pos, tiles))
            else:
                hands_actions.append(["PASS"])
    return hands_actions

# ==============================================================================
# ÓRDENES DE VENTA (dinámicas con predicción)
# ==============================================================================

def get_drip_sell_orders(obs, min_price_ratio=0.4):
    sell_orders = []
    day = obs.get("day", 1)
    shed = obs.get("private", {}).get("shed", {})
    prices = obs.get("market", {}).get("prices", {})

    for item, qty in shed.items():
        if qty <= 0:
            continue
        current_price = prices.get(item, 1)
        base_price = BASE_PRICES.get(item, 50)

        # Fin de juego: liquidar todo
        if day >= 28:
            sell_orders.append(["sell", item, qty])
            continue

        # Precio promedio histórico
        hist = _PRICE_HISTORY.get(item, [])
        avg_price = sum(hist) / len(hist) if hist else base_price

        # Umbral dinámico: vender si el precio actual está por encima del promedio * factor
        # y también si necesitamos efectivo (si el dinero es bajo)
        money = obs["farms"][obs["player"]]["money"]
        if money < 100:
            # Necesitamos liquidez, vender aunque sea a menor precio
            sell_orders.append(["sell", item, min(qty, SAFE_SELL_LIMITS.get(item, 2) * 2)])
            continue

        # Venta normal
        min_acceptable = max(base_price * min_price_ratio, avg_price * 0.85)
        if current_price >= min_acceptable and current_price > 1:
            # Si el precio es excepcional (> 1.3 * avg), vender más
            if current_price > avg_price * 1.3:
                sell_qty = qty  # vender todo
            else:
                sell_qty = min(qty, SAFE_SELL_LIMITS.get(item, 2) * 3)
            if sell_qty > 0:
                sell_orders.append(["sell", item, sell_qty])

    return sell_orders

# ==============================================================================
# ÓRDENES DE COMPRA (semillas)
# ==============================================================================

def get_buy_orders(obs, target_crop):
    """Compra semillas del cultivo objetivo, ajustando cantidad según tierra disponible y dinero."""
    player = obs["player"]
    money = obs["farms"][player]["money"]
    day = obs.get("day", 1)
    if day >= 28:
        return []

    # Contar casillas de suelo vacías y libres de maleza
    tiles = obs["farms"][player]["tiles"]
    empty_soil = 0
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and tile.get("type") == "SOIL":
                empty_soil += 1

    # También considerar cultivos en crecimiento que se cosecharán pronto (días restantes)
    # Pero simplificamos: comprar solo si hay suelo vacío
    if empty_soil == 0:
        return []

    spec = CROP_SPECS.get(target_crop, {})
    seed_cost = spec.get("seed_cost", 10)

    # ¿Cuántas semillas podemos comprar? No más de empty_soil ni más de lo que el dinero permita
    max_buy = min(empty_soil, money // seed_cost)
    # Limitar a un máximo razonable para no gastar todo
    budget_fraction = 0.6  # usar 60% del dinero
    max_by_budget = int((money * budget_fraction) // seed_cost)
    qty = min(max_buy, max_by_budget)

    if qty > 0:
        # También verificar si ya tenemos semillas en inventario
        seeds = obs.get("private", {}).get("seeds", {})
        current_stock = seeds.get(target_crop, 0)
        # No comprar si ya tenemos suficientes para plantar todo el suelo vacío
        if current_stock >= empty_soil:
            return []
        # Ajustar para no exceder el suelo vacío
        qty = min(qty, empty_soil - current_stock)
        if qty > 0:
            return [["buy_seed", target_crop, qty]]
    return []

# ==============================================================================
# AGENTE PRINCIPAL
# ==============================================================================

def agent(obs):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    day = obs.get("day", 1)

    # Actualizar historial de precios
    update_price_history(obs)

    # Inventario
    shed_inventory = private.get("shed", {})
    seeds_inventory = private.get("seeds", {})
    has_fertilizer = shed_inventory.get("FERTILIZER", 0) > 0

    # Elegir cultivo objetivo
    target_crop = evaluate_optimal_crop(obs, has_fertilizer=has_fertilizer)

    # Preparar órdenes de mercado
    market_orders = []

    # 1. Vender
    sell_orders = get_drip_sell_orders(obs, min_price_ratio=0.4)
    market_orders.extend(sell_orders)

    # 2. Comprar semillas
    buy_orders = get_buy_orders(obs, target_crop)
    market_orders.extend(buy_orders)

    # Limitar a 10 órdenes por turno
    market_orders = market_orders[:10]

    # Decisiones del agricultor
    seeds_stock = seeds_inventory.get(target_crop, 0)
    tiles = me["tiles"]
    farmer_action = decide_farmer_action(me, target_crop, seeds_stock, day, tiles)

    # Decisiones de las manos
    hands_actions = decide_hands_actions(me, tiles)

    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market_orders
    }