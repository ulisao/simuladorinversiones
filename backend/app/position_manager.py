"""
Gestor de salidas dinámicas (`PositionManager`).

Reemplaza el take-profit fijo R/B 1:2 por una salida escalonada en cuatro fases,
manejada tick a tick sobre una posición ya abierta:

1. **SL inicial (-3,0%)** sobre el 100% de la posición.
2. **TP1 (+4,5%)**: vende el 50%, cancela el SL inicial y activa el trailing.
3. **Trailing (1,2%) con piso garantizado (+3,5%)** sobre el 50% restante.
   El stop es monótono creciente: solo sube, nunca baja.
4. **TP2 techo (+8,0%)** o **cierre preventivo a las 16:50 hs ART**, lo que llegue
   primero.
5. **Vencimiento por tiempo (10 días corridos)**: red de seguridad contra la
   posición que no se mueve. Si nunca tocó ni el SL inicial ni el TP1, se cierra
   igual — ni gana ni pierde, pero inmoviliza capital y ocupa un cupo de
   `MAX_POSICIONES`.

Referencia de spec: `Pasar_ulises_31_de_agosto.docx`, secciones 1, 2, 3 y 5.
El vencimiento por tiempo no está en ese documento: lo agrega la Tarea 3.5 del
plan (`tareas-desarrollo.md`) como `SWING_MAX_DIAS`.

Diferencias deliberadas contra el código de la spec:

- **Nada hardcodeado.** La spec escribe `0.030`, `0.045`, `0.012`, `0.035`, `0.080`
  y `time(16, 50)` dentro del `__init__`. Acá los defaults salen de `config`
  (sección "Gestión de salidas"), igual que hace `technical_filters`.
- **Los `timestamp` naive se interpretan como hora ART**, no como hora local del
  servidor. La spec llama `timestamp.astimezone(self.tz)` a secas, lo que en un
  datetime sin `tzinfo` toma la zona del sistema operativo y vuelve el resultado
  dependiente de dónde corre el proceso. Acá se localiza explícitamente, así
  `on_tick` es determinístico y testeable.
- **Precio inválido levanta `ValueError`.** Un tick con precio 0 o negativo (dato
  roto del feed) dispararía una venta espuria por stop-loss; es preferible que el
  llamador lo descarte antes de tocar la máquina de estados.
- **(De)serialización incluida** (`a_dict` / `desde_dict`) para el punto
  "Persistencia de Estado" del checklist de la spec (sección 5): si el proceso se
  reinicia a mitad de rueda, el seguimiento no se pierde. El acceso a la base es
  responsabilidad del job que consume esta clase, no de este módulo.

Este módulo es puro: no habla con la red ni con la base, y `on_tick` acepta un
`timestamp` inyectable para poder probar la regla de las 16:50 sin depender de la
hora real.
"""
from datetime import date, datetime, time
from typing import Any, Dict, Optional

import pytz

from . import config


# ---------- Códigos de la respuesta ----------
# Van en inglés y en mayúsculas porque son códigos de máquina (los consume el job
# de la Tarea 3.6 y quedan grabados en la operación), no mensajes al usuario.

ACCION_VENTA = "SELL"

MOTIVO_CIERRE_PREVENTIVO = "END_OF_DAY_CUTOFF_1650"
MOTIVO_STOP_INICIAL = "INITIAL_STOP_LOSS_HIT"
MOTIVO_TP1_PARCIAL = "TP1_PARTIAL_50PCT"
MOTIVO_TP2_TECHO = "TP2_CEILING_HIT"
MOTIVO_TRAILING = "TRAILING_STOP_1.2PCT_HIT"
MOTIVO_VENCIMIENTO = "SWING_TIME_EXPIRY"

NOTA_CIERRE_PREVENTIVO = "Cierre preventivo para evitar Gap bajista nocturno"
NOTA_VENCIMIENTO = "Posición dormida: ni SL ni TP1 en el plazo máximo"


class PositionManager:
    """
    Máquina de estados de salida de una posición larga.

    Se instancia una vez por posición abierta y se le pasa cada precio nuevo con
    `on_tick`. Devuelve `None` mientras no haya nada que hacer, o el dict de la
    orden a ejecutar cuando se dispara una regla.

    Args:
        symbol: ticker de la posición (solo informativo, para logs y persistencia).
        entry_price: precio de entrada. Todos los umbrales se miden contra esto.
        total_qty: cantidad comprada. El TP1 vende `total_qty // 2`.
        sl_initial_pct: stop-loss inicial. Default `config.SALIDA_SL_INICIAL_PCT`.
        tp1_pct: gatillo del parcial. Default `config.SALIDA_TP1_PCT`.
        trailing_pullback: retroceso tolerado desde el pico. Default
            `config.SALIDA_TRAILING_PULLBACK`.
        min_guaranteed_pct: piso infranqueable post-TP1. Default
            `config.SALIDA_PISO_GARANTIZADO_PCT`.
        tp2_pct: techo de cierre total. Default `config.SALIDA_TP2_PCT`.
        market_close_cutoff: hora ART del cierre preventivo. Default
            `config.SALIDA_HORA_CIERRE_PREVENTIVO`.
        tz: nombre IANA de la zona horaria. Default `config.TZ_BYMA`.
        entry_date: fecha de compra, para el vencimiento por tiempo. Si es None
            la regla queda desactivada (una posición sin fecha no puede vencer).
        max_dias: días corridos antes de dar la posición por vencida. Default
            `config.SALIDA_SWING_MAX_DIAS`.

    Raises:
        ValueError: si `entry_price` o `total_qty` no son positivos.

    Atributos de estado (los que hay que persistir):
        is_tp1_hit: si ya se cobró el parcial del 50%.
        is_closed: si la posición ya está liquidada (a partir de acá `on_tick`
            devuelve siempre `None`).
        max_price_since_tp1: pico registrado desde el TP1 (high-water mark).
        current_stop_price: stop vigente. Antes del TP1 es el SL inicial; después,
            el trailing con piso.
        remaining_qty: cantidad todavía en cartera.
    """

    def __init__(
        self,
        symbol: str,
        entry_price: float,
        total_qty: float,
        sl_initial_pct: Optional[float] = None,
        tp1_pct: Optional[float] = None,
        trailing_pullback: Optional[float] = None,
        min_guaranteed_pct: Optional[float] = None,
        tp2_pct: Optional[float] = None,
        market_close_cutoff: Optional[time] = None,
        tz: Optional[str] = None,
        entry_date: Optional[date] = None,
        max_dias: Optional[int] = None,
    ) -> None:
        entry_price = float(entry_price)
        if entry_price <= 0:
            raise ValueError("entry_price tiene que ser positivo.")
        if total_qty <= 0:
            raise ValueError("total_qty tiene que ser positivo.")

        self.symbol = symbol
        self.entry_price = entry_price
        self.total_qty = total_qty
        self.remaining_qty = total_qty

        # ---------- Parámetros operativos (config.py, nunca literales acá) ----------
        self.sl_initial_pct = (
            config.SALIDA_SL_INICIAL_PCT if sl_initial_pct is None else float(sl_initial_pct)
        )
        self.tp1_pct = config.SALIDA_TP1_PCT if tp1_pct is None else float(tp1_pct)
        self.trailing_pullback = (
            config.SALIDA_TRAILING_PULLBACK
            if trailing_pullback is None
            else float(trailing_pullback)
        )
        self.min_guaranteed_pct = (
            config.SALIDA_PISO_GARANTIZADO_PCT
            if min_guaranteed_pct is None
            else float(min_guaranteed_pct)
        )
        self.tp2_pct = config.SALIDA_TP2_PCT if tp2_pct is None else float(tp2_pct)

        # ---------- Horario del cierre preventivo (Argentina, UTC-3) ----------
        self.tz_nombre = config.TZ_BYMA if tz is None else str(tz)
        self.tz = pytz.timezone(self.tz_nombre)
        self.market_close_cutoff = (
            config.SALIDA_HORA_CIERRE_PREVENTIVO
            if market_close_cutoff is None
            else market_close_cutoff
        )

        # ---------- Vencimiento por tiempo (Tarea 3.5) ----------
        self.entry_date = entry_date
        self.max_dias = (
            config.SALIDA_SWING_MAX_DIAS if max_dias is None else int(max_dias)
        )

        # ---------- Estado interno ----------
        self.is_tp1_hit = False
        self.is_closed = False
        self.max_price_since_tp1 = 0.0
        self.current_stop_price = entry_price * (1.0 - self.sl_initial_pct)

    # ---------- Helpers internos ----------

    def _hora_art(self, timestamp: Optional[datetime]) -> time:
        """
        Hora del tick expresada en zona horaria de Buenos Aires.

        Un `timestamp` con `tzinfo` se convierte; uno naive se interpreta como hora
        ART (no como hora local del servidor, que haría el resultado dependiente de
        la máquina). Sin `timestamp` se usa el reloj real.
        """
        if timestamp is None:
            return datetime.now(self.tz).time()
        if timestamp.tzinfo is None:
            return self.tz.localize(timestamp).time()
        return timestamp.astimezone(self.tz).time()

    def _fecha_art(self, timestamp: Optional[datetime]) -> date:
        """Fecha del tick en zona ART, con el mismo criterio que `_hora_art`."""
        if timestamp is None:
            return datetime.now(self.tz).date()
        if timestamp.tzinfo is None:
            return self.tz.localize(timestamp).date()
        return timestamp.astimezone(self.tz).date()

    def _vencida(self, timestamp: Optional[datetime]) -> bool:
        """True si la posición pasó `max_dias` corridos desde la compra.

        Sin `entry_date` la regla no aplica: preferimos no cerrar nada antes que
        inventar una fecha de compra.
        """
        if self.entry_date is None or self.max_dias <= 0:
            return False
        return (self._fecha_art(timestamp) - self.entry_date).days >= self.max_dias

    def _rendimiento_pct(self, current_price: float) -> float:
        """Rendimiento bruto del precio contra la entrada, en porcentaje."""
        return ((current_price / self.entry_price) - 1) * 100

    def _liquidar(self, current_price: float, motivo: str, **extra: Any) -> Dict[str, Any]:
        """Cierra el remanente completo y arma el dict de la orden."""
        self.is_closed = True
        qty_to_sell = self.remaining_qty
        self.remaining_qty = 0
        orden: Dict[str, Any] = {
            "action": ACCION_VENTA,
            "reason": motivo,
            "qty": qty_to_sell,
            "price": current_price,
            "profit_pct": self._rendimiento_pct(current_price),
        }
        orden.update(extra)
        return orden

    # ---------- Máquina de estados ----------

    def on_tick(
        self, current_price: float, timestamp: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evalúa las condiciones de salida contra un precio nuevo.

        El orden de prioridad es el de la spec y no es intercambiable:

        1. Cierre preventivo 16:50 hs ART (solo si ya se cobró el TP1).
        2. Si todavía no tocó TP1: primero el SL inicial, después el TP1, y
           recién al final el vencimiento por tiempo (Tarea 3.5).
        3. Si ya tocó TP1: primero se actualiza el pico y se sube el stop, después
           el TP2 techo, y por último el trailing. Una posición que ya cobró el
           parcial no vence por tiempo: la gestiona el trailing.

        Args:
            current_price: último precio observado.
            timestamp: momento del tick. Si es None usa la hora real; si es naive
                se interpreta como hora ART.

        Returns:
            El dict de la orden a ejecutar, o `None` si no hay nada que hacer
            (incluye el caso de la posición ya cerrada).

            Claves comunes: `action` ("SELL"), `reason` (código del motivo), `qty`
            (cantidad a vender), `price`, `profit_pct`. El TP1 agrega
            `new_stop_price` y el cierre preventivo agrega `note`.

        Raises:
            ValueError: si `current_price` no es positivo.
        """
        if self.is_closed:
            return None

        current_price = float(current_price)
        if current_price <= 0:
            raise ValueError("current_price tiene que ser positivo.")

        now_art = self._hora_art(timestamp)

        # -------------------------------------------------------------
        # REGLA PRIORITARIA: cierre intradiario preventivo (16:50 hs).
        # Si ya cobró TP1 y el mercado está por cerrar, liquida todo para no
        # quedar expuesto al gap bajista de la apertura siguiente.
        # -------------------------------------------------------------
        if self.is_tp1_hit and now_art >= self.market_close_cutoff:
            return self._liquidar(
                current_price,
                MOTIVO_CIERRE_PREVENTIVO,
                note=NOTA_CIERRE_PREVENTIVO,
            )

        # -------------------------------------------------------------
        # CASO 1: posición inicial (todavía no tocó TP1).
        # -------------------------------------------------------------
        if not self.is_tp1_hit:
            # 1.1 Stop-loss inicial (-3,0%).
            if current_price <= self.current_stop_price:
                return self._liquidar(current_price, MOTIVO_STOP_INICIAL)

            # 1.2 Take-profit 1 (+4,5%): vende el 50% y cancela el SL inicial.
            if current_price >= self.entry_price * (1.0 + self.tp1_pct):
                self.is_tp1_hit = True
                qty_tp1 = self.total_qty // 2  # el papel impar queda en el remanente
                self.remaining_qty -= qty_tp1

                # Activa el trailing con piso mínimo garantizado en +3,5%.
                self.max_price_since_tp1 = current_price
                trailing_inicial = current_price * (1.0 - self.trailing_pullback)
                piso_garantizado = self.entry_price * (1.0 + self.min_guaranteed_pct)
                self.current_stop_price = max(piso_garantizado, trailing_inicial)

                return {
                    "action": ACCION_VENTA,
                    "reason": MOTIVO_TP1_PARCIAL,
                    "qty": qty_tp1,
                    "price": current_price,
                    "profit_pct": self._rendimiento_pct(current_price),
                    "new_stop_price": self.current_stop_price,
                }

            # 1.3 Vencimiento por tiempo. Va ÚLTIMO del caso 1 a propósito: si en
            # este mismo tick el precio toca el SL o el TP1, mandan esas reglas,
            # que son la estrategia real. Esto solo barre lo que quedó dormido.
            if self._vencida(timestamp):
                return self._liquidar(
                    current_price, MOTIVO_VENCIMIENTO, note=NOTA_VENCIMIENTO
                )

        # -------------------------------------------------------------
        # CASO 2: post-TP1 (gestión dinámica del trailing 1,2%).
        # -------------------------------------------------------------
        else:
            # 2.1 Nuevo pico: el stop persigue al precio, pero solo hacia arriba.
            if current_price > self.max_price_since_tp1:
                self.max_price_since_tp1 = current_price
                stop_calculado = current_price * (1.0 - self.trailing_pullback)
                if stop_calculado > self.current_stop_price:
                    self.current_stop_price = stop_calculado

            # 2.2 TP2 techo (+8,0%).
            if current_price >= self.entry_price * (1.0 + self.tp2_pct):
                return self._liquidar(current_price, MOTIVO_TP2_TECHO)

            # 2.3 Trailing tocado (retroceso de 1,2% desde el pico).
            if current_price <= self.current_stop_price:
                return self._liquidar(current_price, MOTIVO_TRAILING)

        return None

    # ---------- Persistencia (checklist de la spec, sección 5) ----------

    def a_dict(self) -> Dict[str, Any]:
        """
        Estado serializable de la posición.

        Incluye los parámetros operativos además del estado para que una posición
        abierta con una configuración vieja se restaure con esa misma
        configuración, y no con la que esté vigente al reiniciar el proceso.
        """
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "total_qty": self.total_qty,
            "remaining_qty": self.remaining_qty,
            "is_tp1_hit": self.is_tp1_hit,
            "is_closed": self.is_closed,
            "max_price_since_tp1": self.max_price_since_tp1,
            "current_stop_price": self.current_stop_price,
            "sl_initial_pct": self.sl_initial_pct,
            "tp1_pct": self.tp1_pct,
            "trailing_pullback": self.trailing_pullback,
            "min_guaranteed_pct": self.min_guaranteed_pct,
            "tp2_pct": self.tp2_pct,
            "entry_date": self.entry_date,
            "max_dias": self.max_dias,
        }

    @classmethod
    def desde_dict(cls, estado: Dict[str, Any]) -> "PositionManager":
        """
        Reconstruye un `PositionManager` a partir de un estado guardado.

        Solo `symbol`, `entry_price` y `total_qty` son obligatorios: el resto de las
        claves puede faltar (la tabla `PositionState` guarda un subconjunto). Lo que
        no venga se completa con los defaults de `config`, y el estado ausente se
        interpreta como "posición recién abierta".

        Args:
            estado: dict con la forma de `a_dict()`, o un subconjunto suyo.

        Returns:
            La instancia con el estado restaurado.

        Raises:
            ValueError: si falta `entry_price` o `total_qty`, o si no son positivos.
        """
        if estado.get("entry_price") is None or estado.get("total_qty") is None:
            raise ValueError("El estado guardado necesita 'entry_price' y 'total_qty'.")

        manager = cls(
            symbol=estado.get("symbol", ""),
            entry_price=estado["entry_price"],
            total_qty=estado["total_qty"],
            sl_initial_pct=estado.get("sl_initial_pct"),
            tp1_pct=estado.get("tp1_pct"),
            trailing_pullback=estado.get("trailing_pullback"),
            min_guaranteed_pct=estado.get("min_guaranteed_pct"),
            tp2_pct=estado.get("tp2_pct"),
            entry_date=estado.get("entry_date"),
            max_dias=estado.get("max_dias"),
        )

        manager.is_tp1_hit = bool(estado.get("is_tp1_hit", False))
        manager.is_closed = bool(estado.get("is_closed", False))
        manager.max_price_since_tp1 = float(estado.get("max_price_since_tp1") or 0.0)

        remanente = estado.get("remaining_qty")
        if remanente is not None:
            manager.remaining_qty = remanente

        # El stop vigente se restaura tal cual: recalcularlo podría bajarlo, y el
        # stop es monótono creciente por definición.
        stop_guardado = estado.get("current_stop_price")
        if stop_guardado is not None:
            manager.current_stop_price = float(stop_guardado)

        return manager

    def __repr__(self) -> str:  # pragma: no cover - solo para logs
        return (
            f"PositionManager(symbol={self.symbol!r}, entry_price={self.entry_price}, "
            f"remaining_qty={self.remaining_qty}, is_tp1_hit={self.is_tp1_hit}, "
            f"is_closed={self.is_closed}, current_stop_price={self.current_stop_price})"
        )
