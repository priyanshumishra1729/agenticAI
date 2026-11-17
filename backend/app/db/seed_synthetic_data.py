"""Synthetic but internally consistent reference data for the demo."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from app.database import SessionLocal
from app.models import Incident, InventoryRecord, Shipment, Supplier, SystemSettings, Team, User

TEAMS = [("Logistics", "LOG", "A. Gomez"), ("Procurement", "PUR", "M. Chen"), ("Warehouse", "WH", "R. Singh"),
         ("Inventory", "INV", "B. Flores"), ("Quality", "QA", "K. Osei"), ("Operations", "OPS", "D. Patel")]

SUPPLIERS = [
    ("SUP-001", "Northline Supply", "USA", 84, "T1", ["Harbor Peak Foods", "Polar Fresh Co"]),
    ("SUP-002", "BlueHarbor Logistics", "USA", 79, "T1", ["Atlas Freight", "Gulfstream Carriers"]),
    ("SUP-003", "Harbor Peak Foods", "Canada", 91, "T1", ["Northline Supply"]),
    ("SUP-004", "Shenzhen Apex Electronics", "China", 68, "T2", ["Taipei Micro Components", "Penang Circuitworks"]),
    ("SUP-005", "Atlas Freight", "USA", 88, "T1", ["BlueHarbor Logistics"]),
    ("SUP-006", "Monterrey Steel Industries", "Mexico", 72, "T2", ["Ohio Valley Metals"]),
    ("SUP-007", "Rotterdam Chemicals", "Netherlands", 93, "T1", ["Antwerp Polymers"]),
]

SHIPMENTS = [
    ("SHIP-1042", "BlueHarbor Logistics", "SKU-1178", "Houston, TX", "Dallas, TX", "delayed", 36, 48000),
    ("SHIP-8901", "Northline Supply", "SKU-2204", "Minneapolis, MN", "Chicago, IL", "delayed", 12, 92000),
    ("SHIP-3310", "Shenzhen Apex Electronics", "SKU-5510", "Shenzhen, CN", "Long Beach, CA", "held_customs", 96, 310000),
    ("SHIP-2207", "Atlas Freight", "SKU-7720", "Savannah, GA", "Atlanta, GA", "in_transit", 8, 21000),
    ("SHIP-4415", "Monterrey Steel Industries", "SKU-3305", "Monterrey, MX", "Detroit, MI", "delayed", 72, 156000),
    ("SHIP-5120", "Rotterdam Chemicals", "SKU-6601", "Rotterdam, NL", "Newark, NJ", "in_transit", 120, 87000),
    ("SHIP-6033", "Harbor Peak Foods", "SKU-2204", "Vancouver, BC", "Seattle, WA", "in_transit", 18, 64000),
]

INVENTORY = [
    ("SKU-1178", "Industrial Seal Kit", "Houston DC", 280, 80, 45, 500, 18),
    ("SKU-1178", "Industrial Seal Kit", "Dallas DC", 60, 20, 30, 400, 18),
    ("SKU-2204", "Frozen Salmon Portions", "Chicago DC", 140, 95, 60, 300, 42),
    ("SKU-5510", "Microcontroller Board MX-5", "Long Beach DC", 90, 40, 70, 2000, 65),
    ("SKU-5510", "Microcontroller Board MX-5", "Reno DC", 30, 10, 25, 1500, 65),
    ("SKU-7720", "Retail Display Units", "Atlanta DC", 900, 100, 40, 1500, 12),
    ("SKU-3305", "Cold-Rolled Steel Coil", "Detroit DC", 45, 30, 20, 200, 410),
    ("SKU-6601", "Industrial Solvent Drum", "Newark DC", 320, 60, 35, 800, 95),
    ("SKU-8812", "Pharma Cold Pack", "Memphis DC", 50, 35, 30, 500, 120),
]


def _history(now: datetime):
    rows = [
        ("INC-1001", "Port rail congestion delays outbound shipment", "transportation_delay", "Houston, TX", "BlueHarbor Logistics",
         "SHIP-1042", "SKU-1178", 120, 2, "high", "in_review", "Logistics",
         "Rail congestion at the Port of Houston caused container delays and affected replenishment timing."),
        ("INC-1002", "Cold chain temperature excursion on frozen inventory", "cold_chain_excursion", "Chicago, IL", "Northline Supply",
         "SHIP-8901", "SKU-2204", 75, 5, "critical", "escalated", "Quality",
         "Trailer temperature rose above threshold for 4 hours during linehaul transit."),
        ("INC-0991", "Customs hold on electronics container", "transportation_delay", "Long Beach, CA", "Shenzhen Apex Electronics",
         "SHIP-2990", "SKU-5510", 400, 240, "high", "closed", "Logistics",
         "Container held for documentation discrepancy; cleared after broker resubmission."),
        ("INC-0987", "Damaged pallets on retail display delivery", "damaged_goods", "Atlanta, GA", "Atlas Freight",
         "SHIP-1999", "SKU-7720", 34, 300, "low", "closed", "Warehouse",
         "34 pallets arrived crushed after improper load securing."),
        ("INC-0975", "Steel supplier capacity cut", "supplier_failure", "Monterrey, MX", "Monterrey Steel Industries",
         "SHIP-3801", "SKU-3305", 200, 520, "high", "resolved", "Procurement",
         "Supplier announced 40% capacity reduction due to furnace maintenance."),
        ("INC-0968", "WMS outage at Newark DC", "warehouse_disruption", "Newark, NJ", None, None, "SKU-6601", 0, 700, "medium",
         "closed", "Warehouse", "Warehouse management system outage halted picking for 6 hours."),
    ]
    for r in rows:
        yield Incident(incident_id=r[0], title=r[1], category=r[2], incident_type=r[2], location=r[3], supplier=r[4],
                       shipment_id=r[5], product_sku=r[6], quantity_affected=r[7],
                       reported_time=now - timedelta(hours=r[8]), created_at=now - timedelta(hours=r[8]),
                       severity=r[9], status=r[10], description=r[12], verification_status="verified",
                       approval_status="approved" if r[10] in {"closed", "resolved"} else "pending"), r[11]


def seed_synthetic_data() -> Dict[str, Any]:
    with SessionLocal() as db:
        existing = {t.name for t in db.query(Team).all()}
        for name, code, owner in TEAMS:
            if name not in existing:
                db.add(Team(name=name, code=code, owner=owner))
        if not db.query(User).count():
            db.add_all([User(name="Naomi Smith", email="naomi@demo.local", role="Operations Manager"),
                        User(name="Patrick Lee", email="patrick@demo.local", role="Warehouse Lead")])
        if not db.query(Supplier).count():
            db.add_all([Supplier(supplier_id=a, name=b, country=c, reliability=d, tier=e, alternates=f) for a, b, c, d, e, f in SUPPLIERS])
        if not db.query(Shipment).count():
            db.add_all([Shipment(shipment_id=a, supplier_name=b, sku=c, origin=d, destination=e, status=f, eta_hours=g, value_usd=h)
                        for a, b, c, d, e, f, g, h in SHIPMENTS])
        if not db.query(InventoryRecord).count():
            db.add_all([InventoryRecord(sku=a, product_name=b, warehouse=c, on_hand=d, reserved=e, daily_demand=f, capacity=g,
                                        unit_cost_usd=h) for a, b, c, d, e, f, g, h in INVENTORY])
        db.flush()
        if not db.query(Incident).count():
            teams = {t.name: t.id for t in db.query(Team).all()}
            for inc, team in _history(datetime.utcnow()):
                inc.assigned_team_id = teams.get(team)
                db.add(inc)
        if not db.query(SystemSettings).filter(SystemSettings.key == "severity_bands").first():
            db.add(SystemSettings(key="severity_bands", value={"low": 0, "medium": 35, "high": 55, "critical": 75}))
        db.commit()
    return {"status": "ok"}


if __name__ == "__main__":
    from app.database import init_db

    init_db()
    print(seed_synthetic_data())
