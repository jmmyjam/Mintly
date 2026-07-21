"""TCGCSV price client: set-name→group matching, card-number normalization,
the products×prices join, variant mapping, and its never-raise failure modes
(network faked — the fetch helpers are monkeypatched with fixture JSON)."""
import pytest

from app.services import tcgcsv


GROUPS = [
    {"groupId": 24380, "name": "ME05: Pitch Black"},
    {"groupId": 604, "name": "Crown Zenith: Galarian Gallery"},
    {"groupId": 7, "name": "Base Set"},
    {"groupId": 1428, "name": "XY - Ancient Origins"},
    {"groupId": 1364, "name": "Diamond and Pearl"},
]

PRODUCTS = [
    {"productId": 1, "name": "Tropius",
     "extendedData": [{"name": "Rarity", "value": "Common"},
                      {"name": "Number", "value": "001/084"}]},
    {"productId": 2, "name": "Lurantis ex",
     "extendedData": [{"name": "Number", "value": "004/084"}]},
    {"productId": 3, "name": "Booster Box", "extendedData": []},  # not a card
    {"productId": 4, "name": "Gallery Card",
     "extendedData": [{"name": "Number", "value": "TG12/TG30"}]},
    {"productId": 5, "name": "Priceless Card",
     "extendedData": [{"name": "Number", "value": "009/084"}]},
    {"productId": 6, "name": "Vintage Holo",
     "extendedData": [{"name": "Number", "value": "010/062"}]},
]

PRICES = [
    {"productId": 1, "subTypeName": "Normal", "lowPrice": 0.01, "midPrice": 0.08,
     "highPrice": 1.0, "marketPrice": 0.04, "directLowPrice": None},
    {"productId": 1, "subTypeName": "Reverse Holofoil", "lowPrice": 0.05,
     "midPrice": 0.25, "highPrice": 2.0, "marketPrice": 0.15},
    {"productId": 2, "subTypeName": "Holofoil", "lowPrice": 1.0, "midPrice": 2.0,
     "highPrice": 3.0, "marketPrice": 1.5},
    {"productId": 3, "subTypeName": "Normal", "marketPrice": 99.0},  # no Number
    {"productId": 4, "subTypeName": "Normal", "lowPrice": 5.0, "highPrice": 9.0,
     "marketPrice": None, "midPrice": None},  # nothing extract_price could use
    {"productId": 5, "subTypeName": "1st Edition Holofoil", "midPrice": 40.0,
     "marketPrice": None},  # mid-only rows still count
    # vintage WOTC subtypes map onto the keys pokemontcg.io uses
    {"productId": 6, "subTypeName": "Unlimited Holofoil", "marketPrice": 42.5,
     "midPrice": 30.0},
    {"productId": 6, "subTypeName": "1st Edition", "marketPrice": 81.9,
     "midPrice": 113.25},
]


@pytest.fixture(autouse=True)
def fake_fetches(monkeypatch):
    """Serve the fixture JSON and reset the module memos between tests."""
    monkeypatch.setattr(tcgcsv, "_groups_cache", None)
    monkeypatch.setattr(tcgcsv, "_prices_cache", {})
    monkeypatch.setattr(tcgcsv, "_fetch_groups", lambda: GROUPS)
    monkeypatch.setattr(tcgcsv, "_fetch_products", lambda gid: PRODUCTS)
    monkeypatch.setattr(tcgcsv, "_fetch_prices", lambda gid: PRICES)


class TestGroupMatching:
    def test_code_prefix_on_group_name_is_ignored(self):
        # pokemontcg.io says "Pitch Black"; TCGplayer says "ME05: Pitch Black"
        assert tcgcsv.group_id_for_set("Pitch Black") == 24380

    def test_match_is_case_and_punctuation_insensitive(self):
        assert tcgcsv.group_id_for_set("pitch black") == 24380
        assert tcgcsv.group_id_for_set("Crown Zenith Galarian Gallery") == 604

    def test_era_dash_prefix_on_group_name_is_ignored(self):
        # XY/SM-era groups are "XY - Ancient Origins" style on TCGplayer
        assert tcgcsv.group_id_for_set("Ancient Origins") == 1428

    def test_and_and_ampersand_are_interchangeable(self):
        # pokemontcg.io says "Diamond & Pearl"; TCGplayer says "Diamond and Pearl"
        assert tcgcsv.group_id_for_set("Diamond & Pearl") == 1364

    def test_unknown_set_returns_none(self):
        assert tcgcsv.group_id_for_set("Not A Real Set") is None

    def test_set_id_override_wins_over_name_matching(self, monkeypatch):
        monkeypatch.setattr(tcgcsv, "_GROUP_OVERRIDES", {"me5": 24380})
        assert tcgcsv.group_id_for_set("Totally Different Name", "me5") == 24380

    def test_groups_fetched_once_per_run(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tcgcsv, "_fetch_groups",
                            lambda: calls.append(1) or GROUPS)
        tcgcsv.group_id_for_set("Pitch Black")
        tcgcsv.group_id_for_set("Base Set")
        assert len(calls) == 1


class TestNumberNormalization:
    def test_denominator_and_leading_zeros_dropped(self):
        assert tcgcsv.norm_number("001/084") == "1"
        assert tcgcsv.norm_number("190/086") == "190"

    def test_alphanumeric_numbers_kept(self):
        # Trainer Gallery / promo style numbers must survive (case-folded,
        # since both sides pass through the same normalizer)
        assert tcgcsv.norm_number("TG12/TG30") == "tg12"
        assert tcgcsv.norm_number("TG12") == "tg12"
        assert tcgcsv.norm_number("SWSH039") == "swsh039"

    def test_zero_survives_the_strip(self):
        assert tcgcsv.norm_number("0") == "0"


class TestPricesForGroup:
    def test_join_keyed_by_normalized_number_with_mapped_variants(self):
        joined = tcgcsv.prices_for_group(24380)
        assert joined["1"] == {
            "normal": {"low": 0.01, "mid": 0.08, "high": 1.0, "market": 0.04},
            "reverseHolofoil": {"low": 0.05, "mid": 0.25, "high": 2.0,
                                "market": 0.15},
        }
        assert joined["4"] == {
            "holofoil": {"low": 1.0, "mid": 2.0, "high": 3.0, "market": 1.5},
        }
        assert joined["9"] == {"1stEditionHolofoil": {"mid": 40.0}}

    def test_vintage_wotc_subtypes_map_to_pokemontcgio_keys(self):
        # "Unlimited Holofoil"/"1st Edition" (Fossil-era groups) become the
        # holofoil/1stEditionNormal keys pokemontcg.io itself would use
        joined = tcgcsv.prices_for_group(630)
        assert joined["10"] == {
            "holofoil": {"mid": 30.0, "market": 42.5},
            "1stEditionNormal": {"mid": 113.25, "market": 81.9},
        }

    def test_products_without_numbers_and_null_price_rows_skipped(self):
        joined = tcgcsv.prices_for_group(24380)
        assert "tg12" not in joined  # market AND mid both null
        # the sealed Booster Box (no Number entry) contributes nothing
        assert not any(v.get("market") == 99.0
                       for variants in joined.values()
                       for v in variants.values())

    def test_group_fetched_once_per_run(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tcgcsv, "_fetch_products",
                            lambda gid: calls.append(gid) or PRODUCTS)
        tcgcsv.prices_for_group(24380)
        tcgcsv.prices_for_group(24380)
        assert calls == [24380]


class TestCardPrices:
    def test_returns_tcgplayer_prices_shape(self):
        prices = tcgcsv.card_prices("me5", "Pitch Black", "1")
        assert prices["normal"]["market"] == 0.04

    def test_number_normalized_on_the_lookup_side_too(self):
        assert tcgcsv.card_prices("me5", "Pitch Black", "001/084") is not None

    def test_none_for_unknown_number_set_or_missing_number(self):
        assert tcgcsv.card_prices("me5", "Pitch Black", "999") is None
        assert tcgcsv.card_prices("xx1", "Not A Real Set", "1") is None
        assert tcgcsv.card_prices("me5", "Pitch Black", None) is None


class TestFailureModes:
    """Any fetch failure yields empty/None — never an exception."""

    def test_failed_groups_fetch(self, monkeypatch):
        monkeypatch.setattr(tcgcsv, "_fetch_groups", lambda: None)
        assert tcgcsv.group_id_for_set("Pitch Black") is None

    def test_failed_groups_fetch_leaves_cache_unset_for_retry(self, monkeypatch):
        fetches = [None, GROUPS]
        monkeypatch.setattr(tcgcsv, "_fetch_groups", lambda: fetches.pop(0))
        assert tcgcsv.group_id_for_set("Pitch Black") is None
        assert tcgcsv.group_id_for_set("Pitch Black") == 24380

    def test_failed_products_or_prices_fetch(self, monkeypatch):
        monkeypatch.setattr(tcgcsv, "_fetch_products", lambda gid: None)
        assert tcgcsv.prices_for_group(24380) == {}
        monkeypatch.setattr(tcgcsv, "_fetch_products", lambda gid: PRODUCTS)
        monkeypatch.setattr(tcgcsv, "_fetch_prices", lambda gid: None)
        assert tcgcsv.prices_for_group(24380) == {}

    def test_failed_group_fetch_not_cached_as_empty(self, monkeypatch):
        monkeypatch.setattr(tcgcsv, "_fetch_products", lambda gid: None)
        assert tcgcsv.prices_for_group(24380) == {}
        monkeypatch.setattr(tcgcsv, "_fetch_products", lambda gid: PRODUCTS)
        assert tcgcsv.prices_for_group(24380)["1"]["normal"]["market"] == 0.04
