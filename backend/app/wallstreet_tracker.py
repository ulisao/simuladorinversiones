"""
Tracker de consenso institucional (Tarea 5.4).

Convierte los movimientos 13F que entrega `edgar_13f` en señales concretas de
compra y de venta. La idea central: **no seguir a un fondo solo**. Un gestor
puede equivocarse, tener un mandato distinto o estar cubriendo otra posición;
que varios fondos independientes muevan el mismo papel en la misma dirección es
una señal mucho más difícil de explicar por casualidad.

## Reglas

```mermaid
flowchart TD
    M[movimientos 13F] --> F1{"tipo = NUEVA o AUMENTO"}
    F1 -- no --> V["¿REDUCCION o CIERRE?<br/>→ señal de venta si tenemos la posición"]
    F1 -- sí --> F2{"peso en cartera ≥<br/>SMART_MIN_PESO_CARTERA"}
    F2 -- no --> X1[Descartado: ruido para el fondo]
    F2 -- sí --> F3{"¿lo movieron ≥<br/>SMART_MIN_CONSENSO fondos?"}
    F3 -- no --> X2[Descartado: sin consenso]
    F3 -- sí --> F4{"precio actual vs precio<br/>promedio de los fondos"}
    F4 -- "subió más de SMART_MAX_DELAY_SUBA" --> X3[Descartado: llegamos tarde]
    F4 -- dentro del margen --> OK[Señal de compra]
```

> El filtro de "llegamos tarde" no es opcional en esta estrategia: los 13F se
> presentan con hasta **45 días de rezago legal**, así que para cuando el dato
> es público el papel ya se movió. Sin ese filtro se compraría sistemáticamente
> arriba del precio al que entró el fondo.

## Qué NO hace este módulo

* No baja nada de internet: recibe los movimientos ya parseados.
* No ejecuta ni registra operaciones (eso es la Tarea 5.5).
* El precio actual se inyecta o se pide a `market_data`, que ya degrada solo
  ante error — un ticker sin precio se descarta con motivo, no rompe el barrido.
"""
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import config
from . import edgar_13f
from . import market_data
from . import technical_filters

logger = logging.getLogger(__name__)

ESTRATEGIA = config.ESTRATEGIA_SMART_MONEY


class WallStreetAdvancedTracker:
    """Consenso de fondos institucionales sobre el universo habilitado.

    Args:
        min_consenso: fondos distintos que tienen que coincidir. Default
            `config.SMART_MIN_CONSENSO`.
        min_peso: peso mínimo de la posición en la cartera del fondo. Default
            `config.SMART_MIN_PESO_CARTERA`.
        max_delay_suba: suba máxima tolerada del precio actual sobre el precio
            promedio de los fondos. Default `config.SMART_MAX_DELAY_SUBA`.
        universo: tickers operables. Default `config.TICKERS_BYMA` — un papel
            sin CEDEAR habilitado no se puede comprar, por más consenso que tenga.
    """

    def __init__(
        self,
        min_consenso: Optional[int] = None,
        min_peso: Optional[float] = None,
        max_delay_suba: Optional[float] = None,
        universo: Optional[Iterable[str]] = None,
    ) -> None:
        self.min_consenso = (
            config.SMART_MIN_CONSENSO if min_consenso is None else int(min_consenso)
        )
        self.min_peso = (
            config.SMART_MIN_PESO_CARTERA if min_peso is None else float(min_peso)
        )
        self.max_delay_suba = (
            config.SMART_MAX_DELAY_SUBA if max_delay_suba is None else float(max_delay_suba)
        )
        self.universo = set(universo if universo is not None else config.TICKERS_BYMA)

    # ---------- Agrupación ----------

    def _por_ticker(self, movimientos: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        agrupados: Dict[str, List[Dict[str, Any]]] = {}
        for m in movimientos:
            agrupados.setdefault(m["ticker"], []).append(m)
        return agrupados

    # ---------- Señales de compra ----------

    def procesar_reportes(
        self,
        movimientos: Iterable[Dict[str, Any]],
        precios: Optional[Dict[str, float]] = None,
        proveedor_precio: Optional[Callable[[str], float]] = None,
    ) -> Dict[str, Any]:
        """Señales de compra por consenso, con los descartes y su motivo.

        Args:
            movimientos: lo que devuelve `edgar_13f.descargar_movimientos()["movimientos"]`.
            precios: precios actuales ya resueltos, `{"NVDA": 200.0}`. Si falta
                uno se usa `proveedor_precio`.
            proveedor_precio: de dónde sacar un precio que no vino en `precios`.
                Default `market_data.get_last_price`.

        Returns:
            `{"compras": [...], "descartados": [{"ticker", "motivo"}], "evaluados": int}`
        """
        precios = dict(precios or {})
        traer_precio = proveedor_precio or market_data.get_last_price

        compras: List[Dict[str, Any]] = []
        descartados: List[Dict[str, str]] = []
        agrupados = self._por_ticker(movimientos)

        for ticker, movs in sorted(agrupados.items()):
            if ticker not in self.universo:
                descartados.append(
                    {
                        "ticker": ticker,
                        "motivo": (
                            f"FUERA DE UNIVERSO: {ticker} no tiene CEDEAR habilitado, "
                            "no se puede operar por más consenso que haya."
                        ),
                    }
                )
                continue

            compradores = [
                m
                for m in movs
                if m["tipo"] in edgar_13f.MOVIMIENTOS_DE_COMPRA
                and m["peso_cartera"] >= self.min_peso
            ]

            if len(compradores) < self.min_consenso:
                con_peso = len(compradores)
                total_compras = sum(1 for m in movs if m["tipo"] in edgar_13f.MOVIMIENTOS_DE_COMPRA)
                descartados.append(
                    {
                        "ticker": ticker,
                        "motivo": (
                            f"SIN CONSENSO: {con_peso} fondo(s) con peso ≥ "
                            f"{self.min_peso * 100:.1f}% de su cartera "
                            f"(se necesitan {self.min_consenso}; {total_compras} compraron "
                            "sin alcanzar el peso mínimo)."
                        ),
                    }
                )
                continue

            precio_fondos = self._precio_promedio(compradores)
            if precio_fondos is None:
                descartados.append(
                    {
                        "ticker": ticker,
                        "motivo": "SIN DATOS: los filings no traen precio promedio utilizable.",
                    }
                )
                continue

            precio_actual = precios.get(ticker)
            if precio_actual is None:
                try:
                    precio_actual = traer_precio(ticker)
                except Exception as exc:  # noqa: BLE001 — un ticker sin precio no frena el resto
                    descartados.append(
                        {"ticker": ticker, "motivo": f"SIN PRECIO: no se pudo cotizar {ticker} ({exc})."}
                    )
                    continue

            delta = (precio_actual / precio_fondos) - 1
            if delta > self.max_delay_suba:
                descartados.append(
                    {
                        "ticker": ticker,
                        "motivo": (
                            f"VETO TARDE: {ticker} ya subió {delta * 100:.2f}% sobre el precio "
                            f"promedio de los fondos (${precio_fondos:,.2f}), por encima del "
                            f"máximo de {self.max_delay_suba * 100:.1f}%."
                        ),
                    }
                )
                continue

            compras.append(self._señal(ticker, compradores, precio_actual, precio_fondos, delta))

        return {"compras": compras, "descartados": descartados, "evaluados": len(agrupados)}

    def _precio_promedio(self, compradores: List[Dict[str, Any]]) -> Optional[float]:
        """Promedio ponderado por valor de los precios de los fondos compradores.

        Ponderado y no simple: un fondo que puso $10.000M pesa más en el precio
        de referencia que uno que puso $50M.
        """
        con_precio = [m for m in compradores if m.get("precio_promedio")]
        if not con_precio:
            return None
        valor_total = sum(m["valor"] for m in con_precio)
        if valor_total <= 0:
            return sum(m["precio_promedio"] for m in con_precio) / len(con_precio)
        return sum(m["precio_promedio"] * m["valor"] for m in con_precio) / valor_total

    def _señal(
        self,
        ticker: str,
        compradores: List[Dict[str, Any]],
        precio_actual: float,
        precio_fondos: float,
        delta: float,
    ) -> Dict[str, Any]:
        señal: Dict[str, Any] = {
            "ticker": ticker,
            "estrategia": ESTRATEGIA,
            "origen": "SMART_MONEY_13F",
            "precio_entrada": round(precio_actual, 2),
            "consenso": len(compradores),
            "fondos": [m["fondo"] for m in compradores],
            "movimientos": [{"fondo": m["fondo"], "tipo": m["tipo"],
                             "peso_cartera": m["peso_cartera"]} for m in compradores],
            "peso_promedio": round(
                sum(m["peso_cartera"] for m in compradores) / len(compradores), 6
            ),
            "precio_promedio_fondos": round(precio_fondos, 2),
            "delta_vs_fondos": round(delta, 4),
        }
        señal.update(self._riesgo(ticker, precio_actual))
        return señal

    def _riesgo(self, ticker: str, precio_actual: float) -> Dict[str, Any]:
        """Stop y objetivo con el mismo criterio que las otras dos fuentes.

        Si no se puede calcular el ATR (sin histórico, sin red), la señal sale
        igual pero con el riesgo en `None`: el consenso institucional es válido
        aunque hoy no tengamos datos técnicos.
        """
        try:
            df = market_data.get_history(ticker, period=technical_filters.PERIODO_HISTORICO)
            atr = float(technical_filters.calculate_atr(df).iloc[-1])
            riesgo = technical_filters.calcular_stop_y_objetivo(precio_actual, atr)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: sin riesgo calculable para la señal 13F (%s)", ticker, exc)
            return {"stop_loss": None, "take_profit": None, "pct_riesgo": None}

        return {
            "stop_loss": round(riesgo["stop_loss"], 2),
            "take_profit": round(riesgo["take_profit"], 2),
            "pct_riesgo": round(riesgo["pct_riesgo"] * 100, 2),
            "ratio_riesgo_beneficio": config.TAKE_PROFIT_RATIO,
        }

    # ---------- Señales de venta ----------

    def senales_de_venta(
        self,
        movimientos: Iterable[Dict[str, Any]],
        posiciones_abiertas: Iterable[str],
    ) -> List[Dict[str, Any]]:
        """Avisa qué posiciones abiertas de esta estrategia salieron de los fondos.

        Basta **un** fondo reduciendo o cerrando para avisar: para entrar se
        exige consenso, para salir no. La asimetría es deliberada — el costo de
        salir antes de tiempo es perderse una suba; el de quedarse, una caída con
        la tesis ya rota.

        Args:
            movimientos: los del último trimestre.
            posiciones_abiertas: tickers que el sistema tiene abiertos bajo la
                estrategia Smart Money.
        """
        abiertas = {t.upper() for t in posiciones_abiertas}
        ventas: List[Dict[str, Any]] = []

        for m in movimientos:
            if m["ticker"] not in abiertas:
                continue
            if m["tipo"] not in edgar_13f.MOVIMIENTOS_DE_VENTA:
                continue
            ventas.append(
                {
                    "ticker": m["ticker"],
                    "estrategia": ESTRATEGIA,
                    "fondo": m["fondo"],
                    "tipo": m["tipo"],
                    "motivo": (
                        f"SALIDA 13F: {m['fondo']} "
                        f"{'cerró' if m['tipo'] == edgar_13f.CIERRE else 'redujo'} "
                        f"su posición en {m['ticker']}."
                    ),
                }
            )

        return ventas
