from __future__ import annotations

from decimal import Decimal

from conftest import amount


def test_base_forecast_is_internally_consistent(client, demo):
    response = client.get("/api/cashflow/forecast?horizon=30&scenario=base", headers=demo["headers"])
    assert response.status_code == 200
    forecast = response.json()

    assert forecast["scenario"] == "base"
    assert forecast["horizon_days"] == 30
    assert len(forecast["series"]) == 31
    assert forecast["series"][0]["balance"] == forecast["opening_balance"]
    assert forecast["series"][-1]["balance"] == forecast["closing_balance"]

    reserve = amount(forecast["minimum_reserve"])
    previous = amount(forecast["opening_balance"])
    running_minimum = previous
    for point in forecast["series"][1:]:
        balance = amount(point["balance"])
        assert balance == previous + amount(point["inflow"]) - amount(point["outflow"])
        assert point["is_forecast"] is True
        assert point["below_reserve"] is (balance < reserve)
        running_minimum = min(running_minimum, balance)
        previous = balance

    assert amount(forecast["minimum_balance"]) == running_minimum
    expected_surplus = max(Decimal("0.00"), running_minimum - reserve)
    assert amount(forecast["investable_surplus"]) == expected_surplus
    assert forecast["assumptions"]["receivables_not_guaranteed"] is True
    assert forecast["assumptions"]["method"].startswith("Rules-based")
    overview = client.get("/api/cashflow/overview?horizon=30", headers=demo["headers"]).json()
    assert overview["data_quality"] in ("low", "medium", "high")


def test_scenarios_order_and_sensitivity(client, demo):
    response = client.get("/api/cashflow/overview?horizon=30", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    scenarios = {row["key"]: row for row in body["scenarios"]}
    assert set(scenarios) == {"conservative", "base", "optimistic"}
    assert amount(scenarios["conservative"]["minimum_balance"]) <= amount(
        scenarios["base"]["minimum_balance"]
    )
    assert amount(scenarios["base"]["minimum_balance"]) <= amount(
        scenarios["optimistic"]["minimum_balance"]
    )

    sensitivity = body["sensitivity"]
    assert [row["key"] for row in sensitivity] == ["base", "conservative", "optimistic"]
    assert "reserve" in body["definitions"]["investable_surplus"].lower()
    assert body["obligations"]
    for obligation in body["obligations"]:
        assert amount(obligation["amount"]) >= 0


def test_reserve_floor_produces_shortfall_and_no_investable_surplus(client, demo):
    updated = client.put(
        "/api/profile",
        json={"min_cash_reserve": "2000000"},
        headers=demo["headers"],
    )
    assert updated.status_code == 200, updated.text

    forecast = client.get(
        "/api/cashflow/forecast?horizon=30&scenario=base", headers=demo["headers"]
    ).json()
    assert forecast["shortfall_date"] is not None
    assert amount(forecast["investable_surplus"]) == 0
    assert amount(forecast["opening_balance"]) < amount(forecast["minimum_reserve"])


def test_save_forecast_snapshot(client, demo):
    created = client.post(
        "/api/cashflow/forecasts?horizon=30&scenario=conservative", headers=demo["headers"]
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert "projection, not a bank balance" in body["message"]
    assert body["forecast"]["scenario"] == "conservative"

    saved = client.get("/api/cashflow/forecasts", headers=demo["headers"]).json()["items"]
    assert saved
    assert saved[0]["id"] == body["id"]
    assert saved[0]["scenario"] == "conservative"
    assert saved[0]["horizon_days"] == 30


def test_unknown_scenario_rejected(client, demo):
    response = client.get("/api/cashflow/forecast?scenario=impossible", headers=demo["headers"])
    assert response.status_code == 400
