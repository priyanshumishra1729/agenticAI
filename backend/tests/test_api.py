INCIDENT = {
    "title": "Port delay on outbound shipment",
    "description": "Outbound container SHIP-1042 delayed by weather at the port. Contact ops@example.com or 555-123-4567.",
    "category": "transportation_delay",
    "location": "Houston, TX",
    "supplier": "BlueHarbor Logistics",
    "shipment_id": "SHIP-1042",
    "product_sku": "SKU-1178",
    "quantity_affected": 40,
}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/health").json()["llm_mode"].startswith("simulated")


def test_create_and_list_incident(client):
    r = client.post("/api/incidents", json=INCIDENT)
    assert r.status_code == 200, r.text
    assert r.json()["incident_id"].startswith("INC-")
    assert any(i["title"] == INCIDENT["title"] for i in client.get("/api/incidents").json())


def test_schema_validation_rejects_bad_payload(client):
    r = client.post("/api/incidents", json={**INCIDENT, "quantity_affected": -5})
    assert r.status_code == 422


def test_analytics_and_system(client):
    a = client.get("/api/analytics/summary").json()
    assert a["total_incidents"] >= 1 and "severity_distribution" in a
    s = client.get("/api/system").json()
    assert s["pipeline"]["type"] == "SequentialAgent"
    assert {c["name"] for c in s["pipeline"]["children"]} >= {"intake_agent", "context_gatherers", "crew_liaison_agent", "reviewer_agent"}


def test_incident_lifecycle(client):
    inc = client.post("/api/incidents", json={**INCIDENT, "title": "Lifecycle test incident"}).json()
    iid = inc["id"]
    assert client.post(f"/api/incidents/{iid}/approve", json={"approved": True}).status_code == 400  # no plan yet
    assert client.post(f"/api/incidents/{iid}/workflow").status_code == 200
    assert client.post(f"/api/incidents/{iid}/approve", json={"approved": True}).json()["approved"] is True
    assert client.post(f"/api/incidents/{iid}/evidence", json={"summary": "Carrier delivered on revised ETA."}).status_code == 200
    assert client.post(f"/api/incidents/{iid}/verify-resolution").json()["verified"] is True
    assert client.post(f"/api/incidents/{iid}/close").json()["status"] == "closed"
    detail = client.get(f"/api/incidents/{iid}/detail").json()
    assert detail["incident"]["status"] == "closed"
    assert [e["type"] for e in detail["events"]][0] == "closed"
