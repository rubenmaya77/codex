import math
from typing import List, Tuple, Optional, Dict, Any

# ==============================================================================
# CONFIGURACION Y CONSTANTES DEL JUEGO
# (alineadas con las reglas oficiales de Kaggriculture)
# ==============================================================================

CROP_SPECS = {
    #                 seed   ciclo   yield     yield     ongoing
    #                 cost   (dias)  sin fert  con fert
    "WHEAT":      {"seed_cost": 10,  "cycle_days": 5,  "yield_unfert": 4, "yield_fert": 6, "ongoing": False},
    "CARROT":     {"seed_cost": 20,  "cycle_days": 4,  "yield_unfert": 3, "yield_fert": 4, "ongoing": False},
    "TOMATO":     {"seed_cost": 50,  "cycle_days": 12, "yield_unfert": 4, "yield_fert": 8, "ongoing": True},
    "STRAWBERRY": {"seed_cost": 100, "cycle_days": 17, "yield_unfert": 4, "yield_fert": 8, "ongoing": True},
    "MELON":      {"seed_cost": 80,  "cycle_days": 11, "yield_unfert": 6, "yield_fert": 6, "ongoing": False},
}

# NOTA: "max_animals" es un tope ESTRATEGICO propio del agente, no una regla
# del juego (el juego no limita cuantos animales puedes tener, solo el
# espacio de tierra/coops/pastures). El "Max Yield" de la tabla oficial es
# max_held: el tope de producto SIN COSECHAR por animal, no un limite de
# cantidad. FIX: los valores de COW/SHEEP (antes 2) no correspondian a nada
# en las reglas; se alinean aqui con max_held (4/6/6) como referencia
# razonable, pero se puede subir mas si el terreno/economia lo justifica.
ANIMAL_SPECS = {
    "GOOSE": {"cost": 300, "days_to_produce": 1, "product": "EGG",  "yield_per_prod": 1.0, "max_animals": 4},
    "COW":   {"cost": 400, "days_to_produce": 2, "product": "MILK", "yield_per_prod": 1.0, "max_animals": 6},
    "SHEEP": {"cost": 500, "days_to_produce": 3, "product": "WOOL", "yield_per_prod": 1.0, "max_animals": 6},
}

# Parametros reales de la curva de precios del mercado (ver reglas de la competencia)
MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "I0": 10000, "T": 400, "below_func": "sqrt", "below_target": 0.80, "above_func": "log",  "above_target": 0.20},
    "CARROT":     {"base": 35,  "I0": 10000, "T": 450, "below_func": "log",  "below_target": 0.20, "above_func": "sqrt", "above_target": 0.70},
    "TOMATO":     {"base": 60,  "I0": 10000, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "sqrt", "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": 10000, "T": 300, "below_func": "log",  "below_target": 0.20, "above_func": "sq",   "above_target": 3.60},
    "EGG":        {"base": 50,  "I0": 10000, "T": 332, "below_func": "linear", "below_target": 0.40, "above_func": "log", "above_target": 0.20},
    "MILK":       {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt", "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": 10000, "T": 105, "below_func": "log",  "below_target": 0.20, "above_func": "sq",   "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

BASE_PRICES = {k: v["base"] for k, v in MARKET_PARAMS.items()}

# Dias hasta la primera cosecha posible (aunque yield_units ya muestre >0 antes de
# esa fecha, el juego no permite cosechar hasta cumplir esta edad del cultivo).
FIRST_YIELD_DAY = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}

# Ventana de edad (dias desde plantado) en la que aplicar FERTILIZE realmente
# suma: la bonificacion dura solo 3 dias desde que se aplica, asi que
# fertilizar antes de que la planta entre en su ventana de bonificacion
# natural desperdicia el fertilizante ($100) sin ningun beneficio (el timer
# de 3 dias se agota antes de que la ventana empiece). Aplicar demasiado
# tarde (cerca de la decadencia) tambien lo desperdicia.
FERTILIZE_WINDOW = {
    "WHEAT": (2, 4), "CARROT": (2, 3), "MELON": (4, 8),
    "TOMATO": (6, 10), "STRAWBERRY": (8, 15),
}

# Costo de comprar cada cuadrante adicional de tierra (2do, 3ro, 4to)
LAND_PRICES = [1000, 2000, 4000]

SHOP_DEMAND_MAP = {
    "BAKERY":        ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}


# ==============================================================================
# SIMULADOR DE PRECIOS DE MERCADO (formula oficial del juego)
# ==============================================================================

def _shape(func: str, x: float) -> float:
    x = max(x, 0)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1 + x)
    if func == "log10":
        return math.log10(1 + x)
    return x


def _fib_hire_cost(n: int, mult: float = 1.0) -> float:
    """Costo de contratar la (n+1)-esima mano hoy. fib empieza 1,1,2,3,5,8,...
    n = cantidad de contrataciones ya hechas hoy (hires_today)."""
    a, b = 1, 1
    for _ in range(max(n, 0)):
        a, b = b, a + b
    return mult * a


def price_at(item: str, inv: float) -> int:
    """Precio de un item dado el inventario actual del mercado."""
    p = MARKET_PARAMS.get(item)
    if not p:
        return 1
    base, I0, T = p["base"], p["I0"], p["T"]
    if inv < I0:
        f, target = p["below_func"], p["below_target"]
        denom = _shape(f, T)
        amp = (target * base / denom) if denom else 0
        price = base + amp * _shape(f, I0 - inv)
    elif inv > I0:
        f, target = p["above_func"], p["above_target"]
        denom = _shape(f, T)
        amp = (target * base / denom) if denom else 0
        price = base - amp * _shape(f, inv - I0)
    else:
        price = base
    return max(1, round(price))


def simulate_sell(item: str, quantity: int, start_inv: Optional[float] = None) -> Tuple[int, float]:
    """Simula vender `quantity` unidades de un item, unidad por unidad.
    Devuelve (ingreso_total, inventario_final)."""
    p = MARKET_PARAMS.get(item, {})
    inv = start_inv if start_inv is not None else p.get("I0", 10000)
    total = 0
    for _ in range(max(quantity, 0)):
        price = price_at(item, inv)
        total += price
        if price > 1:
            inv += 1
    return total, inv


# ==============================================================================
# CAPA ESTRATEGICA
# ==============================================================================

class StrategicPlanner:
    def __init__(self, obs):
        self.obs = obs
        self.player = obs["player"]
        self.me = obs["farms"][self.player]
        self.private = obs["private"]
        self.market = obs["market"]
        self.day = obs.get("day", 1)
        self.days_left = max(0, 30 - self.day)

        self.shed = self.private.get("shed", {})
        self.seeds = self.private.get("seeds", {})
        self.money = self.me["money"]
        self.tiles = self.me["tiles"]
        self.farmer_pos = self.me["farmer"]
        self.hands = self.me.get("hands", [])
        self.hires_today = self.me.get("hires_today", 0)
        self.prices = self.market.get("prices", {})
        self.town_demands = self._get_town_demands()
        self.owned_tiles = self._count_owned_tiles()

    def _get_town_demands(self) -> Dict[str, int]:
        """Cuenta CUANTAS tiendas (entre las desbloqueadas) demandan cada
        producto, en vez de solo si hay al menos una. WHEAT tiene 5 tiendas
        que lo piden, CARROT solo 2 - antes ambos recibian el mismo bono
        plano de 1.15x; con el conteo se puede escalar proporcionalmente."""
        unlocked_shops = self.obs.get("town", {}).get("unlocked_shops", [])
        demand_count: Dict[str, int] = {}
        for shop in unlocked_shops:
            shop_type = shop.get("type") if isinstance(shop, dict) else shop
            for item in SHOP_DEMAND_MAP.get(shop_type, []):
                demand_count[item] = demand_count.get(item, 0) + 1
        return demand_count

    def _count_owned_tiles(self) -> int:
        # FIX: "owned" = cualquier casilla dentro de un cuadrante comprado,
        # este vacia u ocupada. Antes excluia las vacias (tile is None),
        # subestimando el tamano real de la granja.
        count = 0
        for row in self.tiles:
            for tile in row:
                if tile != "LOCKED":
                    count += 1
        return count

    def _count_empty_tiles(self) -> int:
        count = 0
        for row in self.tiles:
            for tile in row:
                if tile is None:
                    count += 1
        return count

    def _count_animal_structures(self) -> int:
        count = 0
        for row in self.tiles:
            for tile in row:
                if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE"):
                    count += 1
        return count

    def _count_animals_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.tiles:
            for tile in row:
                if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE") and tile.get("animal"):
                    a = tile["animal"]
                    counts[a] = counts.get(a, 0) + 1
        return counts

    # --------------------------------------------------------------------
    # Simulacion de precios / ROI
    # --------------------------------------------------------------------

    def _simulate_market_price(self, item, quantity):
        """Ingreso total simulado por vender `quantity` unidades de `item`."""
        inv = self.market.get("inventory", {}).get(item)
        total, _ = simulate_sell(item, quantity, inv)
        return total

    def _calculate_crop_roi(self, crop, cycles=1, use_fertilizer=False):
        spec = CROP_SPECS[crop]
        yield_per_cycle = spec["yield_fert"] if use_fertilizer else spec["yield_unfert"]
        cycle_days = spec["cycle_days"]
        if use_fertilizer and crop == "MELON":
            # El fertilizante en melon solo acelera el ciclo, no aumenta el tope
            cycle_days = max(1, cycle_days - 2)

        total_yield = yield_per_cycle * cycles
        # La venta real ahora es en micro-lotes (ver _calculate_optimal_sell_quantity),
        # no un volcado instantaneo - usamos el precio actual (spot) en vez de
        # simular una venta masiva de una sola vez, que subestima el ingreso
        # real de productos premium.
        spot_price = price_at(crop, self.market.get("inventory", {}).get(crop, MARKET_PARAMS.get(crop, {}).get("I0", 10000)))
        revenue = total_yield * spot_price

        cost = spec["seed_cost"] * cycles
        if use_fertilizer:
            fert_price = self.prices.get("FERTILIZER", BASE_PRICES.get("FERTILIZER", 100))
            cost += fert_price * cycles

        total_days = max(1, cycle_days * cycles)
        return (revenue - cost) / total_days

    def _calculate_animal_roi(self, animal):
        spec = ANIMAL_SPECS[animal]
        sell_price = self.prices.get(spec["product"], BASE_PRICES.get(spec["product"], 1))
        feed_price = self.prices.get("WHEAT", BASE_PRICES.get("WHEAT", 25))
        fert_price = self.prices.get("FERTILIZER", BASE_PRICES.get("FERTILIZER", 100))
        daily_yield = spec["yield_per_prod"] / max(spec["days_to_produce"], 1)
        daily_revenue = daily_yield * sell_price
        daily_feed_cost = feed_price * 1.0  # ~1 trigo/dia por animal (heuristica)
        # Todo animal vivo produce 1 fertilizante/dia gratis (COLLECT_FERTILIZER),
        # sin costo adicional - antes no se contaba, subestimando el ROI real.
        daily_fert_byproduct = fert_price * 1.0
        return daily_revenue + daily_fert_byproduct - daily_feed_cost

    def _total_owned(self, animal: str) -> int:
        """Cuenta animales colocados + en el cobertizo (comprados sin colocar)
        + cargados en el inventario de algun trabajador, para no comprar de mas."""
        placed = self._count_animals_by_type().get(animal, 0)
        in_shed = self.shed.get(animal, 0)
        carried = 0
        for inv in self.private.get("inventories", []):
            if inv:
                carried += inv.get(animal, 0)
        return placed + in_shed + carried

    def _unplaced(self, animal: str) -> int:
        """Animales ya comprados pero que todavia no estan sobre una
        estructura (coop/pasture): en el cobertizo o cargados por alguien."""
        amt = self.shed.get(animal, 0)
        for inv in self.private.get("inventories", []):
            if inv:
                amt += inv.get(animal, 0)
        return amt

    def _evaluate_animal_expansion(self) -> Optional[str]:
        if self.days_left < 8:
            return None
        best, best_roi = None, 0.0
        for animal, spec in ANIMAL_SPECS.items():
            if self._total_owned(animal) >= spec["max_animals"]:
                continue
            if self.money < spec["cost"] + 200:  # reserva de seguridad
                continue
            # No comprar otro mientras ya haya uno sin colocar: cada estructura
            # (coop/pasture) solo aloja UN animal, y hay que darle tiempo a
            # OperationsManager de construir la estructura y colocarlo antes de
            # comprar el siguiente (evita comprar animales que nunca se usan).
            if self._unplaced(animal) > 0:
                continue
            roi = self._calculate_animal_roi(animal)
            if roi > best_roi:
                best_roi, best = roi, animal
        return best

    def _evaluate_tile_expansion(self) -> bool:
        unlocked = self.me.get("unlocked_quadrants", [])
        if len(unlocked) >= 4:
            return False
        idx = len(unlocked) - 1  # el primer cuadrante es gratis
        if idx < 0 or idx >= len(LAND_PRICES):
            return False
        cost = LAND_PRICES[idx]
        if len(unlocked) == 1 and self.money >= cost + 200 and self.days_left > 10:
            return True
        if self.money < cost + 500:
            return False
        if self.days_left < 6:
            return False
        if self._count_empty_tiles() > 15:
            return False  # todavia hay bastante espacio en la tierra actual
        return True

    def _get_best_crop(self, allow_fertilizer=True) -> Optional[str]:
        best_crop, best_roi = None, float("-inf")
        for crop in CROP_SPECS:
            use_fert = allow_fertilizer and self._should_use_fertilizer(crop)
            roi = self._calculate_crop_roi(crop, 1, use_fert)
            if roi > best_roi:
                best_roi, best_crop = roi, crop
        return best_crop

    def _should_use_fertilizer(self, crop) -> bool:
        fert_price = self.prices.get("FERTILIZER", BASE_PRICES.get("FERTILIZER", 100))
        if self.money < fert_price + 200:
            return False
        roi_plain = self._calculate_crop_roi(crop, 1, False)
        roi_fert = self._calculate_crop_roi(crop, 1, True)
        return roi_fert > roi_plain

    def _generate_optimal_portfolio(self) -> Dict[str, Any]:
        """Rankea los cultivos por ROI y asigna cuantos plantar de cada uno,
        pero siempre reservando una porcion para cultivos de ciclo corto
        (WHEAT/CARROT) que dan flujo de caja rapido y evitan quedarnos sin
        liquidez mientras esperamos que madure un cultivo caro y lento
        (melon/fresa tardan 10+ dias en la primera cosecha)."""
        ranked = []
        for crop in CROP_SPECS:
            use_fert = self._should_use_fertilizer(crop)
            roi = self._calculate_crop_roi(crop, 1, use_fert)
            bonus = 1.0 + 0.05 * self.town_demands.get(crop, 0)
            ranked.append((roi * bonus, crop, use_fert))
        ranked.sort(reverse=True)

        empty_capacity = self._count_empty_tiles()

        crops: Dict[str, int] = {}
        fertilize_on: set = set()

        if empty_capacity > 0 and ranked:
            # Porcion minima garantizada para flujo de caja rapido (ciclo <=5 dias)
            liquidity_crop = "WHEAT" if self.prices.get("WHEAT", BASE_PRICES["WHEAT"]) >= \
                self.prices.get("CARROT", BASE_PRICES["CARROT"]) * (10.0 / 20.0) else "CARROT"
            # En dinero bajo o en los primeros dias, priorizamos liquidez con mas fuerza
            liquidity_share = 0.6 if (self.money < 1500 or self.day < 5) else 0.35
            liquidity_n = math.ceil(empty_capacity * liquidity_share)
            crops[liquidity_crop] = liquidity_n
            if self._should_use_fertilizer(liquidity_crop):
                fertilize_on.add(liquidity_crop)

            remaining_capacity = empty_capacity - liquidity_n
            growth_ranked = [r for r in ranked if r[1] != liquidity_crop]

            if remaining_capacity > 0 and growth_ranked:
                primary_n = 0  # FIX: evita UnboundLocalError si best_roi <= 0
                best_roi, best_crop, best_fert = growth_ranked[0]
                if best_roi > 0:
                    primary_n = math.ceil(remaining_capacity * 0.7)
                    crops[best_crop] = crops.get(best_crop, 0) + primary_n
                    if best_fert:
                        fertilize_on.add(best_crop)

                if len(growth_ranked) > 1:
                    second_roi, second_crop, second_fert = growth_ranked[1]
                    if second_roi > 0:
                        secondary_n = remaining_capacity - primary_n
                        if secondary_n > 0:
                            crops[second_crop] = crops.get(second_crop, 0) + secondary_n
                            if second_fert:
                                fertilize_on.add(second_crop)

        return {"crops": crops, "use_fertilizer_on": fertilize_on, "ranked": ranked}

    def strategy_wants_animal_expansion(self) -> bool:
        return self.days_left >= 8 and self.money >= 500

    def get_strategy(self) -> Dict[str, Any]:
        strategy: Dict[str, Any] = {
            "crops": {},
            "use_fertilizer_on": set(),
            "animals": [],
            "should_hire_hands": 0,
            "should_expand_tiles": False,
        }

        if self.days_left <= 0:
            return strategy

        portfolio = self._generate_optimal_portfolio()
        strategy["crops"] = portfolio["crops"]
        strategy["use_fertilizer_on"] = portfolio["use_fertilizer_on"]

        best_animal = self._evaluate_animal_expansion()
        if best_animal:
            strategy["animals"].append(best_animal)

        # Contratacion mas temprana que antes (el costo Fibonacci reinicia
        # cada dia y las primeras contrataciones son casi gratis), pero sin
        # sobrecontratar: seguimos exigiendo un minimo de tareas disponibles
        # para que la mano no quede ociosa (el umbral bajo de 8, no 15,
        # todavia filtra el arranque cuando casi no hay nada plantado).
        target_hires_today = 10
        if self.money > 50 and self.hires_today < target_hires_today and self.days_left > 2:
            strategy["should_hire_hands"] = target_hires_today - self.hires_today

        strategy["should_expand_tiles"] = self._evaluate_tile_expansion()

        return strategy


# ==============================================================================
# CAPA TACTICA - MERCADO
# ==============================================================================

class MarketManager:
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
        self.hires_today = self.me.get("hires_today", 0)
        # Liquidacion total: cerca del turno final (por defecto 720 turnos)
        # ya no tiene sentido frenar ventas por precio o por reservas (trigo
        # para animales, fertilizante) - lo que quede sin vender en el
        # cobertizo NO cuenta para el resultado final ("unsold items in
        # inventory do not count"). Vendemos TODO, al precio que sea.
        self.hour = obs.get("hour", 0)
        self.absolute_step = self.day * 24 + self.hour
        self.liquidation_mode = self.absolute_step >= 717

    def _count_animals(self) -> int:
        count = 0
        for row in self.me.get("tiles", []):
            for tile in row:
                if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE") and tile.get("animal"):
                    count += 1
        return count

    def _calculate_optimal_sell_quantity(self, item: str, qty: int) -> int:
        if qty <= 0:
            return 0
        if self.liquidation_mode:
            return qty  # liquidacion total: vender todo, sin importar el precio
        p = MARKET_PARAMS.get(item)
        base = p["base"] if p else self.prices.get(item, 1)
        inv = self.market.get("inventory", {}).get(item, (p.get("I0", 10000) if p else 10000))
        best_n = 0
        for n in range(1, qty + 1):
            price = price_at(item, inv)
            # dejamos de vender si el precio se desploma por debajo del 30% del base
            if price < base * 0.3 and n > 1:
                break
            best_n = n
            if price > 1:
                inv += 1
        # Micro-lotes para productos premium sensibles a sobreoferta: no
        # vender mas de 2/turno incluso si el corte de precio permitiria mas,
        # para dejar que el consumo de la ciudad reponga precio entre turnos.
        # Micro-lotes para productos premium: en un mercado real (validado
        # contra un replay propio bajo townCenterSellInterval=24) los precios
        # tienden a SUBIR sostenidamente por escasez, no a colapsar por
        # sobreoferta - asi que vender de a 1/turno (en vez de 2 o sin tope)
        # deja mas inventario para venderlo mas adelante a mejor precio.
        # Probado empiricamente: 1 > 2 > sin_tope bajo la config real.
        if self.day < 29 and item in ("MELON", "STRAWBERRY", "WOOL", "MILK"):
            best_n = min(best_n, 1)
        return best_n

    def _simulate_sell_price(self, item: str, quantity: int) -> float:
        inv = self.market.get("inventory", {}).get(item)
        total, _ = simulate_sell(item, quantity, inv)
        return total

    def _needs_wheat_for_animals(self) -> bool:
        return self._count_animals() > 0

    def _calculate_animal_feed_needs(self) -> int:
        return self._count_animals() * 3  # buffer de 3 dias

    def get_orders(self) -> List:
        orders: List = []
        remaining_money = self.money

        # 1. VENTAS
        for item, qty in list(self.shed.items()):
            if item in ANIMAL_SPECS or item in ("GOOSE", "COW", "SHEEP"):
                continue
            if item.endswith("_SEED"):
                continue
            if item == "FERTILIZER":
                # FIX: antes nunca se vendia fertilizante, ni siquiera el
                # excedente recolectado gratis de los animales (COLLECT_FERTILIZER).
                # Mantenemos un buffer para las FERTILIZE planeadas y vendemos
                # solo lo que sobra por encima de ese buffer (evita el ciclo
                # comprar/vender del mismo turno que motivo el "continue" original).
                # En liquidacion no hay "planeadas" que valgan: no quedan
                # turnos futuros para usarlo, asi que el buffer es 0.
                fert_buffer = 0 if self.liquidation_mode else (5 if self.strategy.get("use_fertilizer_on") else 0)
                fert_excess = qty - fert_buffer
                if fert_excess > 0:
                    sell_qty = self._calculate_optimal_sell_quantity(item, fert_excess)
                    if sell_qty > 0:
                        orders.append(["SELL", item, sell_qty])
                continue
            if item == "WHEAT" and self._needs_wheat_for_animals() and not self.liquidation_mode:
                required = self._calculate_animal_feed_needs()
                # Solo vendemos trigo por encima del doble de la reserva necesaria
                # (histeresis para no comprar y vender en turnos alternos).
                if qty <= required * 2:
                    continue
                qty = qty - required * 2
            sell_qty = self._calculate_optimal_sell_quantity(item, qty)
            if sell_qty > 0:
                orders.append(["SELL", item, sell_qty])

        # 2. COMPRAR TRIGO PARA ALIMENTAR ANIMALES (solo si el stock esta muy bajo,
        #    con histeresis para no oscilar con la venta de arriba)
        if self._needs_wheat_for_animals() and not self.liquidation_mode:
            required = self._calculate_animal_feed_needs()
            have = self.shed.get("WHEAT", 0)
            if have < required * 0.5:
                wheat_price = self.prices.get("WHEAT", BASE_PRICES.get("WHEAT", 25))
                to_buy = min(int(required - have) + 1, 10)
                cost = wheat_price * to_buy
                if to_buy > 0 and remaining_money >= cost:
                    orders.append(["BUY_PRODUCT", "WHEAT", to_buy])
                    remaining_money -= cost

        # 3. COMPRAR SEMILLAS
        if self.day < 28:
            for crop, need in self.strategy.get("crops", {}).items():
                if need > 0:
                    current_seeds = self.private.get("seeds", {}).get(crop, 0)
                    cost = CROP_SPECS[crop]["seed_cost"]
                    to_buy = max(0, min(need, 8) - current_seeds)
                    if to_buy > 0 and remaining_money >= cost * to_buy:
                        orders.append(["BUY_SEED", crop, to_buy])
                        remaining_money -= cost * to_buy

        # 4. COMPRAR FERTILIZANTE
        if self.strategy.get("use_fertilizer_on") and self.day < 25:
            fert_price = self.prices.get("FERTILIZER", BASE_PRICES.get("FERTILIZER", 100))
            fert_stock = self.shed.get("FERTILIZER", 0)
            if fert_stock < 5 and remaining_money >= fert_price * 2 + 200:
                orders.append(["BUY_PRODUCT", "FERTILIZER", 2])
                remaining_money -= fert_price * 2

        # 5. COMPRAR ANIMALES
        for animal in self.strategy.get("animals", []):
            cost = ANIMAL_SPECS[animal]["cost"]
            if remaining_money >= cost:
                orders.append(["BUY_ANIMAL", animal, 1])
                remaining_money -= cost

        # 6. CONTRATAR
        # FIX: antes no se verificaba ni descontaba el costo (fib creciente)
        # contra el dinero que ya se planeo gastar en los pasos anteriores
        # de este mismo turno, arriesgando ordenes de HIRE que la partida
        # rechaza o que dejan sin fondos las ordenes siguientes.
        hires_planned = self.hires_today
        for _ in range(self.strategy.get("should_hire_hands", 0)):
            cost = _fib_hire_cost(hires_planned)
            if remaining_money < cost:
                break
            orders.append(["HIRE"])
            remaining_money -= cost
            hires_planned += 1

        # 7. EXPANDIR
        # FIX: la decision de expandir se tomo en StrategicPlanner con el
        # dinero ORIGINAL del turno, sin saber cuanto se gastaria despues en
        # semillas/fertilizante/animales/manos. Revalidamos aqui con lo que
        # realmente queda.
        if self.strategy.get("should_expand_tiles", False):
            unlocked = len(self.me.get("unlocked_quadrants", []))
            idx = unlocked - 1
            if 0 <= idx < len(LAND_PRICES):
                land_cost = LAND_PRICES[idx]
                if remaining_money >= land_cost:
                    orders.append(["BUY_LAND"])
                    remaining_money -= land_cost

        return orders[:10]


def _hungarian_assignment(cost: List[List[float]]) -> List[int]:
    """Algoritmo Hungaro (Kuhn-Munkres), O(n^2*m). Requiere n_filas <= n_columnas
    (se rellena con columnas dummy de costo 0 en el llamador si hace falta).
    Devuelve `assign` de largo n con assign[i] = columna asignada a la fila i,
    minimizando el costo total. Reemplaza la asignacion secuencial/golosa
    (primero el farmer toma lo mas cercano, luego cada mano por turno) por
    la asignacion optima GLOBAL unidad<->tarea, evitando que una unidad
    cruce media granja mientras otra estaba justo al lado de esa tarea."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    INF = float('inf')
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(0, m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    assign = [0] * (n + 1)
    for j in range(1, m + 1):
        if p[j] != 0:
            assign[p[j]] = j
    return [assign[i] - 1 for i in range(1, n + 1)]


# ==============================================================================
# CAPA OPERATIVA - CAMPO
# ==============================================================================

class OperationsManager:
    def __init__(self, obs, strategy):
        self.obs = obs
        self.player = obs["player"]
        self.me = obs["farms"][self.player]
        self.private = obs["private"]
        self.strategy = strategy
        self.day = obs.get("day", 0)
        self.tiles = self.me["tiles"]
        self.height = len(self.tiles)
        self.width = len(self.tiles[0]) if self.height else 0
        self.farmer_pos = tuple(self.me["farmer"])
        self.hands_pos = [tuple(p) for p in self.me.get("hands", [])]
        self.inventories = self.private.get("inventories", [])
        self.shed = self.private.get("shed", {})
        self.seeds = self.private.get("seeds", {})
        self.assigned_targets: set = set()
        half = self.width // 2 if self.width else 5
        self.shed_positions = {(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)}
        self.remaining_to_plant = dict(self.strategy.get("crops", {}))

    def _get_fertilizer_stock(self) -> int:
        return self.shed.get("FERTILIZER", 0)

    def _is_harvestable(self, tile: Dict) -> bool:
        """yield_units puede mostrar >0 antes de que el cultivo pueda cosecharse
        realmente; hay que respetar la edad minima (first-yield-day) del cultivo."""
        if tile.get("yield_units", 0) <= 0:
            return False
        crop = tile.get("crop")
        age = self.day - tile.get("planted_day", self.day)
        return age >= FIRST_YIELD_DAY.get(crop, 0)

    def _scan_tiles(self) -> Dict:
        scan = {
            "harvest": [], "water": [], "plant": [], "weed": [],
            "empty": [], "coop": [], "pasture": [], "animals": [], "fertilize": []
        }
        for y in range(self.height):
            for x in range(self.width):
                tile = self.tiles[y][x]
                if tile is None:
                    scan["empty"].append((x, y))
                    scan["plant"].append((x, y))
                elif isinstance(tile, dict):
                    kind = tile.get("kind")
                    if kind == "PLANT":
                        if self._is_harvestable(tile):
                            scan["harvest"].append((x, y))
                        if not tile.get("watered_today", True):
                            scan["water"].append((x, y))
                        crop = tile.get("crop")
                        age = self.day - tile.get("planted_day", self.day)
                        fert_window = FERTILIZE_WINDOW.get(crop, (0, 999))
                        if (crop in self.strategy.get("use_fertilizer_on", set())
                                and tile.get("fertilized_until_day", -1) < self.day
                                and fert_window[0] <= age <= fert_window[1]
                                and self._get_fertilizer_stock() > 0):
                            scan["fertilize"].append((x, y))
                    elif kind == "WEED":
                        scan["weed"].append((x, y))
                    elif kind in ("COOP", "PASTURE"):
                        if kind == "COOP":
                            scan["coop"].append((x, y))
                        else:
                            scan["pasture"].append((x, y))
                        animal = tile.get("animal")
                        if animal in ("GOOSE", "COW", "SHEEP"):
                            # FIX: los productos (huevo/leche/lana) tambien deben
                            # cosecharse, o se quedan topeados en max_held sin
                            # entrar nunca al cobertizo/venta.
                            if tile.get("yield_units", 0) > 0:
                                scan["harvest"].append((x, y))
                            # FIX: antes solo se enrutaba hacia animales sin
                            # alimentar. Ahora tambien se enruta si necesitan
                            # CARE o si hay fertilizante disponible para
                            # recolectar, o el bono de CARE y el fertilizante
                            # gratis nunca se aprovechan salvo que una unidad
                            # pase por ahi por casualidad.
                            needs_feed = not tile.get("fed_today", True)
                            needs_care = tile.get("fed_today", False) and not tile.get("cared_today", False)
                            needs_fert_collect = tile.get("fertilizer_available", False)
                            if needs_feed or needs_care or needs_fert_collect:
                                scan["animals"].append((x, y))
        return scan

    def _current_tile(self, pos: Tuple[int, int]):
        x, y = pos
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.tiles[y][x]
        return None

    def _is_current_tile_animal(self, pos: Tuple[int, int]) -> bool:
        """Verifica si en la posicion actual hay un animal sin alimentar."""
        tile = self._current_tile(pos)
        if not isinstance(tile, dict):
            return False
        kind = tile.get("kind")
        if kind not in ("COOP", "PASTURE"):
            return False
        animal = tile.get("animal")
        return animal in ("GOOSE", "COW", "SHEEP") and not tile.get("fed_today", True)

    def _inv(self, idx: int) -> Dict:
        if idx < len(self.inventories) and self.inventories[idx]:
            return self.inventories[idx]
        return {}

    def _inv_count(self, inv: Dict, item: str) -> int:
        return inv.get(item, 0) if inv else 0

    def _inv_total(self, inv: Dict) -> int:
        return sum(inv.values()) if inv else 0

    def _pick_crop_to_plant(self) -> Optional[str]:
        for crop, need in self.remaining_to_plant.items():
            if need > 0 and self.seeds.get(crop, 0) > 0:
                return crop
        return None

    def _needed_animal_to_place(self, inv: Dict) -> Optional[str]:
        for animal in ("GOOSE", "COW", "SHEEP"):
            if self._inv_count(inv, animal) > 0:
                return animal
        return None

    def _has_unoccupied_structure(self, positions: List[Tuple[int, int]]) -> bool:
        for pos in positions:
            tile = self._current_tile(pos)
            if isinstance(tile, dict) and not tile.get("animal"):
                return True
        return False

    def _pick_needed_shed_item(self, inv: Dict, scan: Dict) -> Optional[Tuple[str, int]]:
        if scan["animals"] and self._inv_count(inv, "WHEAT") == 0 and self.shed.get("WHEAT", 0) > 0:
            return ("WHEAT", min(5, self.shed.get("WHEAT", 0)))
        if scan["fertilize"] and self._inv_count(inv, "FERTILIZER") == 0 and self.shed.get("FERTILIZER", 0) > 0:
            return ("FERTILIZER", min(3, self.shed.get("FERTILIZER", 0)))
        for animal in ("GOOSE", "COW", "SHEEP"):
            if self.shed.get(animal, 0) > 0 and self._inv_count(inv, animal) == 0:
                if animal == "GOOSE" and self._has_unoccupied_structure(scan["coop"]):
                    return (animal, 1)
                if animal in ("COW", "SHEEP") and self._has_unoccupied_structure(scan["pasture"]):
                    return (animal, 1)
        return None

    def _cargo_targets(self, inv: Dict, scan: Dict) -> List[Tuple[int, int]]:
        """FIX: casillas donde se puede USAR lo que la unidad ya trae en el
        inventario (animal por colocar, trigo para alimentar, fertilizante
        para aplicar). Sin esto, una unidad que recoge algo en el cobertizo
        y no se mueve en el mismo turno queda parada ahi mismo, y en el
        siguiente turno la logica de 'estoy en el cobertizo con inventario'
        la hace soltarlo de nuevo -> loop infinito de PICKUP/DROP sin nunca
        entregarlo."""
        targets: List[Tuple[int, int]] = []
        if self._inv_count(inv, "GOOSE") > 0:
            targets.extend(s for s in scan["coop"] if not self._current_tile(s).get("animal"))
        for animal in ("COW", "SHEEP"):
            if self._inv_count(inv, animal) > 0:
                targets.extend(s for s in scan["pasture"] if not self._current_tile(s).get("animal"))
        if self._inv_count(inv, "WHEAT") > 0:
            targets.extend(scan["animals"])
        if self._inv_count(inv, "FERTILIZER") > 0:
            targets.extend(scan["fertilize"])
        return targets

    def _immediate_action(self, pos: Tuple[int, int], inv: Dict, scan: Dict) -> Optional[List]:
        tile = self._current_tile(pos)
        if isinstance(tile, dict):
            kind = tile.get("kind")
            if kind == "PLANT":
                if self._is_harvestable(tile):
                    return ["HARVEST"]
                if not tile.get("watered_today", True):
                    return ["WATER"]
                crop = tile.get("crop")
                age = self.day - tile.get("planted_day", self.day)
                fert_window = FERTILIZE_WINDOW.get(crop, (0, 999))
                if (crop in self.strategy.get("use_fertilizer_on", set())
                        and tile.get("fertilized_until_day", -1) < self.day
                        and fert_window[0] <= age <= fert_window[1]
                        and self._inv_count(inv, "FERTILIZER") > 0):
                    return ["FERTILIZE"]
            elif kind == "WEED":
                return ["DIG"]
            elif kind in ("COOP", "PASTURE"):
                animal = tile.get("animal")
                if animal:
                    # FIX: cosechar producto acumulado ANTES de otras acciones,
                    # para no dejarlo topeado en max_held sin vender nunca.
                    if tile.get("yield_units", 0) > 0:
                        return ["HARVEST"]
                    if not tile.get("fed_today", True) and self._inv_count(inv, "WHEAT") > 0:
                        return ["FEED"]
                    if tile.get("fertilizer_available"):
                        return ["COLLECT_FERTILIZER"]
                    if tile.get("fed_today", False) and not tile.get("cared_today", False):
                        return ["CARE"]
                else:
                    to_place = self._needed_animal_to_place(inv)
                    if to_place and ((kind == "COOP" and to_place == "GOOSE") or
                                      (kind == "PASTURE" and to_place in ("COW", "SHEEP"))):
                        return ["PLACE", to_place]
        elif tile is None:
            # FIX: si hay un animal comprado sin estructura libre donde
            # colocarlo, construir tiene prioridad sobre plantar - un animal
            # varado en el cobertizo es capital 100% ocioso (ya se pago su
            # costo y no produce nada), mientras que una siembra retrasada
            # un turno no pierde casi nada.
            unplaced_goose = self.shed.get("GOOSE", 0) + sum((inv or {}).get("GOOSE", 0) for inv in self.inventories)
            unplaced_pasture_animal = sum(
                self.shed.get(a, 0) + sum((inv or {}).get(a, 0) for inv in self.inventories)
                for a in ("COW", "SHEEP")
            )
            needs_coop = unplaced_goose > 0 and not self._has_unoccupied_structure(scan["coop"])
            needs_pasture = unplaced_pasture_animal > 0 and not self._has_unoccupied_structure(scan["pasture"])
            if needs_coop:
                return ["BUILD_COOP"]
            if needs_pasture:
                return ["BUILD_PASTURE"]
            crop = self._pick_crop_to_plant()
            if crop:
                self.remaining_to_plant[crop] = self.remaining_to_plant.get(crop, 0) - 1
                return ["PLANT", crop]

        if pos in self.shed_positions:
            cargo_targets = self._cargo_targets(inv, scan)
            if self._inv_total(inv) > 0:
                if not cargo_targets:
                    return ["DROP"]
                # FIX: seguimos cargando algo con un destino pendiente (animal
                # por colocar, trigo/fertilizante por usar en otra casilla).
                # No lo soltamos aqui: caemos a `return None` y dejamos que
                # _assign_movement nos lleve hacia ese destino.
            else:
                pick = self._pick_needed_shed_item(inv, scan)
                if pick:
                    return ["PICKUP", pick[0], pick[1]]
        return None

    def _step_towards(self, pos: Tuple[int, int], target: Tuple[int, int]) -> List:
        x, y = pos
        tx, ty = target
        dx, dy = tx - x, ty - y
        if dx == 0 and dy == 0:
            return ["PASS"]
        if abs(dx) >= abs(dy):
            return ["EAST"] if dx > 0 else ["WEST"]
        return ["SOUTH"] if dy > 0 else ["NORTH"]

    def _nearest_unassigned(self, pos: Tuple[int, int], candidates: List[Tuple[int, int]],
                             exclude_self: bool = True) -> Optional[Tuple[int, int]]:
        avail = [c for c in candidates if c not in self.assigned_targets]
        if exclude_self:
            # Si el target es la propia casilla, decide_actions ya lo intento via
            # _immediate_action y fallo (recurso faltante); no tiene sentido "moverse"
            # hacia donde ya estamos - eso solo produce un PASS improductivo. Lo excluimos
            # para que el trabajador busque otra tarea (p.ej. plantar) en su lugar.
            avail = [c for c in avail if c != pos]
        if not avail:
            return None
        avail.sort(key=lambda c: abs(c[0] - pos[0]) + abs(c[1] - pos[1]))
        return avail[0]

    # (la asignacion secuencial anterior fue reemplazada por
    # _assign_tasks_optimally, que usa el Algoritmo Hungaro - ver arriba)

    # Prioridad de cada categoria de tarea compartida (menor = mas urgente).
    # Se usa junto con la distancia para construir el costo de la matriz
    # unidad<->tarea del algoritmo Hungaro: BIG domina sobre la distancia
    # maxima posible en el tablero (~18), asi que primero se respeta la
    # prioridad y, dentro de la misma prioridad, se minimiza la distancia total.
    TASK_PRIORITY = {"harvest": 0, "build": 1, "fetch_animal": 1, "weed": 2, "animals": 3, "water": 4, "fertilize": 5, "plant": 6}
    _BIG = 1000

    def _needs_new_structure(self, scan: Dict) -> bool:
        unplaced_goose = self.shed.get("GOOSE", 0) + sum((inv or {}).get("GOOSE", 0) for inv in self.inventories)
        unplaced_pasture_animal = sum(
            self.shed.get(a, 0) + sum((inv or {}).get(a, 0) for inv in self.inventories)
            for a in ("COW", "SHEEP")
        )
        needs_coop = unplaced_goose > 0 and not self._has_unoccupied_structure(scan["coop"])
        needs_pasture = unplaced_pasture_animal > 0 and not self._has_unoccupied_structure(scan["pasture"])
        return needs_coop or needs_pasture

    def _has_unfetched_animal(self, scan: Dict) -> bool:
        """True si hay un animal esperando especificamente en el COBERTIZO
        (no cargado por ninguna unidad) y ya existe una estructura libre
        donde colocarlo - alguien debe ir a buscarlo."""
        if self.shed.get("GOOSE", 0) > 0 and self._has_unoccupied_structure(scan["coop"]):
            return True
        for animal in ("COW", "SHEEP"):
            if self.shed.get(animal, 0) > 0 and self._has_unoccupied_structure(scan["pasture"]):
                return True
        return False

    def _assign_tasks_optimally(self, units: List[Tuple[Tuple[int, int], bool]],
                                 pending_idx: List[int], scan: Dict,
                                 results: List[Optional[List]]) -> None:
        """Asigna de forma OPTIMA GLOBAL (Algoritmo Hungaro) las unidades sin
        tarea inmediata a las tareas compartidas de la granja (cosechar,
        desyerbar, animales, regar, fertilizar, plantar, construir), en vez de
        la asignacion secuencial anterior (el farmer se queda con lo mas
        cercano, luego cada mano, en orden fijo) que podia dejar a una unidad
        cruzando la granja mientras otra estaba al lado de esa tarea."""
        plant_targets = scan["empty"] if self._pick_crop_to_plant() else []
        # FIX: "build" es su propia categoria explicita - antes construir un
        # coop/pasture solo pasaba por casualidad, cuando una unidad llegaba a
        # una casilla vacia sin tener ya una siembra pendiente ahi mismo. Sin
        # esto, un animal comprado puede quedar varado en el cobertizo toda
        # la partida sin nunca producir nada.
        build_targets = scan["empty"] if self._needs_new_structure(scan) else []
        # FIX: si hay un animal ya comprado esperando en el cobertizo Y una
        # estructura libre donde colocarlo, alguien debe ir a RECOGERLO. Antes
        # esto dependia de que una unidad pasara por el cobertizo con el
        # inventario vacio por pura casualidad (o del fallback de ultimo
        # recurso, que solo se activa si una unidad queda sin NINGUNA otra
        # tarea, algo que casi nunca pasa) - un animal de $300-500 podia
        # quedar varado sin producir nada durante toda la partida.
        fetch_animal_targets = list(self.shed_positions) if self._has_unfetched_animal(scan) else []
        groups = {
            "harvest": scan["harvest"], "build": build_targets, "fetch_animal": fetch_animal_targets,
            "weed": scan["weed"], "animals": scan["animals"], "water": scan["water"],
            "fertilize": scan["fertilize"], "plant": plant_targets,
        }
        # Dedupe: una misma casilla puede calificar para mas de una categoria
        # (p.ej. una planta cosechable y sin regar el mismo dia); nos
        # quedamos con la de mayor prioridad para no ofrecerla dos veces
        # como si fueran tareas distintas.
        best_priority: Dict[Tuple[int, int], int] = {}
        for name, positions in groups.items():
            rank = self.TASK_PRIORITY[name]
            for pos in positions:
                if pos in self.assigned_targets:
                    continue
                if pos not in best_priority or rank < best_priority[pos]:
                    best_priority[pos] = rank
        tasks = list(best_priority.items())
        if not tasks:
            return

        n, m = len(pending_idx), len(tasks)
        dummy_cols = max(0, n - m)  # columnas "no hacer nada" si faltan tareas
        cost: List[List[float]] = []
        for idx in pending_idx:
            pos = units[idx][0]
            row = [abs(pos[0] - tpos[0]) + abs(pos[1] - tpos[1]) + rank * self._BIG
                   for (tpos, rank) in tasks]
            row.extend([0.0] * dummy_cols)
            cost.append(row)

        assignment = _hungarian_assignment(cost)
        for row_i, col_j in enumerate(assignment):
            idx = pending_idx[row_i]
            if col_j < m:
                target_pos = tasks[col_j][0]
                self.assigned_targets.add(target_pos)
                results[idx] = self._step_towards(units[idx][0], target_pos)
            # columna dummy -> results[idx] sigue en None, cae al fallback

    def decide_actions(self) -> Tuple[List, List[List]]:
        scan = self._scan_tiles()
        units = [(self.farmer_pos, True)] + [(p, False) for p in self.hands_pos]
        n_units = len(units)
        invs = [self._inv(i) for i in range(n_units)]
        results: List[Optional[List]] = [None] * n_units

        # 1. Acciones inmediatas: lo que se puede hacer parado en la casilla
        #    actual (HARVEST/WATER/FEED/CARE/COLLECT_FERTILIZER/PLANT/etc).
        pending: List[int] = []
        for i, (pos, _) in enumerate(units):
            action = self._immediate_action(pos, invs[i], scan)
            if action is not None:
                results[i] = action
            else:
                pending.append(i)

        # 2. Entrega de carga pendiente: es especifica por unidad (depende de
        #    QUE trae cada una en su inventario), asi que se resuelve antes
        #    de la asignacion conjunta y con prioridad maxima - es lo que
        #    evita el loop PICKUP/DROP (ver _cargo_targets).
        still_pending: List[int] = []
        for i in pending:
            pos = units[i][0]
            cargo_targets = self._cargo_targets(invs[i], scan)
            target = self._nearest_unassigned(pos, cargo_targets) if cargo_targets else None
            if target:
                self.assigned_targets.add(target)
                results[i] = self._step_towards(pos, target)
            else:
                still_pending.append(i)

        # 3. Asignacion optima global (Hungaro) del resto de unidades a las
        #    tareas compartidas de la granja.
        if still_pending:
            self._assign_tasks_optimally(units, still_pending, scan, results)

        # 4. Fallback: buscar en el cobertizo lo que haga falta, o PASS.
        for i in still_pending:
            if results[i] is not None:
                continue
            pos = units[i][0]
            inv = invs[i]
            needs_fetch = (self._pick_needed_shed_item(inv, scan) is not None
                            and pos not in self.shed_positions)
            if needs_fetch:
                nearest_shed = self._nearest_unassigned(pos, list(self.shed_positions))
                if nearest_shed is None:
                    nearest_shed = min(
                        self.shed_positions,
                        key=lambda c: abs(c[0] - pos[0]) + abs(c[1] - pos[1])
                    )
                results[i] = self._step_towards(pos, nearest_shed)
            else:
                results[i] = ["PASS"]

        farmer_action = results[0] if results else ["PASS"]
        hand_actions = results[1:]
        return farmer_action, hand_actions


# ==============================================================================
# PUNTO DE ENTRADA DEL AGENTE
# ==============================================================================

def agent(obs):
    try:
        planner = StrategicPlanner(obs)
        strategy = planner.get_strategy()

        market_mgr = MarketManager(obs, strategy)
        market_orders = market_mgr.get_orders()

        ops_mgr = OperationsManager(obs, strategy)
        farmer_action, hand_actions = ops_mgr.decide_actions()

        return {"farmer": farmer_action, "hands": hand_actions, "market": market_orders}
    except Exception:
        # Red de seguridad: nunca queremos que el agente crashee la partida.
        try:
            n_hands = len(obs.get("farms", [{}])[obs.get("player", 0)].get("hands", []))
        except Exception:
            n_hands = 0
        return {"farmer": ["PASS"], "hands": [["PASS"] for _ in range(n_hands)], "market": []}
