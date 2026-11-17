"""SignalChain MCP server (Model Context Protocol, FastMCP).

Tools
- supplier_shipment_lookup   database lookup (suppliers + shipments tables)
- inventory_lookup           database lookup (inventory table)
- historical_incident_search database search over past incidents
- document_parser            extracts structured fields from a free-text report
- impact_calculator          operational / financial impact calculator
- weather_risk               EXTERNAL API – Open-Meteo geocoding + forecast (no key)

Agents reach these tools through an MCP ClientSession (see ``app.mcp_client``).
Run standalone for external MCP clients (Claude Desktop, MCP Inspector …):
    python -m app.mcp_server            # stdio transport
"""


import re
import time
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from app.core.config import settings

mcp = FastMCP(
    "signalchain-tools",
    instructions="Supply-chain incident tools: database lookups, document parsing, impact calculation and live weather risk.",
)


def _db():
    from app.database import SessionLocal

    return SessionLocal()


@mcp.tool()
def supplier_shipment_lookup(supplier: str = "", shipment_id: str = "") -> Dict[str, Any]:
    """Look up a supplier profile and shipment record in the operational database."""
    from app.models import Shipment, Supplier

    with _db() as db:
        ship = None
        if shipment_id:
            ship = db.query(Shipment).filter(Shipment.shipment_id.ilike(shipment_id.strip())).first()
        sup = None
        name = supplier or (ship.supplier_name if ship else "")
        if name:
            sup = db.query(Supplier).filter(Supplier.name.ilike(f"%{name.strip()}%")).first()
        return {
            "found": bool(sup or ship),
            "supplier": None if not sup else {"supplier_id": sup.supplier_id, "name": sup.name, "country": sup.country,
                                              "reliability": sup.reliability, "tier": sup.tier},
            "shipment": None if not ship else {"shipment_id": ship.shipment_id, "sku": ship.sku, "origin": ship.origin,
                                               "destination": ship.destination, "status": ship.status,
                                               "eta_hours": ship.eta_hours, "value_usd": ship.value_usd},
            "alternates": list(sup.alternates or []) if sup else [],
        }


@mcp.tool()
def inventory_lookup(product_sku: str = "") -> Dict[str, Any]:
    """Return on-hand / reserved stock, daily demand and days of cover for a SKU across warehouses."""
    from app.models import InventoryRecord

    with _db() as db:
        rows = db.query(InventoryRecord).filter(InventoryRecord.sku.ilike(product_sku.strip())).all() if product_sku else []
        warehouses = [
            {"warehouse": r.warehouse, "product_name": r.product_name, "on_hand": r.on_hand, "reserved": r.reserved,
             "available": max(0, r.on_hand - r.reserved), "daily_demand": r.daily_demand, "capacity": r.capacity,
             "unit_cost_usd": r.unit_cost_usd}
            for r in rows
        ]
        available = sum(w["available"] for w in warehouses)
        demand = sum(w["daily_demand"] for w in warehouses)
        return {
            "found": bool(rows),
            "sku": product_sku or None,
            "total_available": available,
            "total_daily_demand": demand,
            "days_of_cover": round(available / demand, 1) if demand else 0.0,
            "warehouses": warehouses,
        }


@mcp.tool()
def historical_incident_search(category: str = "", supplier: str = "", location: str = "", exclude_incident_id: str = "") -> Dict[str, Any]:
    """Search past incidents with the same category, supplier or location (for duplicates and precedent)."""
    from app.models import Incident

    with _db() as db:
        rows = db.query(Incident).order_by(Incident.reported_time.desc()).limit(500).all()
    city = (location or "").split(",")[0].strip().lower()
    matches = []
    for r in rows:
        if (exclude_incident_id and r.incident_id == exclude_incident_id) or r.incident_type == "evaluation":
            continue  # evaluation fixtures never count as operational history
        score = 0
        if category and r.category == category:
            score += 40
        if supplier and r.supplier and supplier.lower() in r.supplier.lower():
            score += 35
        if city and city in (r.location or "").lower():
            score += 25
        if score >= 60:
            matches.append({"incident_id": r.incident_id, "title": r.title, "category": r.category, "supplier": r.supplier,
                            "location": r.location, "severity": r.severity, "status": r.status,
                            "shipment_id": r.shipment_id, "similarity": score,
                            "reported_time": r.reported_time.isoformat() if r.reported_time else None})
    matches.sort(key=lambda m: -m["similarity"])
    history_hours = {"transportation_delay": 9.5, "supplier_failure": 30.0, "inventory_shortage": 18.0, "damaged_goods": 6.0,
                     "warehouse_disruption": 14.0, "cold_chain_excursion": 11.0, "quality_defect": 26.0}
    return {"count": len(matches), "incidents": matches[:5], "avg_resolution_hours": history_hours.get(category)}


_CATEGORY_HINTS = {
    "cold_chain_excursion": ["temperature", "cold chain", "reefer", "thaw", "frozen", "excursion"],
    "damaged_goods": ["damaged", "broken", "crushed", "leaking", "dented", "water damage"],
    "supplier_failure": ["bankrupt", "insolvency", "shutdown", "capacity", "supplier outage", "force majeure", "strike"],
    "inventory_shortage": ["stockout", "stock-out", "shortage", "out of stock", "backorder", "depleted"],
    "warehouse_disruption": ["warehouse", "dock", "forklift", "power outage", "fire", "flood", "wms"],
    "quality_defect": ["defect", "contamination", "recall", "nonconform", "failed inspection", "quality"],
    "transportation_delay": ["delay", "congestion", "customs", "port", "rail", "truck", "late", "missed pickup", "vessel"],
}


@mcp.tool()
def document_parser(description: str = "") -> Dict[str, Any]:
    """Extract supplier, shipment id, SKU, quantity, location and a category hint from a free-text incident report."""
    text = description or ""
    low = text.lower()
    ship = re.search(r"\bSHIP-[A-Z0-9-]+\b", text, re.IGNORECASE)
    sku = re.search(r"\bSKU-[A-Z0-9-]+\b", text, re.IGNORECASE)
    qty = re.search(r"(\d[\d,]*)\s*(units|pallets|cases|cartons|containers|pcs|items)", low)
    loc = re.search(r"\b(?:at|in|near)\s+([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?(?:,\s?[A-Z]{2})?)", text)
    sup = re.search(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)?\s(?:Logistics|Supply|Freight|Foods|Industries|Manufacturing|Components|Electronics))\b", text)
    hits = {cat: sum(1 for k in kws if k in low) for cat, kws in _CATEGORY_HINTS.items()}
    best = max(hits.items(), key=lambda kv: kv[1])
    return {
        "supplier": sup.group(1) if sup else None,
        "shipment_id": ship.group(0).upper() if ship else None,
        "sku": sku.group(0).upper() if sku else None,
        "quantity": int(qty.group(1).replace(",", "")) if qty else None,
        "location": loc.group(1) if loc else None,
        "category_hint": best[0] if best[1] else None,
        "keywords": sorted({k for kws in _CATEGORY_HINTS.values() for k in kws if k in low})[:10],
    }


@mcp.tool()
def impact_calculator(quantity_affected: int = 0, total_available: int = 0, daily_demand: int = 0,
                      unit_cost_usd: int = 25, delay_hours: int = 24) -> Dict[str, Any]:
    """Calculate shortage units, days of cover, revenue at risk, expedite cost and SLA-breach risk."""
    quantity_affected, total_available, daily_demand = max(0, quantity_affected), max(0, total_available), max(0, daily_demand)
    demand_during_delay = int(daily_demand * delay_hours / 24)
    shortage = max(0, demand_during_delay - total_available) + max(0, quantity_affected - total_available) // 2
    cover = round(total_available / daily_demand, 1) if daily_demand else 0.0
    revenue = int((quantity_affected + shortage) * unit_cost_usd * 2.2)
    expedite = int(quantity_affected * unit_cost_usd * 0.18 + (450 if delay_hours > 24 else 150))
    risk = "high" if (shortage > 0 and cover < 2) or delay_hours >= 72 else "medium" if cover < 5 or delay_hours >= 24 else "low"
    return {"shortage_units": shortage, "days_of_cover": cover, "revenue_at_risk_usd": revenue,
            "expedite_cost_usd": expedite, "sla_breach_risk": risk}


_weather_cache: Dict[str, Any] = {}


@mcp.tool()
async def weather_risk(location: str = "") -> Dict[str, Any]:
    """Live weather disruption risk for a location (Open-Meteo geocoding + 48h forecast)."""
    key = (location or "").strip().lower()
    if not key:
        return {"location": location, "source": "none", "risk_level": "unknown", "summary": "No location given."}
    cached = _weather_cache.get(key)
    if cached and time.time() - cached[0] < 1800:
        return cached[1]
    if not settings.enable_external_apis:
        return {"location": location, "source": "offline", "risk_level": "unknown", "summary": "External APIs disabled."}
    try:
        city = location.split(",")[0].strip()
        async with httpx.AsyncClient(timeout=4.0) as client:
            geo = (await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1})).json()
            if not geo.get("results"):
                raise ValueError("location not found")
            g = geo["results"][0]
            fc = (await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": g["latitude"], "longitude": g["longitude"], "forecast_days": 2, "timezone": "auto",
                "daily": "wind_speed_10m_max,precipitation_sum,weather_code"})).json()
        wind = max(fc["daily"]["wind_speed_10m_max"])
        rain = round(sum(fc["daily"]["precipitation_sum"]), 1)
        level = "high" if wind >= 60 or rain >= 40 else "moderate" if wind >= 35 or rain >= 15 else "low"
        out = {"location": f"{g['name']}, {g.get('admin1') or g.get('country', '')}".strip(", "), "source": "open-meteo",
               "latitude": g["latitude"], "longitude": g["longitude"], "max_wind_kmh": wind, "precipitation_mm": rain,
               "risk_level": level, "summary": f"48h outlook: max wind {wind} km/h, precipitation {rain} mm -> {level} transport risk."}
    except Exception as exc:
        out = {"location": location, "source": "unavailable", "risk_level": "unknown", "summary": f"Weather API unavailable ({type(exc).__name__})."}
    _weather_cache[key] = (time.time(), out)
    return out


if __name__ == "__main__":
    from app.database import init_db

    init_db()
    mcp.run()  # stdio
