"""Graded (slab) pricing — roadmap #11, phase 2 of condition/grade.

Covers the graded_price_snapshot series (record/read/staleness), the daily job's
graded_fill (held combos only, budget, give-up), and what GET /portfolio does
with a slab price once one exists.
"""
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import snapshot_all
from app.models import GradedPriceSnapshot, utcnow
from app.services import card_catalog
from app.services.price_history import (
    GRADED_MAX_AGE_DAYS, graded_history, graded_recorded_today,
    latest_graded_prices, record_graded_snapshot,
)
from conftest import TestingSessionLocal, make_card


CHARIZARD = ("base1-4", "PSA", "10")


def seed_graded(card_id, grader, grade, price, days_ago=0, sales=5):
    db = TestingSessionLocal()
    row = GradedPriceSnapshot(card_id=card_id, grader=grader, grade=grade,
                              price=price, sale_count=sales,
                              snapshot_date=utcnow() - timedelta(days=days_ago))
    db.add(row)
    db.commit()
    db.close()


class TestGradedSeries:
    def test_records_one_row_per_holding_per_day(self):
        db = TestingSessionLocal()
        assert record_graded_snapshot(db, *CHARIZARD, 900.0, 6) is True
        assert record_graded_snapshot(db, *CHARIZARD, 900.0, 6) is False
        assert db.query(GradedPriceSnapshot).count() == 1
        db.close()

    def test_same_day_rerun_refreshes_the_price(self):
        db = TestingSessionLocal()
        record_graded_snapshot(db, *CHARIZARD, 900.0, 6)
        record_graded_snapshot(db, *CHARIZARD, 950.0, 8)
        row = db.query(GradedPriceSnapshot).one()
        assert (row.price, row.sale_count) == (950.0, 8)
        db.close()

    def test_grades_of_one_card_are_separate_series(self):
        db = TestingSessionLocal()
        record_graded_snapshot(db, "base1-4", "PSA", "10", 900.0)
        record_graded_snapshot(db, "base1-4", "PSA", "9", 400.0)
        record_graded_snapshot(db, "base1-4", "BGS", "10", 850.0)
        assert db.query(GradedPriceSnapshot).count() == 3
        prices = latest_graded_prices(db, [("base1-4", "PSA", "10"),
                                           ("base1-4", "PSA", "9"),
                                           ("base1-4", "BGS", "10")])
        assert prices[("base1-4", "PSA", "10")][0] == 900.0
        assert prices[("base1-4", "PSA", "9")][0] == 400.0
        assert prices[("base1-4", "BGS", "10")][0] == 850.0
        db.close()

    def test_latest_wins(self):
        seed_graded(*CHARIZARD, 800.0, days_ago=3)
        seed_graded(*CHARIZARD, 900.0, days_ago=1)
        db = TestingSessionLocal()
        assert latest_graded_prices(db, [CHARIZARD])[CHARIZARD][0] == 900.0
        db.close()

    def test_stale_price_is_not_current(self):
        # Past the window, the honest answer is "no current price", not a
        # months-old median presented as today's market
        seed_graded(*CHARIZARD, 900.0, days_ago=GRADED_MAX_AGE_DAYS + 2)
        db = TestingSessionLocal()
        assert latest_graded_prices(db, [CHARIZARD]) == {}
        assert latest_graded_prices(db, [CHARIZARD], max_age_days=None)[CHARIZARD][0] == 900.0
        db.close()

    def test_unknown_holding_is_absent_not_zero(self):
        db = TestingSessionLocal()
        assert latest_graded_prices(db, [CHARIZARD]) == {}
        assert latest_graded_prices(db, []) == {}
        db.close()

    def test_sale_count_rides_along(self):
        seed_graded(*CHARIZARD, 900.0, sales=17)
        db = TestingSessionLocal()
        assert latest_graded_prices(db, [CHARIZARD])[CHARIZARD][2] == 17
        db.close()

    def test_recorded_today_only_reports_wanted_holdings(self):
        db = TestingSessionLocal()
        record_graded_snapshot(db, "base1-4", "PSA", "10", 900.0)
        record_graded_snapshot(db, "base1-4", "PSA", "9", 400.0)
        done = graded_recorded_today(db, [("base1-4", "PSA", "10"),
                                          ("base1-4", "BGS", "10")])
        assert done == {("base1-4", "PSA", "10")}
        db.close()

    def test_history_is_oldest_first(self):
        seed_graded(*CHARIZARD, 800.0, days_ago=2)
        seed_graded(*CHARIZARD, 900.0, days_ago=1)
        db = TestingSessionLocal()
        points = graded_history(db, *CHARIZARD, days=30)
        assert [p["price"] for p in points] == [800.0, 900.0]
        db.close()


def seed_lot(client, headers, card_id="base1-4", **body):
    return client.post("/portfolio/add",
                       json={"card_id": card_id, "purchase_price": 500.0, **body},
                       headers=headers)


class TestHeldCombos:
    def test_lists_distinct_graded_holdings_only(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=50.0))
        upstream.add(make_card("base1-2", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_lot(client, auth_headers, grading="PSA", grade="10")  # a second lot, same holding
        seed_lot(client, auth_headers, grading="BGS", grade="9.5")
        seed_lot(client, auth_headers, grading="Raw", grade="Near Mint")
        seed_lot(client, auth_headers, "base1-2")  # no condition at all

        db = TestingSessionLocal()
        combos = set(snapshot_all.held_graded_combos(db))
        db.close()
        assert combos == {("base1-4", "PSA", "10"), ("base1-4", "BGS", "9.5")}


class FakeGradedEstimator:
    """Stands in for _estimate_graded_one: median per (card, grader, grade)."""

    def __init__(self, medians, failing=frozenset()):
        self.medians = medians
        self.failing = failing
        self.calls = []

    def __call__(self, card, grader, grade):
        key = (card["number"], grader, grade)
        self.calls.append((card["name"], grader, grade))
        if key in self.failing:
            return None
        med = self.medians.get(key)
        return {"count": 7 if med else 0, "median": med}


@pytest.fixture
def graded_fill(monkeypatch):
    """Run graded_fill against the test DB with a fake estimator, no sleeping."""
    monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)

    def run(medians, budget=10, failing=frozenset()):
        fake = FakeGradedEstimator(medians, failing)
        monkeypatch.setattr(snapshot_all, "_estimate_graded_one", fake)
        db = TestingSessionLocal()
        try:
            return snapshot_all.graded_fill(db, budget), fake
        finally:
            db.close()

    return run


def seed_catalog(card_id="base1-4", name="Charizard", number="4",
                 set_name="Base", release="1999/01/09", printed_total=102):
    """Seed a catalog row the way the crawl really does: a BARE collector number
    plus the set's printedTotal. The two are paired into "4/102" by
    _display_number — testing with a pre-joined number hid a bug where the comp
    filter rejected every "4/102" title."""
    db = TestingSessionLocal()
    card = make_card(card_id, name, price=50.0)
    card["number"] = number
    card["set"] = {"id": "base1", "name": set_name, "releaseDate": release,
                   "printedTotal": printed_total}
    card_catalog.upsert_cards(db, [card])
    db.close()


class TestDisplayNumber:
    """The catalog stores "4"; sellers write "4/102". Pairing the two is what
    lets the comp filter recognise a real listing."""

    def test_pairs_a_bare_number_with_the_set_total(self):
        assert snapshot_all._display_number("4", 102) == "4/102"

    def test_leaves_a_lettered_number_alone(self):
        assert snapshot_all._display_number("SWSH066", 307) == "SWSH066"
        assert snapshot_all._display_number("TG12", 30) == "TG12"

    def test_falls_back_to_the_bare_number_without_a_set_total(self):
        assert snapshot_all._display_number("4", None) == "4"

    def test_passes_through_nothing(self):
        assert snapshot_all._display_number(None, 102) is None


class TestGradedFill:
    def test_prices_held_slabs_and_snapshots_them(self, client, auth_headers,
                                                  upstream, graded_fill):
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        seed_lot(client, auth_headers, grading="PSA", grade="10")

        result, fake = graded_fill({("4/102", "PSA", "10"): 900.0})
        assert result.prices == {("base1-4", "PSA", "10"): 900.0}
        assert result.attempted == 1 and result.eligible == 1
        assert fake.calls == [("Charizard", "PSA", "10")]

        db = TestingSessionLocal()
        assert latest_graded_prices(db, [CHARIZARD])[CHARIZARD][:1] == (900.0,)
        db.close()

    def test_passes_the_set_year_to_the_estimator(self, client, auth_headers,
                                                  upstream, monkeypatch):
        # The year is what separates a reprint from the original at the same
        # collector number, so it has to reach the comp filter
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog(release="2021/10/08")
        seed_lot(client, auth_headers, grading="PSA", grade="10")

        seen = {}
        monkeypatch.setattr(snapshot_all.time, "sleep", lambda s: None)
        monkeypatch.setattr(snapshot_all, "_estimate_graded_one",
                            lambda card, g, gr: seen.update(card) or {"count": 0, "median": None})
        db = TestingSessionLocal()
        snapshot_all.graded_fill(db, 10)
        db.close()
        assert seen["year"] == 2021
        assert seen["number"] == "4/102"

    def test_skips_holdings_already_priced_today(self, client, auth_headers,
                                                 upstream, graded_fill):
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_graded(*CHARIZARD, 900.0)

        result, fake = graded_fill({("4/102", "PSA", "10"): 950.0})
        assert fake.calls == [] and result.eligible == 0

    def test_slab_without_recent_comps_records_nothing(self, client, auth_headers,
                                                       upstream, graded_fill):
        # Normal for a slab that hasn't traded lately — costs the run nothing
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        seed_lot(client, auth_headers, grading="PSA", grade="10")

        result, _ = graded_fill({})
        assert result.prices == {} and result.no_sales == 1
        db = TestingSessionLocal()
        assert db.query(GradedPriceSnapshot).count() == 0
        db.close()

    def test_unsearchable_grading_is_not_a_failure(self, client, auth_headers,
                                                  upstream, graded_fill):
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        seed_lot(client, auth_headers, grading="Other", grade="Mint 10")

        result, fake = graded_fill({})
        assert result.unpriceable == 1
        assert result.attempted == 0 and result.failures == 0
        assert fake.calls == []

    def test_card_missing_from_the_catalog_is_skipped(self, client, auth_headers,
                                                     upstream, graded_fill):
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")  # no catalog row

        result, fake = graded_fill({("4/102", "PSA", "10"): 900.0})
        assert result.unpriceable == 1 and fake.calls == []

    def test_budget_caps_the_pass(self, client, auth_headers, upstream, graded_fill):
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_lot(client, auth_headers, grading="PSA", grade="9")
        seed_lot(client, auth_headers, grading="BGS", grade="9.5")

        result, fake = graded_fill({}, budget=2)
        assert len(fake.calls) == 2 and result.eligible == 3

    def test_gives_up_after_consecutive_failed_fetches(self, client, auth_headers,
                                                      upstream, graded_fill):
        # Consecutive failed FETCHES are the bot-block signature
        upstream.add(make_card("base1-4", price=50.0))
        seed_catalog()
        grades = ["10", "9", "8", "7", "6", "5"]
        for g in grades:
            seed_lot(client, auth_headers, grading="PSA", grade=g)

        result, fake = graded_fill(
            {}, budget=10, failing={("4/102", "PSA", g) for g in grades})
        assert result.gave_up is True
        assert result.failures == snapshot_all._EBAY_GIVEUP
        assert len(fake.calls) == snapshot_all._EBAY_GIVEUP

    def test_no_graded_holdings_does_nothing(self, graded_fill):
        result, fake = graded_fill({("4/102", "PSA", "10"): 900.0})
        assert result.attempted == 0 and fake.calls == []


class TestPortfolioUsesGradedPrice:
    def test_graded_lot_priced_from_its_slab_series(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=50.0))  # raw market stays low
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_graded(*CHARIZARD, 900.0, sales=12)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 900.0
        assert row["gain_loss"] == 400.0
        assert row["price_source"] == "ebay_graded"
        assert row["price_sample"] == 12

    def test_graded_lot_without_a_slab_price_stays_at_cost(self, client, auth_headers,
                                                           upstream):
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] is None
        assert row["gain_loss"] is None
        assert row["price_source"] is None

    def test_a_stale_slab_price_falls_back_to_cost(self, client, auth_headers, upstream):
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_graded(*CHARIZARD, 900.0, days_ago=GRADED_MAX_AGE_DAYS + 5)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] is None

    def test_another_grade_never_prices_this_holding(self, client, auth_headers,
                                                     upstream):
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_graded("base1-4", "PSA", "9", 400.0)  # only the 9 has comps

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] is None

    def test_raw_lot_is_untouched_by_the_graded_series(self, client, auth_headers,
                                                      upstream):
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="Raw", grade="Near Mint")
        seed_graded(*CHARIZARD, 900.0)

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 50.0
        assert row["price_source"] is None

    def test_graded_lot_gets_no_day_change_from_the_raw_series(self, client,
                                                               auth_headers, upstream):
        # The raw baseline would measure a slab against the ungraded card's
        # yesterday — a nonsense percentage
        upstream.add(make_card("base1-4", price=50.0))
        seed_lot(client, auth_headers, grading="PSA", grade="10")
        seed_graded(*CHARIZARD, 900.0)
        db = TestingSessionLocal()
        from app.models import CardPriceSnapshot
        db.add(CardPriceSnapshot(card_id="base1-4", price=25.0,
                                 snapshot_date=utcnow() - timedelta(days=1)))
        db.commit()
        db.close()

        [row] = client.get("/portfolio", headers=auth_headers).json()
        assert row["current_price"] == 900.0
        assert row["price_change"] is None
