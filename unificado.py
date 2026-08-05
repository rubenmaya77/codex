
import heapq
from collections import deque

# ==============================================================================
# 1. CONSTANTES Y CONFIGURACIÓN DEL JUEGO
# ==============================================================================

BASE_PRICES = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60,
    "STRAWBERRY": 120, "MELON": 250, "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100
}

CROP_SPECS = {
    "WHEAT":      {"seed_cost": 10, "growth_days": 2},
    "CARROT":     {"seed_cost": 20, "growth_days": 2},
    "TOMATO":     {"seed_cost": 50, "growth_days": 8},
    "STRAWBERRY": {"seed_cost": 100, "growth_days": 10},
    "MELON":      {"seed_cost": 80, "growth_days": 10}
}

ANIMAL_STRUCTURES = {
    "GOOSE": "COOP",
    "COW": "PASTURE",
    "SHEEP": "PASTURE"
}

# ==============================================================================
# 2. MÓDULO DE PATHFINDING Y NAVEGACIÓN MULTI-TRABAJADOR
# ==============================================================================

def get_direction(current, next_node):
    """Convierte el paso de coordenadas en un comando de dirección oficial."""
    cx, cy = current
    nx, ny = next_node
    
    if nx > cx: return "EAST"
    if nx < cx: return "WEST"
    if ny > cy: return "SOUTH"
    if ny < cy: return "NORTH"
    return "PASS"

def a_star_path(start, target, width=10, height=10, obstacles=None):
    """Calcula la ruta más corta evitando obstáculos (otros peones/edificios)."""
    if obstacles is None:
        obstacles = set()
        
    if start == target:
        return []

    open_set = []
    heapq.heappush(open_set, (0, start))
    
    came_from = {}
    g_score = {start: 0}
    f_score = {start: abs(start[0] - target[0]) + abs(start[1] - target[1])}
    
    while open_set:
        _, current = heapq.heappop(open_set)
        
        if current == target:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path
            
        cx, cy = current
        neighbors = [(cx, cy-1), (cx, cy+1), (cx-1, cy), (cx+1, cy)]
        
        for nx, ny in neighbors:
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in obstacles:
                tentative_g = g_score[current] + 1
                neighbor = (nx, ny)
                
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f = tentative_g + abs(nx - target[0]) + abs(ny - target[1])
                    f_score[neighbor] = f
                    heapq.heappush(open_set, (f, neighbor))
                    
    return []

def get_closest_target_bfs(start, targets, width=10, height=10, obstacles=None):
    """Busca el objetivo más cercano que no haya sido asignado a otro trabajador."""
    if obstacles is None:
        obstacles = set()
        
    if start in targets:
        return start
        
    queue = deque([start])
    visited = set([start])
    
    while queue:
        cx, cy = queue.popleft()
        
        for nx, ny in [(cx, cy-1), (cx, cy+1), (cx-1, cy), (cx+1, cy)]:
            if 0 <= nx < width and 0 <= ny < height:
                neighbor = (nx, ny)
                if neighbor not in visited and neighbor not in obstacles:
                    if neighbor in targets:
                        return neighbor
                    visited.add(neighbor)
                    queue.append(neighbor)
                    
    return None

# ==============================================================================
# 3. LÓGICA DE ACCIONES DE CAMPO (AGRICULTURA Y GANADERÍA)
# ==============================================================================

def solve_worker_action(worker_pos, me, seeds_inventory, shed_inventory, day, assigned_targets, worker_obstacles):
    """Genera la orden óptima para un trabajador (Granjero o Peón) evitando duplicidad de metas."""
    wx, wy = worker_pos
    tiles = me["tiles"]
    current_pos = (wx, wy)
    
    feed_targets = set()
    harvest_targets = set()
    water_targets = set()
    fertilizer_targets = set()
    weed_targets = set()
    empty_targets = set()
    empty_coop_targets = set()

    has_wheat = shed_inventory.get("WHEAT", 0) > 0 or seeds_inventory.get("WHEAT", 0) > 0

    # 1. Mapeo exhaustivo del estado de los 100 tiles
    for y in range(10):
        for x in range(10):
            pos = (x, y)
            if pos in assigned_targets:
                continue  # Ignorar objetivos ya asignados a otro peón este turno
                
            tile = tiles[y][x]
            if tile is None:
                empty_targets.add(pos)
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "WEED":
                    weed_targets.add(pos)
                elif kind == "PLANT":
                    if tile.get("yield_units", 0) > 0:
                        harvest_targets.add(pos)
                    elif not tile.get("watered_today", False):
                        water_targets.add(pos)
                elif kind in ("COOP", "PASTURE"):
                    animal = tile.get("animal")
                    if animal is not None:
                        # Prioridad de cuidado animal: Cosecha > Alimento > Fertilizante
                        if tile.get("yield_units", 0) > 0:
                            harvest_targets.add(pos)
                        elif not tile.get("fed_today", False) and has_wheat:
                            feed_targets.add(pos)
                        elif tile.get("fertilizer_available", False):
                            fertilizer_targets.add(pos)
                    else:
                        empty_coop_targets.add(pos)

    # 2. Ejecución inmediata si el trabajador ya está parado sobre la casilla de acción
    current_tile = tiles[wy][wx]
    if isinstance(current_tile, dict):
        kind = current_tile.get("kind")
        if kind == "WEED":
            return ["DIG"], current_pos
        elif kind == "PLANT":
            if current_tile.get("yield_units", 0) > 0:
                return ["HARVEST"], current_pos
            elif not current_tile.get("watered_today", False):
                return ["WATER"], current_pos
        elif kind in ("COOP", "PASTURE"):
            animal = current_tile.get("animal")
            if animal is not None:
                if current_tile.get("yield_units", 0) > 0:
                    return ["HARVEST"], current_pos
                elif not current_tile.get("fed_today", False) and has_wheat:
                    return ["FEED"], current_pos
                elif current_tile.get("fertilizer_available", False):
                    return ["COLLECT_FERTILIZER"], current_pos
            else:
                if shed_inventory.get("GOOSE", 0) > 0:
                    return ["PLACE", "GOOSE"], current_pos

    elif current_tile is None:
        # Construir gallinero si compramos un ganso y no hay coop libre
        if shed_inventory.get("GOOSE", 0) > 0 and not empty_coop_targets and day < 25:
            return ["BUILD_COOP"], current_pos
        elif seeds_inventory.get("WHEAT", 0) > 0 and day < 28:
            return ["PLANT"], current_pos

    # 3. Selección y navegación hacia el objetivo más cercano
    # Jerarquía: Maleza > Alimentar Animales > Cosechar > Regar > Recoger Fertilizante > Sembrar
    best_target = None
    if weed_targets:
        best_target = get_closest_target_bfs(current_pos, weed_targets, obstacles=worker_obstacles)
    elif feed_targets:
        best_target = get_closest_target_bfs(current_pos, feed_targets, obstacles=worker_obstacles)
    elif harvest_targets:
        best_target = get_closest_target_bfs(current_pos, harvest_targets, obstacles=worker_obstacles)
    elif water_targets:
        best_target = get_closest_target_bfs(current_pos, water_targets, obstacles=worker_obstacles)
    elif fertilizer_targets:
        best_target = get_closest_target_bfs(current_pos, fertilizer_targets, obstacles=worker_obstacles)
    elif empty_targets and seeds_inventory.get("WHEAT", 0) > 0 and day < 28:
        best_target = get_closest_target_bfs(current_pos, empty_targets, obstacles=worker_obstacles)

    if best_target:
        path = a_star_path(current_pos, best_target, obstacles=worker_obstacles)
        if path:
            next_step = path[0]
            return [get_direction(current_pos, next_step)], best_target

    return ["PASS"], None

# ==============================================================================
# 4. ENTRY POINT PRINCIPAL DE KAGGRICULTURE
# ==============================================================================

def agent(obs):
    """Agente competitivo principal integrado con peones y ganadería."""
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    day = obs.get("day", 0)
    
    market_orders = []
    shed_inventory = private.get("shed", {})
    seeds_inventory = private.get("seeds", {})
    prices = obs.get("market", {}).get("prices", {})
    money = me["money"]

    # A. Mercado: Ventas
    for item, qty in shed_inventory.items():
        if qty > 0 and item not in ("GOOSE", "COW", "SHEEP"):
            base = BASE_PRICES.get(item, 10)
            curr = prices.get(item, 0)
            if curr >= base * 0.9 or day >= 28:
                market_orders.append(["SELL", item, qty])

    # B. Mercado: Compras de Insumos y Ganado
    wheat_seeds = seeds_inventory.get("WHEAT", 0)
    if wheat_seeds < 8 and money >= 80 and day < 28:
        market_orders.append(["BUY_SEED", "WHEAT", 8])

    # Comprar 1 Ganso a partir del Día 3 si hay presupuesto y alimento suficiente
    if day >= 3 and day < 22 and money >= 400 and shed_inventory.get("GOOSE", 0) == 0:
        market_orders.append(["BUY_ANIMAL", "GOOSE", 1])

    # C. Mercado: Contratación de Peones (HIRE)
    # Contratar 1 peón si el capital supera los 500 y no se ha contratado hoy
    hires_today = me.get("hires_today", 0)
    if hires_today == 0 and money >= 500 and day < 27:
        market_orders.append(["HIRE"])

    # D. Asignación de Tareas para Granjero y Peones
    assigned_targets = set()
    worker_obstacles = set()
    
    # Lista de todas las unidades activas en el campo
    all_workers = [tuple(me["farmer"])] + [tuple(h) for h in me.get("hands", [])]
    for w in all_workers:
        worker_obstacles.add(w)

    # 1. Resolver acción del agricultor principal
    farmer_action, target_used = solve_worker_action(
        all_workers[0], me, seeds_inventory, shed_inventory, day, assigned_targets, worker_obstacles
    )
    if target_used:
        assigned_targets.add(target_used)

    # 2. Resolver acciones para los peones contratados
    hands_actions = []
    for hand_pos in all_workers[1:]:
        hand_act, target_used = solve_worker_action(
            hand_pos, me, seeds_inventory, shed_inventory, day, assigned_targets, worker_obstacles
        )
        if target_used:
            assigned_targets.add(target_used)
        hands_actions.append(hand_act)

    return {
        "farmer": farmer_action,
        "hands": hands_actions,
        "market": market_orders[:10]  # Límite estricto del API
    }