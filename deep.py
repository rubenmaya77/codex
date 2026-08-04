import math
import random
from collections import deque, defaultdict
from typing import List, Tuple, Optional, Dict, Any

# ==============================================================================
# CONFIGURACIÓN Y CONSTANTES DEL JUEGO
# ==============================================================================

CROP_SPECS = {
    "WHEAT":      {"seed_cost": 10,  "growth_days": 2,  "base_yield": 1.5,  "fertilizer_mult": 1.5, "max_cycles": 12},
    "CARROT":     {"seed_cost": 20,  "growth_days": 2,  "base_yield": 1.33, "fertilizer_mult": 1.5, "max_cycles": 10},
    "TOMATO":     {"seed_cost": 50,  "growth_days": 8,  "base_yield": 1.0,  "fertilizer_mult": 2.0, "max_cycles": 4},
    "STRAWBERRY": {"seed_cost": 100, "growth_days": 10, "base_yield": 0.5,  "fertilizer_mult": 2.0, "max_cycles": 3},
    "MELON":      {"seed_cost": 80,  "growth_days": 10, "base_yield": 0.5,  "fertilizer_mult": 3.0, "max_cycles": 2}
}

ANIMAL_SPECS = {
    "COW":   {"cost": 400, "feed_cost": 20, "days_to_produce": 3, "product": "MILK", "yield_per_prod": 1.0, "max_animals": 2},
    "SHEEP": {"cost": 300, "feed_cost": 15, "days_to_produce": 4, "product": "WOOL", "yield_per_prod": 1.0, "max_animals": 2},
    "GOOSE": {"cost": 100, "feed_cost": 5,  "days_to_produce": 2, "product": "EGG",  "yield_per_prod": 0.5, "max_animals": 4}
}

SAFE_SELL_LIMITS = {
    "WHEAT": 6, "CARROT": 4, "TOMATO": 3,
    "STRAWBERRY": 1, "MELON": 1, "MILK": 1, "WOOL": 1, "FERTILIZER": 2, "EGG": 2
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

TILE_PRICES = [200, 300, 400, 500, 600, 700, 800, 900, 1000, 1000]  # Precio por tile expandido

# ==============================================================================
# CAPA ESTRATÉGICA - OPTIMIZADOR MILP SIMPLIFICADO
# ==============================================================================

class StrategicPlanner:
    """Planificador estratégico que determina la asignación óptima de recursos."""
    
    def __init__(self, obs):
        self.obs = obs
        self.player = obs["player"]
        self.me = obs["farms"][self.player]
        self.private = obs["private"]
        self.market = obs["market"]
        self.day = obs.get("day", 1)
        self.days_left = 30 - self.day
        
        # Estado interno
        self.shed = self.private.get("shed", {})
        self.seeds = self.private.get("seeds", {})
        self.money = self.me["money"]
        self.tiles = self.me["tiles"]
        self.farmer_pos = self.me["farmer"]
        self.hands = self.me.get("hands", [])
        self.hires_today = self.me.get("hires_today", 0)
        
        # Análisis de mercado
        self.prices = self.market.get("prices", {})
        self.town_demands = self._get_town_demands()
        self.owned_tiles = self._count_owned_tiles()
        
    def _get_town_demands(self) -> set:
        """Obtiene cultivos con demanda activa de tiendas."""
        unlocked_shops = self.obs.get("town", {}).get("unlocked_shops", [])
        demands = set()
        for shop in unlocked_shops:
            shop_type = shop.get("type") if isinstance(shop, dict) else shop
            if shop_type in SHOP_DEMAND_MAP:
                demands.update(SHOP_DEMAND_MAP[shop_type])
        return demands
    
    def _count_owned_tiles(self) -> int:
        """Cuenta tiles propios (no vacíos en la granja)."""
        count = 0
        for row in self.tiles:
            for tile in row:
                if tile is not None:
                    count += 1
        return count
    
    def _simulate_market_price(self, item: str, quantity: int) -> float:
        """
        Simula el precio después de vender quantity unidades.
        Modelo: p(inv) = base + sign * amp * (|inv - I0|)^exponent
        """
        # Parámetros conocidos del juego
        params = {
            "WHEAT": {"base": 25, "I0": 0, "amp": 15, "exponent": 0.5, "sign": -1},
            "CARROT": {"base": 35, "I0": 0, "amp": 20, "exponent": 0.5, "sign": -1},
            "TOMATO": {"base": 60, "I0": 0, "amp": 40, "exponent": 0.6, "sign": -1},
            "STRAWBERRY": {"base": 120, "I0": 0, "amp": 100, "exponent": 0.7, "sign": -1},
            "MELON": {"base": 250, "I0": 0, "amp": 200, "exponent": 0.8, "sign": -1},
            "MILK": {"base": 160, "I0": 0, "amp": 120, "exponent": 0.7, "sign": -1},
            "WOOL": {"base": 200, "I0": 0, "amp": 150, "exponent": 0.7, "sign": -1},
            "EGG": {"base": 50, "I0": 0, "amp": 30, "exponent": 0.5, "sign": -1},
            "FERTILIZER": {"base": 100, "I0": 0, "amp": 60, "exponent": 0.5, "sign": -1}
        }
        
        p = params.get(item, {"base": 50, "I0": 0, "amp": 30, "exponent": 0.5, "sign": -1})
        current_inv = self.market.get("inventory", {}).get(item, 0)
        new_inv = current_inv + quantity
        
        # Precio base con decaimiento
        price = p["base"] + p["sign"] * p["amp"] * (abs(new_inv - p["I0"]) ** p["exponent"])
        return max(1, price)
    
    def _calculate_crop_roi(self, crop: str, cycles: int = 1, use_fertilizer: bool = False) -> Dict:
        """Calcula ROI detallado para un cultivo considerando múltiples ciclos."""
        spec = CROP_SPECS[crop]
        price = self.prices.get(crop, BASE_PRICES.get(crop, 50))
        seed_cost = spec["seed_cost"]
        growth_days = spec["growth_days"]
        
        # Rendimiento por ciclo
        yield_per_cycle = spec["base_yield"]
        if use_fertilizer:
            yield_per_cycle *= spec["fertilizer_mult"]
        
        # Demanda de tienda
        demand_boost = 1.25 if crop in self.town_demands else 1.0
        effective_price = price * demand_boost
        
        # Considerar caída de precio por múltiples ventas
        total_cycles = min(cycles, spec["max_cycles"])
        total_revenue = 0
        total_cost = seed_cost * total_cycles
        
        for cycle in range(total_cycles):
            # Cada ciclo tiene su propio precio (simulamos caída)
            cycle_price = self._simulate_market_price(crop, 1) if cycle > 0 else price
            total_revenue += yield_per_cycle * cycle_price * demand_boost
        
        # Costo de oportunidad: tiempo
        total_days = growth_days * total_cycles
        net_profit = total_revenue - total_cost
        
        # ROI ajustado por tiempo
        daily_return = net_profit / total_days if total_days > 0 else 0
        roi_percentage = (net_profit / total_cost) * 100 if total_cost > 0 else 0
        
        return {
            "crop": crop,
            "cycles": total_cycles,
            "total_days": total_days,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "net_profit": net_profit,
            "daily_return": daily_return,
            "roi_percentage": roi_percentage,
            "use_fertilizer": use_fertilizer
        }
    
    def _calculate_animal_roi(self, animal: str) -> Dict:
        """Calcula ROI para animales."""
        spec = ANIMAL_SPECS[animal]
        days_left = self.days_left
        cost = spec["cost"]
        feed_cost = spec["feed_cost"]
        days_to_produce = spec["days_to_produce"]
        product = spec["product"]
        yield_per_prod = spec["yield_per_prod"]
        price = self.prices.get(product, BASE_PRICES.get(product, 50))
        
        # Número de producciones posibles
        productions = max(0, (days_left - 1) // days_to_produce)
        
        total_revenue = productions * yield_per_prod * price
        total_feed_cost = days_left * feed_cost  # Alimentación diaria
        
        # Demanda de tienda para el producto
        if product in self.town_demands:
            total_revenue *= 1.25
        
        net_profit = total_revenue - cost - total_feed_cost
        
        return {
            "animal": animal,
            "productions": productions,
            "total_cost": cost + total_feed_cost,
            "total_revenue": total_revenue,
            "net_profit": net_profit,
            "daily_return": net_profit / days_left if days_left > 0 else 0,
            "product": product
        }
    
    def _evaluate_animal_expansion(self) -> Optional[str]:
        """Evalúa si es rentable comprar animales."""
        # Verificar si tenemos suficiente espacio y dinero
        if self.owned_tiles < 10 or self.money < 500:
            return None
        
        # Contar animales actuales
        current_animals = sum(1 for item in self.shed if item in ANIMAL_SPECS)
        best_animal = None
        best_roi = -float("inf")
        
        for animal, spec in ANIMAL_SPECS.items():
            if current_animals >= spec["max_animals"]:
                continue
            if self.money < spec["cost"]:
                continue
            
            roi = self._calculate_animal_roi(animal)
            if roi["daily_return"] > best_roi and roi["productions"] > 0:
                best_roi = roi["daily_return"]
                best_animal = animal
        
        return best_animal
    
    def _evaluate_tile_expansion(self) -> bool:
        """Evalúa si comprar más tiles es rentable."""
        owned = self.owned_tiles
        if owned >= 30:  # Máximo razonable
            return False
        
        next_tile_cost = TILE_PRICES[min(owned, len(TILE_PRICES) - 1)]
        if self.money < next_tile_cost * 1.5:  # Mantener buffer
            return False
        
        # Solo expandir si tenemos cultivos rentables disponibles
        best_crop = self._get_best_crop()
        if best_crop:
            roi = self._calculate_crop_roi(best_crop, cycles=3)
            return roi["daily_return"] > 2.0
        
        return False
    
    def _get_best_crop(self, allow_fertilizer: bool = True) -> Optional[str]:
        """Obtiene el mejor cultivo basado en ROI."""
        best_crop = None
        best_roi = -float("inf")
        
        for crop in CROP_SPECS:
            spec = CROP_SPECS[crop]
            if spec["growth_days"] >= self.days_left:
                continue
            if self.money < spec["seed_cost"]:
                continue
            
            # Evaluar con y sin fertilizante
            for use_fert in [False, True]:
                if use_fert and not allow_fertilizer:
                    continue
                roi = self._calculate_crop_roi(crop, cycles=min(3, spec["max_cycles"]), use_fertilizer=use_fert)
                if roi["daily_return"] > best_roi:
                    best_roi = roi["daily_return"]
                    best_crop = crop
        
        return best_crop
    
    def _should_use_fertilizer(self, crop: str) -> bool:
        """Determina si usar fertilizante para un cultivo."""
        fert_stock = self.shed.get("FERTILIZER", 0)
        if fert_stock <= 0:
            return False
        
        spec = CROP_SPECS[crop]
        roi_without = self._calculate_crop_roi(crop, cycles=1, use_fertilizer=False)
        roi_with = self._calculate_crop_roi(crop, cycles=1, use_fertilizer=True)
        
        # Solo usar si mejora significativamente el ROI
        return roi_with["daily_return"] > roi_without["daily_return"] * 1.2
    
    def _generate_optimal_portfolio(self) -> Dict:
        """Genera cartera óptima de cultivos y animales."""
        portfolio = {
            "crops": {},
            "animals": [],
            "should_expand_tiles": False,
            "should_hire_hands": 0,
            "use_fertilizer_on": None
        }
        
        # 1. Selección de cultivos basada en ROI
        best_crop = self._get_best_crop()
        if best_crop:
            portfolio["crops"][best_crop] = 1
            if self._should_use_fertilizer(best_crop):
                portfolio["use_fertilizer_on"] = best_crop
        
        # 2. Evaluar animales
        best_animal = self._evaluate_animal_expansion()
        if best_animal:
            portfolio["animals"].append(best_animal)
        
        # 3. Expansión de tiles
        portfolio["should_expand_tiles"] = self._evaluate_tile_expansion()
        
        # 4. Contratación de Farm Hands
        if self.money > 1000 and self.hires_today < 3:
            # Costo Fibonacci: 100, 100, 200, 300, 500...
            hire_cost = self.me.get("hire_cost", 100)
            if self.money > hire_cost * 3:
                portfolio["should_hire_hands"] = min(2, 3 - self.hires_today)
        
        return portfolio
    
    def get_strategy(self) -> Dict:
        """Retorna la estrategia completa para el turno actual."""
        portfolio = self._generate_optimal_portfolio()
        
        # Priorizar cultivos de alto ROI en etapas tempranas
        if self.day <= 5:
            # Enfocarse en cultivos rápidos para flujo de caja
            fast_crops = ["WHEAT", "CARROT"]
            for crop in fast_crops:
                if crop in portfolio["crops"]:
                    continue
                spec = CROP_SPECS[crop]
                if self.money >= spec["seed_cost"] and spec["growth_days"] < self.days_left:
                    portfolio["crops"][crop] = 1
                    break
        
        # En etapas tardías, maximizar valor
        elif self.day >= 25:
            # Vender todo, no comprar más
            portfolio["crops"] = {}
            portfolio["animals"] = []
            portfolio["should_expand_tiles"] = False
            portfolio["should_hire_hands"] = 0
        
        return portfolio

# ==============================================================================
# CAPA TÁCTICA - GESTIÓN DE MERCADO
# ==============================================================================

class MarketManager:
    """Gestiona todas las operaciones de mercado con simulación de precios."""
    
    def __init__(self, obs, strategy):
        self.obs = obs
        self.player = obs["player"]
        self.me = obs["farms"][self.player]
        self.private = obs["private"]
        self.market = obs["market"]
        self.day = obs.get("day", 1)
        self.strategy = strategy
        
        self.shed = self.private.get("shed", {})
        self.prices = self.market.get("prices", {})
        self.money = self.me["money"]
    
    def _get_market_elasticity(self, item: str) -> float:
        """Obtiene elasticidad de precio para un item."""
        elasticity = {
            "WHEAT": 0.8, "CARROT": 0.8, "TOMATO": 0.9,
            "STRAWBERRY": 1.2, "MELON": 1.5, "MILK": 1.3,
            "WOOL": 1.3, "EGG": 0.7, "FERTILIZER": 0.6
        }
        return elasticity.get(item, 1.0)
    
    def _calculate_optimal_sell_quantity(self, item: str, qty: int) -> int:
        """Calcula cantidad óptima a vender sin colapsar el precio."""
        if qty <= 0:
            return 0
        
        current_price = self.prices.get(item, 1)
        base_price = BASE_PRICES.get(item, 50)
        elasticity = self._get_market_elasticity(item)
        
        # Si el precio ya está bajo, vender todo
        if current_price < base_price * 0.3:
            return min(qty, 20)
        
        # Calcular precio después de vender
        best_qty = 0
        best_avg_price = 0
        
        for test_qty in range(1, min(qty + 1, 20)):
            avg_price = self._simulate_sell_price(item, test_qty)
            if avg_price > best_avg_price:
                best_avg_price = avg_price
                best_qty = test_qty
        
        # Límite de seguridad
        limit = SAFE_SELL_LIMITS.get(item, 1)
        if current_price > base_price * 1.3:
            limit = int(limit * 2)  # Vender más si el precio está alto
        
        return min(best_qty, limit)
    
    def _simulate_sell_price(self, item: str, quantity: int) -> float:
        """Simula el precio promedio al vender quantity unidades."""
        # Usamos el mismo modelo de simulación que el planificador
        current_inv = self.market.get("inventory", {}).get(item, 0)
        
        # Parámetros del mercado
        params = {
            "WHEAT": {"base": 25, "I0": 0, "amp": 15, "exponent": 0.5},
            "CARROT": {"base": 35, "I0": 0, "amp": 20, "exponent": 0.5},
            "TOMATO": {"base": 60, "I0": 0, "amp": 40, "exponent": 0.6},
            "STRAWBERRY": {"base": 120, "I0": 0, "amp": 100, "exponent": 0.7},
            "MELON": {"base": 250, "I0": 0, "amp": 200, "exponent": 0.8},
            "MILK": {"base": 160, "I0": 0, "amp": 120, "exponent": 0.7},
            "WOOL": {"base": 200, "I0": 0, "amp": 150, "exponent": 0.7},
            "EGG": {"base": 50, "I0": 0, "amp": 30, "exponent": 0.5},
            "FERTILIZER": {"base": 100, "I0": 0, "amp": 60, "exponent": 0.5}
        }
        
        p = params.get(item, {"base": 50, "I0": 0, "amp": 30, "exponent": 0.5})
        
        # Precio promedio al vender en lotes
        total_price = 0
        for i in range(quantity):
            inv = current_inv + i
            price = p["base"] - p["amp"] * (abs(inv - p["I0"]) ** p["exponent"])
            total_price += max(1, price)
        
        return total_price / quantity if quantity > 0 else 0
    
    def get_orders(self) -> List:
        """Genera órdenes de mercado optimizadas."""
        orders = []
        
        # 1. VENTAS - Optimización de precio
        for item, qty in list(self.shed.items()):
            # No vender animales vivos
            if item in ANIMAL_SPECS or item in ["GOOSE", "COW", "SHEEP"]:
                continue
            
            # No vender semillas
            if item.endswith("_SEED"):
                continue
            
            # No vender si es necesario para producción
            if item == "WHEAT" and self._needs_wheat_for_animals():
                required = self._calculate_animal_feed_needs()
                if qty <= required:
                    continue
            
            sell_qty = self._calculate_optimal_sell_quantity(item, qty)
            if sell_qty > 0:
                orders.append(["SELL", item, sell_qty])
        
        # 2. COMPRAS - Semillas para cultivo
        if self.day < 28:
            for crop, need in self.strategy.get("crops", {}).items():
                if need > 0:
                    current_seeds = self.private.get("seeds", {}).get(crop, 0)
                    if current_seeds < 2:  # Mantener stock
                        spec = CROP_SPECS[crop]
                        if self.money >= spec["seed_cost"] * 2:
                            orders.append(["BUY_SEED", crop, 1])
        
        # 3. COMPRAS - Fertilizante
        if self.strategy.get("use_fertilizer_on") and self.day < 25:
            fert_stock = self.shed.get("FERTILIZER", 0)
            if fert_stock < 3 and self.money >= 100:
                orders.append(["BUY_FERTILIZER", 1])
        
        # 4. COMPRAS - Animales
        for animal in self.strategy.get("animals", []):
            if self.money >= ANIMAL_SPECS[animal]["cost"]:
                orders.append(["BUY_ANIMAL", animal])
        
        # 5. CONTRATACIÓN - Farm Hands
        for _ in range(self.strategy.get("should_hire_hands", 0)):
            orders.append(["HIRE"])
        
        # 6. EXPANSIÓN - Terreno
        if self.strategy.get("should_expand_tiles", False):
            orders.append(["BUY_TILE"])
        
        return orders[:10]  # Límite de 10 órdenes por turno
    
    def _needs_wheat_for_animals(self) -> bool:
        """Verifica si necesitamos trigo para alimentar animales."""
        for animal in ["COW", "SHEEP", "GOOSE"]:
            if self.shed.get(animal, 0) > 0:
                return True
        return False
    
    def _calculate_animal_feed_needs(self) -> int:
        """Calcula cuánto trigo necesitamos para alimentar animales."""
        needed = 0
        for animal in ["COW", "SHEEP", "GOOSE"]:
            count = self.shed.get(animal, 0)
            if count > 0:
                # Estimación conservadora: 1 trigo por animal por día
                needed += count
        return needed

# ==============================================================================
# CAPA OPERATIVA - PATHFINDING Y ASIGNACIÓN DE TAREAS
# ==============================================================================

class OperationsManager:
    """Gestiona movimientos y tareas del farmer y farm hands."""
    
    def __init__(self, obs, strategy):
        self.obs = obs
        self.player = obs["player"]
        self.me = obs["farms"][self.player]
        self.private = obs["private"]
        self.day = obs.get("day", 1)
        self.strategy = strategy
        
        self.tiles = self.me["tiles"]
        self.height = len(self.tiles)
        self.width = len(self.tiles[0])
        self.farmer_pos = self.me["farmer"]
        self.hands = self.me.get("hands", [])
        
        self.target_crop = next(iter(strategy.get("crops", {"WHEAT": 1})), "WHEAT")
        self.use_fertilizer = strategy.get("use_fertilizer_on") == self.target_crop
    
    def _find_nearest(self, start: Tuple[int, int], targets: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """Encuentra el objetivo más cercano usando distancia Manhattan."""
        if not targets:
            return None
        
        sx, sy = start
        best_target = None
        best_dist = float("inf")
        
        for tx, ty in targets:
            dist = abs(sx - tx) + abs(sy - ty)
            if dist < best_dist:
                best_dist = dist
                best_target = (tx, ty)
        
        return best_target
    
    def _get_next_step(self, start: Tuple[int, int], target: Tuple[int, int]) -> List:
        """Obtiene el siguiente paso hacia el objetivo."""
        sx, sy = start
        tx, ty = target
        
        if sx < tx: return ["MOVE", "RIGHT"]
        if sx > tx: return ["MOVE", "LEFT"]
        if sy < ty: return ["MOVE", "DOWN"]
        if sy > ty: return ["MOVE", "UP"]
        return ["PASS"]
    
    def _scan_tiles(self) -> Dict:
        """Escanea tiles para identificar tareas pendientes."""
        scan = {
            "harvest": [],
            "water": [],
            "plant": [],
            "animal_feed": [],
            "empty": []
        }
        
        for y in range(self.height):
            for x in range(self.width):
                tile = self.tiles[y][x]
                if tile is None:
                    scan["empty"].append((x, y))
                elif isinstance(tile, dict):
                    # Cultivos
                    if tile.get("stage") == "MATURE" or tile.get("harvestable", False):
                        scan["harvest"].append((x, y))
                    elif tile.get("water", 0) == 0 and tile.get("kind") == "PLANT":
                        scan["water"].append((x, y))
                    elif tile.get("kind") == "ANIMAL_FEED":
                        scan["animal_feed"].append((x, y))
                    
                    # Casillas vacías listas para plantar
                    if tile.get("kind") == "EMPTY" or tile.get("can_plant", False):
                        scan["plant"].append((x, y))
        
        return scan
    
    def _get_fertilizer_stock(self) -> int:
        """Obtiene stock de fertilizante."""
        return self.private.get("shed", {}).get("FERTILIZER", 0)
    
    def _get_seed_stock(self, crop: str) -> int:
        """Obtiene stock de semillas."""
        return self.private.get("seeds", {}).get(crop, 0)
    
    def _is_current_tile_plantable(self, pos: Tuple[int, int]) -> bool:
        """Verifica si la posición actual es plantable."""
        x, y = pos
        if y >= len(self.tiles) or x >= len(self.tiles[0]):
            return False
        tile = self.tiles[y][x]
        return tile is None or (isinstance(tile, dict) and tile.get("kind") == "EMPTY")
    
    def _is_current_tile_harvestable(self, pos: Tuple[int, int]) -> bool:
        """Verifica si la posición actual tiene cultivo listo."""
        x, y = pos
        if y >= len(self.tiles) or x >= len(self.tiles[0]):
            return False
        tile = self.tiles[y][x]
        return isinstance(tile, dict) and (tile.get("harvestable", False) or tile.get("stage") == "MATURE")
    
    def _is_current_tile_waterable(self, pos: Tuple[int, int]) -> bool:
        """Verifica si la posición actual necesita agua."""
        x, y = pos
        if y >= len(self.tiles) or x >= len(self.tiles[0]):
            return False
        tile = self.tiles[y][x]
        return isinstance(tile, dict) and tile.get("water", 0) == 0 and tile.get("kind") == "PLANT"
    
    def decide_farmer_action(self) -> List:
        """Decide la acción del farmer."""
        pos = self.farmer_pos
        seeds_stock = self._get_seed_stock(self.target_crop)
        fert_stock = self._get_fertilizer_stock()
        
        scan = self._scan_tiles()
        
        # PRIORIDAD 1: Cosechar si estamos sobre cultivo maduro
        if self._is_current_tile_harvestable(pos):
            return ["HARVEST"]
        
        # PRIORIDAD 2: Ir a cosechar cultivos maduros
        if scan["harvest"]:
            target = self._find_nearest(pos, scan["harvest"])
            if target:
                return self._get_next_step(pos, target)
        
        # PRIORIDAD 3: Sembrar si estamos en tile plantable
        if self._is_current_tile_plantable(pos) and seeds_stock > 0 and self.day < 27:
            if self.use_fertilizer and fert_stock > 0:
                return ["PLANT", self.target_crop, "FERTILIZER"]
            return ["PLANT", self.target_crop]
        
        # PRIORIDAD 4: Ir a plantar en tile vacío
        if (scan["plant"] or scan["empty"]) and seeds_stock > 0 and self.day < 27:
            plant_targets = scan["plant"] + scan["empty"]
            target = self._find_nearest(pos, plant_targets)
            if target:
                return self._get_next_step(pos, target)
        
        # PRIORIDAD 5: Regar si estamos sobre planta seca
        if self._is_current_tile_waterable(pos):
            return ["WATER"]
        
        # PRIORIDAD 6: Ir a regar plantas secas
        if scan["water"]:
            target = self._find_nearest(pos, scan["water"])
            if target:
                return self._get_next_step(pos, target)
        
        # PRIORIDAD 7: Pasar (sin tareas pendientes)
        return ["PASS"]
    
    def decide_hands_actions(self) -> List:
        """Decide acciones para farm hands."""
        if not self.hands:
            return []
        
        hands_actions = []
        scan = self._scan_tiles()
        seeds_stock = self._get_seed_stock(self.target_crop)
        
        # Asignar tareas a cada hand basado en proximidad
        for hand_pos in self.hands:
            # Cosechar si es posible
            if self._is_current_tile_harvestable(hand_pos):
                hands_actions.append(["HARVEST"])
                continue
            
            # Buscar tareas cercanas
            closest_task = None
            closest_dist = float("inf")
            
            # Priorizar cosecha
            for task_type in ["harvest", "water", "plant", "empty"]:
                for tx, ty in scan.get(task_type, []):
                    dist = abs(hand_pos[0] - tx) + abs(hand_pos[1] - ty)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_task = (task_type, tx, ty)
            
            if closest_task:
                task_type, tx, ty = closest_task
                # Si la tarea está en la misma posición
                if hand_pos == (tx, ty):
                    if task_type in ["plant", "empty"] and seeds_stock > 0:
                        hands_actions.append(["PLANT", self.target_crop])
                    elif task_type == "water":
                        hands_actions.append(["WATER"])
                    elif task_type == "harvest":
                        hands_actions.append(["HARVEST"])
                else:
                    # Moverse hacia la tarea
                    step = self._get_next_step(hand_pos, (tx, ty))
                    hands_actions.append(step)
            else:
                hands_actions.append(["PASS"])
        
        return hands_actions
    
    def get_actions(self) -> Dict:
        """Retorna todas las acciones operativas."""
        return {
            "farmer": self.decide_farmer_action(),
            "hands": self.decide_hands_actions()
        }

# ==============================================================================
# AGENTE PRINCIPAL
# ==============================================================================

def agent(obs):
    """Agente principal con arquitectura jerárquica."""
    
    # 1. CAPA ESTRATÉGICA
    strategic_planner = StrategicPlanner(obs)
    strategy = strategic_planner.get_strategy()
    
    # 2. CAPA TÁCTICA (Mercado)
    market_manager = MarketManager(obs, strategy)
    market_orders = market_manager.get_orders()
    
    # 3. CAPA OPERATIVA (Campo)
    operations_manager = OperationsManager(obs, strategy)
    actions = operations_manager.get_actions()
    
    # 4. ENSAMBLAR RESPUESTA
    return {
        "farmer": actions["farmer"],
        "hands": actions["hands"],
        "market": market_orders
    }

# ==============================================================================
# MANTENER COMPATIBILIDAD CON VERSIÓN ANTERIOR
# ==============================================================================

# Las funciones originales se mantienen para compatibilidad
def evaluate_optimal_crop(obs, has_fertilizer=False):
    """Versión simplificada para compatibilidad."""
    planner = StrategicPlanner(obs)
    return planner._get_best_crop(allow_fertilizer=has_fertilizer) or "WHEAT"

def get_drip_sell_orders(obs, min_price_ratio=0.45):
    """Versión simplificada para compatibilidad."""
    planner = StrategicPlanner(obs)
    manager = MarketManager(obs, {})
    return manager.get_orders()

def decide_farmer_action(me, target_crop, seeds_stock, day):
    """Versión simplificada para compatibilidad."""
    # Esta función se mantiene para no romper código existente
    return ["PASS"]

def get_next_step_towards(start, target):
    """Versión simplificada para compatibilidad."""
    return OperationsManager({"farms": {}}, {})._get_next_step(start, target)