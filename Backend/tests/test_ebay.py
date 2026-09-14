"""eBay sold-listings estimator: HTML parsing, graded/junk filtering, robust
median/average, and the /cards/{id}/ebay-price endpoint (network faked)."""
import pytest

from app.routers import cards
from app.services import ebay_prices
from app.models import CardPriceSnapshot
from conftest import TestingSessionLocal
from fixtures import ebay_graded_titles as real_titles


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

    def test_graded_searches_for_the_slab_instead_of_excluding_it(self):
        q = ebay_prices.build_query("Charizard", "4/102", "Base", "PSA", "10")
        assert q == "Charizard 4/102 PSA 10"

    def test_graded_query_carries_the_tier_qualifier(self):
        q = ebay_prices.build_query("Charizard", "4/102", "Base", "BGS", "10 (Black Label)")
        assert q == "Charizard 4/102 BGS 10 black label"


class TestSplitGrade:
    def test_plain_number(self):
        assert ebay_prices.split_grade("9.5") == ("9.5", None)

    def test_qualified_tier(self):
        assert ebay_prices.split_grade("10 (Black Label)") == ("10", "black label")
        assert ebay_prices.split_grade("10 (Pristine)") == ("10", "pristine")

    def test_non_numeric(self):
        assert ebay_prices.split_grade("Authentic") == ("Authentic", None)


class TestTitleMatchesGrade:
    """The money-losing failure here is a FALSE MATCH (a holding valued off
    another grade's comps), so every near-miss below must come back False."""

    def match(self, title, grading="PSA", grade="10"):
        return ebay_prices.title_matches_grade(title, grading, grade)

    def test_exact_grade(self):
        assert self.match("2016 Pokemon Charizard PSA 10")

    def test_no_space_between_grader_and_grade(self):
        assert self.match("Charizard PSA10 Gem Mint")

    def test_hyphenated(self):
        assert self.match("Charizard PSA-10")

    def test_grading_vocabulary_between_grader_and_grade(self):
        assert self.match("Charizard PSA GEM MT 10")

    def test_one_digit_grade_does_not_match_ten(self):
        # The headline trap: substring matching reads "PSA 1" out of "PSA 10"
        assert not self.match("Charizard PSA 10", grade="1")

    def test_ten_does_not_match_a_longer_number(self):
        assert not self.match("Charizard PSA 100", grade="10")

    def test_whole_grade_does_not_match_a_half_grade(self):
        assert not self.match("Charizard BGS 9.5", "BGS", "9")

    def test_half_grade_matches_itself(self):
        assert self.match("Charizard BGS 9.5 Gem Mint", "BGS", "9.5")

    def test_half_grade_tail_does_not_match_a_whole_grade(self):
        assert not self.match("Charizard CGC 9.5", "CGC", "5")

    def test_year_prefix_is_not_a_grade(self):
        # "1999 ... PSA" must not price as a PSA 9
        assert not self.match("1999 Pokemon Charizard PSA Graded", grade="9")

    def test_card_number_is_not_a_grade(self):
        # A slab whose title never states the grade, only the card number
        assert not self.match("PSA Pikachu 10/102 Jungle", grade="10")
        assert not self.match("Charizard PSA Graded 4/102", grade="4")

    def test_cert_number_does_not_block_a_match(self):
        assert self.match("Charizard PSA 10 Cert 10203040")

    def test_other_grader_is_not_a_comp(self):
        assert not self.match("Charizard BGS 10", "PSA", "10")

    def test_multi_slab_listing_rejected(self):
        # A pair sale prices neither slab on its own
        assert not self.match("Charizard PSA 9 & PSA 10 pair")

    def test_black_label_is_not_a_plain_ten(self):
        assert not self.match("Charizard BGS 10 Black Label", "BGS", "10")

    def test_plain_ten_is_not_a_black_label(self):
        assert not self.match("Charizard BGS 10 Gem Mint", "BGS", "10 (Black Label)")

    def test_black_label_matches_itself(self):
        assert self.match("Charizard BGS 10 Black Label", "BGS", "10 (Black Label)")

    def test_cgc_pristine_tier_distinguished(self):
        assert self.match("Charizard CGC Pristine 10", "CGC", "10 (Pristine)")
        assert not self.match("Charizard CGC Pristine 10", "CGC", "10")

    def test_pristine_as_seller_adjective_does_not_block_psa(self):
        # "pristine" is a CGC tier but plain English in a PSA title
        assert self.match("Charizard PSA 10 pristine condition")

    def test_authentic_grade(self):
        assert self.match("Charizard PSA Authentic", grade="Authentic")
        assert not self.match("Charizard PSA 10", grade="Authentic")

    def test_unsearchable_grading_never_matches(self):
        assert not self.match("Charizard ACE 10", "Other", "10")
        assert not self.match("Charizard PSA 10", "PSA", "")

    def test_tag_slab_matches(self):
        assert self.match("Charizard TAG 9.5", "TAG", "9.5")

    def test_tag_team_card_subtype_is_not_a_tag_slab(self):
        # "TAG TEAM" is a Pokemon card subtype, not the grading company
        assert not self.match("Pikachu & Zekrom GX TAG TEAM 33/181", "TAG", "10")
        assert not self.match("Pikachu & Zekrom GX TAG TEAM 33/181", "TAG", "33")

    def test_tag_is_not_matched_inside_a_word(self):
        assert not self.match("Vintage Charizard 10 card", "TAG", "10")


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


class TestParseSoldGraded:
    def test_keeps_only_the_wanted_slab(self):
        html = page(
            card_html("Charizard 4/102 PSA 10", "Jul 14, 2026", "$900.00"),
            card_html("Charizard 4/102 PSA 9", "Jul 13, 2026", "$400.00"),
            card_html("Charizard 4/102 BGS 10", "Jul 12, 2026", "$850.00"),
            card_html("Charizard 4/102", "Jul 11, 2026", "$250.00"),  # the raw card
        )
        sales = ebay_prices.parse_sold(html, ("PSA", "10"))
        assert [s["price"] for s in sales] == [900.0]

    def test_junk_filter_still_applies_in_graded_mode(self):
        html = page(
            card_html("Charizard 4/102 PSA 10", "Jul 14, 2026", "$900.00"),
            card_html("Lot of 5 PSA 10 Pokemon cards", "Jul 13, 2026", "$4000.00"),
            card_html("Charizard PSA 10 custom proxy", "Jul 12, 2026", "$15.00"),
        )
        assert [s["price"] for s in ebay_prices.parse_sold(html, ("PSA", "10"))] == [900.0]

    def test_raw_mode_is_unchanged(self):
        html = page(
            card_html("Charizard 4/102", "Jul 14, 2026", "$250.00"),
            card_html("Charizard 4/102 PSA 10", "Jul 13, 2026", "$900.00"),
        )
        assert [s["price"] for s in ebay_prices.parse_sold(html)] == [250.0]

    def test_raw_mode_keeps_tag_team_cards_but_drops_tag_slabs(self):
        # "TAG TEAM" is a card subtype: dropping those titles as slabs left the
        # whole TAG TEAM line without raw comps.
        html = page(
            card_html("Pikachu & Zekrom GX TAG TEAM 33/181", "Jul 14, 2026", "$30.00"),
            card_html("Pikachu & Zekrom GX TAG TEAM TAG 9.5", "Jul 13, 2026", "$200.00"),
        )
        assert [s["price"] for s in ebay_prices.parse_sold(html)] == [30.0]


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


class TestRealSoldTitles:
    """The graded filters run against titles captured from a live eBay sold
    search (tests/fixtures/ebay_graded_titles.py), not invented ones."""

    def _kept(self, title):
        w = real_titles.WANTED
        html = page(card_html(title.replace('"', "'"), "Jul 14, 2026", "$500.00"))
        return bool(ebay_prices.parse_sold(
            html,
            want=(w["grading"], w["grade"]),
            identity=(w["number"], w["year"]),
        ))

    @pytest.mark.parametrize("title", real_titles.KEEP)
    def test_real_comps_survive(self, title):
        assert self._kept(title), f"dropped a genuine comp: {title}"

    @pytest.mark.parametrize("title,why", real_titles.DROP)
    def test_wrong_listings_dropped(self, title, why):
        assert not self._kept(title), f"kept a {why}: {title}"


class TestCardIdentity:
    def test_number_alone_is_too_loose_to_use(self):
        # A bare "4" appears in prices, years, and other numbers; only "4/102"
        # or "#4" count as the collector number
        assert not ebay_prices.title_matches_card("Charizard 4 PSA 10", "4/102", None)

    def test_hash_number_without_denominator_counts(self):
        assert ebay_prices.title_matches_card("Charizard Holo #4 PSA 10", "4/102", None)

    def test_hash_number_of_another_set_rejected(self):
        assert not ebay_prices.title_matches_card("Dark Charizard #4/82", "4/102", None)

    def test_year_mismatch_rejected(self):
        assert not ebay_prices.title_matches_card(
            "1999 Charizard Base Set #4", "4/102", 2021)

    def test_year_absent_is_not_penalised(self):
        assert ebay_prices.title_matches_card("Charizard 4/102 Holo", "4/102", 2021)

    def test_no_identity_given_keeps_everything(self):
        assert ebay_prices.title_matches_card("anything at all", None, None)


class TestGradedEstimate:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        ebay_prices._cache.clear()
        yield

    def _serve(self, monkeypatch, by_query):
        monkeypatch.setattr(ebay_prices, "_fetch_sold_html", lambda q: by_query.get(q))

    def test_prices_the_slab_not_the_raw_card(self, monkeypatch):
        self._serve(monkeypatch, {
            "Charizard 4/102 PSA 10": page(
                card_html("Charizard 4/102 PSA 10", "Jul 14, 2026", "$900.00"),
                card_html("Charizard 4/102 PSA 10", "Jul 13, 2026", "$950.00"),
                card_html("Charizard 4/102 PSA 10", "Jul 12, 2026", "$850.00"),
            ),
        })
        est = ebay_prices.estimate("Charizard", "4/102", "Base", "PSA", "10")
        assert est["count"] == 3 and est["median"] == 900.0

    def test_raw_and_graded_estimates_cache_separately(self, monkeypatch):
        self._serve(monkeypatch, {
            "Charizard 4/102 -psa -bgs -cgc": page(
                *[card_html("Charizard 4/102", "Jul 14, 2026", "$250.00")] * 3),
            "Charizard 4/102 PSA 10": page(
                *[card_html("Charizard 4/102 PSA 10", "Jul 14, 2026", "$900.00")] * 3),
        })
        raw = ebay_prices.estimate("Charizard", "4/102", "Base")
        graded = ebay_prices.estimate("Charizard", "4/102", "Base", "PSA", "10")
        assert raw["median"] == 250.0
        assert graded["median"] == 900.0

    def test_raw_grading_takes_the_ungraded_path(self, monkeypatch):
        self._serve(monkeypatch, {
            "Charizard 4/102 -psa -bgs -cgc": page(
                *[card_html("Charizard 4/102", "Jul 14, 2026", "$250.00")] * 3),
        })
        est = ebay_prices.estimate("Charizard", "4/102", "Base", "Raw", "Near Mint")
        assert est["median"] == 250.0

    def test_unsearchable_grading_returns_empty_not_the_raw_price(self, monkeypatch):
        # "Other" has no title form to search. Falling back to the raw figure
        # would report an ungraded price as a slab's value.
        self._serve(monkeypatch, {
            "Charizard 4/102 -psa -bgs -cgc": page(
                *[card_html("Charizard 4/102", "Jul 14, 2026", "$250.00")] * 3),
        })
        est = ebay_prices.estimate("Charizard", "4/102", "Base", "Other", "Mint 10")
        assert est["count"] == 0 and est["median"] is None

    def test_no_comps_returns_empty(self, monkeypatch):
        # A slab that hasn't sold 3 times in eBay's ~90-day window has no free
        # comp; the caller keeps valuing it at cost.
        self._serve(monkeypatch, {
            "Charizard 4/102 BGS 9.5": page(
                card_html("Charizard 4/102 BGS 9.5", "Jul 14, 2026", "$500.00")),
        })
        est = ebay_prices.estimate("Charizard", "4/102", "Base", "BGS", "9.5")
        assert est["count"] == 0 and est["median"] is None


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
