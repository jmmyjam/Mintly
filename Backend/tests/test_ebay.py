"""eBay sold-listings estimator: HTML parsing, graded/junk filtering, robust
median/average, and the /cards/{id}/ebay-price endpoint (network faked)."""
import pytest

from app.routers import cards
from app.services import ebay_prices
from app.models import CardPriceSnapshot
from conftest import TestingSessionLocal


def card_html(title: str, sold: str, price: str) -> str:
    # Mirrors eBay's real markup: title in the image alt, "Sold <date>" then the
    # sold price inside a .su-card-container tile.
    return (
        f'<li class="su-card-container">'
        f'<img alt="{title}" src="x">'
        f'<span class="su-styled-text">Sold  {sold}</span>'
        f'<span class="su-styled-text">{price}</span>'
        f'</li>'
    )


def page(*cards: str) -> str:
    # A promo "Shop on eBay" tile (no sold date) leads real result pages.
    promo = '<li class="su-card-container"><img alt="Shop on eBay"><span>$20.00</span></li>'
    return f'<html><body><ul>{promo}{"".join(cards)}</ul></body></html>'


class TestBuildQuery:
    def test_number_pins_the_card_and_excludes_graded(self):
        q = ebay_prices.build_query("Mega Lucario ex", "188/132", "Mega Evolution")
        assert q == "Mega Lucario ex 188/132 -psa -bgs -cgc"

    def test_falls_back_to_set_name_without_number(self):
        q = ebay_prices.build_query("Pikachu", None, "Base Set")
        assert q == "Pikachu Base Set -psa -bgs -cgc"


class TestSearchUrl:
    def test_untagged_without_campaign_id(self, monkeypatch):
        monkeypatch.setattr(ebay_prices, "_EPN_CAMPAIGN_ID", "")
        url = ebay_prices.search_url("pikachu 58/102")
        assert "campid" not in url and "mkcid" not in url
        assert "_nkw=pikachu+58%2F102" in url and "LH_Sold=1" in url

    def test_epn_params_appended_with_campaign_id(self, monkeypatch):
        monkeypatch.setattr(ebay_prices, "_EPN_CAMPAIGN_ID", "5338000000")
        url = ebay_prices.search_url("pikachu")
        for param in ("campid=5338000000", "mkcid=1", "mkrid=711-53200-19255-0",
                      "siteid=0", "mkevt=1", "toolid=10001"):
            assert param in url
        # the original search params must survive the tagging
        assert "_nkw=pikachu" in url and "LH_Sold=1" in url and "LH_Complete=1" in url

    def test_summarize_source_url_carries_the_tag(self, monkeypatch):
        monkeypatch.setattr(ebay_prices, "_EPN_CAMPAIGN_ID", "5338000000")
        result = ebay_prices.summarize([], "pikachu")
        assert result["count"] == 0
        assert "campid=5338000000" in result["source_url"]


class TestParseSold:
    def test_extracts_date_price_title(self):
        sales = ebay_prices.parse_sold(page(card_html("Mega Lucario ex 188", "Jul 14, 2026", "$260.00")))
        assert sales == [{"date": "2026-07-14", "price": 260.0, "title": "Mega Lucario ex 188"}]

    def test_skips_promo_tiles_without_sold_date(self):
        assert ebay_prices.parse_sold(page()) == []

    def test_excludes_graded_slabs(self):
        html = page(
            card_html("Mega Lucario ex 188", "Jul 14, 2026", "$250.00"),
            card_html("Mega Lucario ex 188 PSA 10", "Jul 14, 2026", "$900.00"),
            card_html("Mega Lucario ex 188 CGC 9.5", "Jul 13, 2026", "$700.00"),
        )
        sales = ebay_prices.parse_sold(html)
        assert [s["price"] for s in sales] == [250.0]

    def test_excludes_lots_and_proxies(self):
        html = page(
            card_html("Mega Lucario ex 188", "Jul 14, 2026", "$250.00"),
            card_html("Lot of 5 Pokemon cards", "Jul 14, 2026", "$40.00"),
            card_html("Mega Lucario ex proxy custom", "Jul 14, 2026", "$3.00"),
        )
        assert [s["price"] for s in ebay_prices.parse_sold(html)] == [250.0]

    def test_price_taken_after_sold_marker(self):
        # A shipping figure before the sold price must not win
        html = (
            '<li class="su-card-container"><img alt="Card 1">'
            '<span>$4.99 shipping</span><span>Sold  Jul 14, 2026</span>'
            '<span>$250.00</span></li>'
        )
        assert ebay_prices.parse_sold(f"<ul>{html}</ul>")[0]["price"] == 250.0

    def test_sorted_newest_first(self):
        html = page(
            card_html("Card A", "Jul 10, 2026", "$10.00"),
            card_html("Card B", "Jul 14, 2026", "$20.00"),
        )
        assert [s["date"] for s in ebay_prices.parse_sold(html)] == ["2026-07-14", "2026-07-10"]


class TestSummarize:
    def _sales(self, *prices):
        return [{"date": "2026-07-14", "price": p, "title": "x"} for p in prices]

    def test_median_and_average(self):
        s = ebay_prices.summarize(self._sales(100.0, 200.0, 300.0), "q")
        assert s["median"] == 200.0
        assert s["average"] == 200.0
        assert s["count"] == 3

    def test_too_few_sales_returns_empty(self):
        s = ebay_prices.summarize(self._sales(100.0, 200.0), "q")
        assert s["count"] == 0
        assert s["median"] is None
        assert s["source_url"].startswith("https://www.ebay.com/sch/")

    def test_outliers_trimmed_around_median(self):
        # 250 is the recent median; the 1400 graded-slab escapee and 5 proxy
        # are >3x / <0.35x and get dropped before the average
        s = ebay_prices.summarize(self._sales(250.0, 260.0, 240.0, 1400.0, 5.0), "q")
        assert s["count"] == 3
        assert s["high"] == 260.0
        assert s["low"] == 240.0

    def test_only_most_recent_window_used(self):
        many = [{"date": "2026-07-14", "price": 100.0, "title": "x"} for _ in range(30)]
        many += [{"date": "2020-01-01", "price": 999.0, "title": "old"}]
        s = ebay_prices.summarize(many, "q")
        assert s["high"] == 100.0  # the old $999 sale is outside the recent window


class TestBlockDetection:
    def test_error_page_flagged(self):
        assert ebay_prices._looks_blocked("<title>Error Page | eBay</title> SORRY")

    def test_pardon_interruption_challenge_flagged(self):
        # eBay's ~120KB PerimeterX/HUMAN bot challenge: a valid 200, but spinners
        # and no listings. Caught by both the title and the size floor.
        html = ("<html><head><title>Pardon Our Interruption...</title></head><body>"
                + "x" * 120_000 + "</body></html>")
        assert ebay_prices._looks_blocked(html)

    def test_challenge_title_flagged_even_when_large(self):
        # A challenge page bloated past the size floor is still caught by its title.
        big = ("<html><head><title>Pardon Our Interruption...</title></head>"
               + "x" * 300_000 + "</html>")
        assert ebay_prices._looks_blocked(big)

    def test_small_page_flagged(self):
        # Any page far under a real ~1MB+ results page is a challenge/interstitial,
        # even one whose title we don't recognize.
        assert ebay_prices._looks_blocked("<html>" + "x" * 100_000 + "</html>")

    def test_real_page_not_flagged(self):
        # A genuine results page is ~1MB+; "something went wrong" buried in its
        # scripts must not trip the detector.
        big = "<html>" + "x" * 300_000 + " something went wrong in a script </html>"
        assert not ebay_prices._looks_blocked(big)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeCardUpstream:
    def __init__(self, card):
        self.card = card

    def get(self, url, params=None, timeout=None):
        return FakeResponse(200, {"data": self.card})


class TestEndpoint:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        ebay_prices._cache.clear()
        cards._cache.clear()
        yield

    def test_endpoint_returns_estimate(self, client, monkeypatch):
        card = {"id": "me1-188", "name": "Mega Lucario ex", "number": "188/132",
                "set": {"name": "Mega Evolution"}}
        monkeypatch.setattr(cards, "session", FakeCardUpstream(card))
        html = page(
            card_html("Mega Lucario ex 188", "Jul 14, 2026", "$250.00"),
            card_html("Mega Lucario ex 188", "Jul 13, 2026", "$260.00"),
            card_html("Mega Lucario ex 188", "Jul 12, 2026", "$240.00"),
        )
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: html)
        body = client.get("/cards/me1-188/ebay-price").json()
        assert body["count"] == 3
        assert body["median"] == 250.0
        assert body["since"] == "2026-07-12"
        assert body["until"] == "2026-07-14"

    def test_endpoint_empty_when_fetch_blocked(self, client, monkeypatch):
        card = {"id": "me1-1", "name": "Test", "number": "1/1", "set": {"name": "X"}}
        monkeypatch.setattr(cards, "session", FakeCardUpstream(card))
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: None)
        body = client.get("/cards/me1-1/ebay-price").json()
        assert body["count"] == 0
        assert body["median"] is None

    @staticmethod
    def _snapshot_price(card_id):
        db = TestingSessionLocal()
        row = (db.query(CardPriceSnapshot)
                 .filter(CardPriceSnapshot.card_id == card_id).one_or_none())
        db.close()
        return row.price if row else None

    def test_usable_estimate_records_snapshot(self, client, monkeypatch):
        # A priceless card's estimate is snapshotted so its history point keeps
        # step with the median the page shows (median of $240/$250/$260 = $250).
        card = {"id": "me1-200", "name": "Mega X", "number": "200/132",
                "set": {"name": "Mega Evolution"}}
        monkeypatch.setattr(cards, "session", FakeCardUpstream(card))
        html = page(
            card_html("Mega X 200", "Jul 14, 2026", "$250.00"),
            card_html("Mega X 200", "Jul 13, 2026", "$260.00"),
            card_html("Mega X 200", "Jul 12, 2026", "$240.00"),
        )
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: html)
        client.get("/cards/me1-200/ebay-price")
        assert self._snapshot_price("me1-200") == 250.0

    def test_blocked_estimate_records_no_snapshot(self, client, monkeypatch):
        card = {"id": "me1-201", "name": "Test", "number": "1/1", "set": {"name": "X"}}
        monkeypatch.setattr(cards, "session", FakeCardUpstream(card))
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: None)
        client.get("/cards/me1-201/ebay-price")
        assert self._snapshot_price("me1-201") is None

    def test_priced_card_estimate_never_overwrites_snapshot(self, client, monkeypatch):
        # A card TCGPlayer CAN price must not get an eBay-median snapshot here —
        # that would clobber its real market history.
        card = {"id": "base1-4", "name": "Charizard", "number": "4/102",
                "set": {"name": "Base"},
                "tcgplayer": {"prices": {"holofoil": {"market": 300.0}}}}
        monkeypatch.setattr(cards, "session", FakeCardUpstream(card))
        html = page(
            card_html("Charizard 4", "Jul 14, 2026", "$250.00"),
            card_html("Charizard 4", "Jul 13, 2026", "$260.00"),
            card_html("Charizard 4", "Jul 12, 2026", "$240.00"),
        )
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: html)
        client.get("/cards/base1-4/ebay-price")
        assert self._snapshot_price("base1-4") is None
