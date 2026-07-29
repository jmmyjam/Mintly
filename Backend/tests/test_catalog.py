"""The local card catalog: service queries, and the cards router serving
browse traffic from the DB once a complete crawl has stamped the sync marker —
with upstream proxy fallback (plus catalog top-up) everywhere else."""
import pytest

from app.routers import cards
from app.services import card_catalog
from conftest import TestingSessionLocal
from test_search import FakePagedUpstream


def catalog_card(card_id: str, name: str, number: str = "1",
                 set_id: str | None = None, set_name: str = "Some Set",
                 release: str = "2023/01/01", rarity: str | None = None,
                 types: list[str] | None = None,
                 price: float | None = 10.0) -> dict:
    card = {
        "id": card_id,
        "name": name,
        "number": number,
        "set": {"id": set_id or card_id.split("-")[0], "name": set_name,
                "releaseDate": release},
        "images": {"small": f"https://img.example/{card_id}/s",
                   "large": f"https://img.example/{card_id}/l"},
    }
    if rarity:
        card["rarity"] = rarity
    if types:
        card["types"] = types
    if price is not None:
        card["tcgplayer"] = {"prices": {"holofoil": {"market": price}}}
    return card


def seed_catalog(cards_list: list[dict], synced: bool = True) -> None:
    db = TestingSessionLocal()
    card_catalog.upsert_cards(db, cards_list)
    if synced:
        card_catalog.mark_full_sync(db)
    db.close()


def age_price(card_id: str) -> None:
    db = TestingSessionLocal()
    row = card_catalog.get_card(db, card_id)
    row.price_updated_at = None  # unambiguously stale
    db.commit()
    db.close()


@pytest.fixture
def cards_upstream(monkeypatch):
    fake = FakePagedUpstream()
    monkeypatch.setattr(cards, "session", fake)
    cards._cache.clear()
    cards._refreshing.clear()
    yield fake
    cards._cache.clear()
    cards._refreshing.clear()


@pytest.fixture
def refreshes(monkeypatch):
    """Capture background price refreshes instead of spawning threads."""
    calls: list[list[str]] = []
    monkeypatch.setattr(cards, "_refresh_prices_in_background", calls.append)
    return calls


# ---- Service ----------------------------------------------------------------

def db_search(**kwargs):
    db = TestingSessionLocal()
    try:
        return card_catalog.search(db, **kwargs)
    finally:
        db.close()


def test_upsert_never_wipes_stored_prices_with_an_empty_block():
    # A TCGCSV-filled card re-fetched from pokemontcg.io arrives with empty
    # prices while upstream lags — the background refresh must not clobber it
    seed_catalog([catalog_card("me5-1", "Tropius", price=0.05)])
    db = TestingSessionLocal()
    try:
        priceless = catalog_card("me5-1", "Tropius", price=None)
        priceless["tcgplayer"] = {"prices": {}}  # how upstream serves new sets
        card_catalog.upsert_cards(db, [priceless])
        stored = card_catalog.get_card(db, "me5-1")
        assert stored.data["tcgplayer"]["prices"]["holofoil"]["market"] == 0.05
        assert stored.price_updated_at is not None  # the check still counts
    finally:
        db.close()


def test_upsert_real_prices_still_overwrite():
    seed_catalog([catalog_card("me5-2", "Lurantis ex", price=0.43)])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(
            db, [catalog_card("me5-2", "Lurantis ex", price=0.50)])
        stored = card_catalog.get_card(db, "me5-2")
        assert stored.data["tcgplayer"]["prices"]["holofoil"]["market"] == 0.50
    finally:
        db.close()


def tcgcsv_priced_card(card_id: str, name: str, price: float) -> dict:
    card = catalog_card(card_id, name, price=price)
    card["tcgplayer"]["priceSource"] = "tcgcsv"
    return card


def test_upsert_keeps_tcgcsv_sourced_prices_over_upstreams():
    # The daily job replaced upstream's figure with TCGplayer's own (wrong
    # product mapped upstream) — the request-path 6h refresh re-fetches
    # upstream and must NOT put the bad figure back
    seed_catalog([tcgcsv_priced_card("swshp-1", "Charizard", 98.49)])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(
            db, [catalog_card("swshp-1", "Charizard", price=580.92)])
        stored = card_catalog.get_card(db, "swshp-1")
        assert stored.data["tcgplayer"]["prices"]["holofoil"]["market"] == 98.49
        assert stored.data["tcgplayer"]["priceSource"] == "tcgcsv"
        assert stored.price_updated_at is not None  # refresh loop still stops
    finally:
        db.close()


def test_upsert_keeps_tcgcsv_injected_product_url():
    # the daily job stores a direct tcgplayer.com/product url alongside its
    # prices — the whole stored block (url included) must survive the
    # request-path refresh, or the CardDetail buy link would flip back and
    # forth between refreshes
    seeded = tcgcsv_priced_card("me9-1", "Mega Card ex", 250.0)
    seeded["tcgplayer"]["url"] = "https://www.tcgplayer.com/product/9"
    seed_catalog([seeded])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(
            db, [catalog_card("me9-1", "Mega Card ex", price=260.0)])
        stored = card_catalog.get_card(db, "me9-1")
        assert stored.data["tcgplayer"]["url"] == "https://www.tcgplayer.com/product/9"
        assert stored.data["tcgplayer"]["prices"]["holofoil"]["market"] == 250.0
    finally:
        db.close()


def test_authoritative_upsert_replaces_tcgcsv_sourced_prices():
    # the daily crawl re-arbitrates sources — its verdict lands verbatim
    seed_catalog([tcgcsv_priced_card("swshp-1", "Charizard", 98.49)])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(
            db, [catalog_card("swshp-1", "Charizard", price=101.0)],
            keep_stored_prices=False)
        stored = card_catalog.get_card(db, "swshp-1")
        assert stored.data["tcgplayer"]["prices"]["holofoil"]["market"] == 101.0
        assert "priceSource" not in stored.data["tcgplayer"]
    finally:
        db.close()


def test_authoritative_upsert_clears_fossilized_prices():
    # no source prices the card any more (upstream retracted a bad figure):
    # the crawl's price-less dict must clear the stored block, not keep it
    seed_catalog([catalog_card("mcd16-5", "Totodile", price=96.66)])
    db = TestingSessionLocal()
    try:
        gone = catalog_card("mcd16-5", "Totodile", price=None)
        card_catalog.upsert_cards(db, [gone], keep_stored_prices=False)
        stored = card_catalog.get_card(db, "mcd16-5")
        assert not (stored.data.get("tcgplayer") or {}).get("prices")
    finally:
        db.close()


def substituted_images_card(card_id: str, name: str) -> dict:
    # how a card looks after the daily job swapped its dead upstream image
    # URLs for the TCGplayer product scan (see snapshot_all.image_fill)
    card = catalog_card(card_id, name)
    card["images"] = {"small": "https://cdn.example/product/9_200w.jpg",
                      "large": "https://cdn.example/product/9_in_1000x1000.jpg",
                      "source": "tcgplayer"}
    return card


def test_upsert_keeps_substituted_images_over_upstreams_dead_urls():
    # upstream still serves the 404ing URLs the daily job replaced — the
    # request-path 6h price refresh must not put them back
    seed_catalog([substituted_images_card("mcd14-3", "Fennekin")])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [catalog_card("mcd14-3", "Fennekin")])
        stored = card_catalog.get_card(db, "mcd14-3")
        assert stored.data["images"]["source"] == "tcgplayer"
        assert stored.data["images"]["small"] == "https://cdn.example/product/9_200w.jpg"
    finally:
        db.close()


def test_upsert_carries_the_verified_stamp_through_a_refresh():
    # an unchanged, once-verified URL keeps its stamp, so the next crawl's
    # image check doesn't HEAD the same URL again
    stamped = catalog_card("me5-3", "Swirlix")
    stamped["images"]["verified"] = True
    seed_catalog([stamped])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [catalog_card("me5-3", "Swirlix")])
        stored = card_catalog.get_card(db, "me5-3")
        assert stored.data["images"]["verified"] is True
    finally:
        db.close()


def test_upsert_drops_the_stamp_when_upstream_moves_the_image():
    # a NEW upstream URL is unproven — it must arrive unstamped so the next
    # crawl checks it
    stamped = catalog_card("me5-4", "Bunnelby")
    stamped["images"]["verified"] = True
    seed_catalog([stamped])
    db = TestingSessionLocal()
    try:
        moved = catalog_card("me5-4", "Bunnelby")
        moved["images"] = {"small": "https://img.example/me5-4/NEW",
                           "large": "https://img.example/me5-4/NEW-l"}
        card_catalog.upsert_cards(db, [moved])
        stored = card_catalog.get_card(db, "me5-4")
        assert stored.data["images"]["small"] == "https://img.example/me5-4/NEW"
        assert "verified" not in stored.data["images"]
    finally:
        db.close()


def test_authoritative_upsert_replaces_substituted_images():
    # the daily crawl re-arbitrates images too — its verdict lands verbatim
    # (image_fill has already swapped the block back in if still needed)
    seed_catalog([substituted_images_card("mcd14-3", "Fennekin")])
    db = TestingSessionLocal()
    try:
        card_catalog.upsert_cards(db, [catalog_card("mcd14-3", "Fennekin")],
                                  keep_stored_prices=False)
        stored = card_catalog.get_card(db, "mcd14-3")
        assert stored.data["images"]["small"] == "https://img.example/mcd14-3/s"
        assert "source" not in stored.data["images"]
    finally:
        db.close()


def test_name_search_is_case_insensitive_substring():
    seed_catalog([catalog_card("b1-1", "Pikachu VMAX"),
                  catalog_card("b1-2", "Raichu")])
    envelope, _ = db_search(name="pIkAcHu")
    assert [c["name"] for c in envelope["data"]] == ["Pikachu VMAX"]
    assert envelope["totalCount"] == 1


def test_like_wildcards_are_literal():
    seed_catalog([catalog_card("b1-1", "Zygarde 100% Forme"),
                  catalog_card("b1-2", "Pikachu")])
    envelope, _ = db_search(name="100%")
    assert [c["name"] for c in envelope["data"]] == ["Zygarde 100% Forme"]


def test_exact_filters_number_set_rarity_type():
    seed_catalog([
        catalog_card("b1-4", "Charizard", number="4", rarity="Rare Holo",
                     types=["Fire", "Flying"]),
        catalog_card("b1-58", "Pikachu", number="58", rarity="Common",
                     types=["Lightning"]),
        catalog_card("b2-4", "Chansey", number="4", rarity="Rare Holo",
                     types=["Colorless"]),
    ])
    envelope, _ = db_search(number="4", set_id="b1")
    assert [c["id"] for c in envelope["data"]] == ["b1-4"]
    envelope, _ = db_search(rarity="Rare Holo")
    assert envelope["totalCount"] == 2
    envelope, _ = db_search(type_="Fire")
    assert [c["id"] for c in envelope["data"]] == ["b1-4"]
    envelope, _ = db_search(type_="Fir")  # delimiter-fenced: no prefix matches
    assert envelope["totalCount"] == 0


def test_multi_value_facets_or_within_and_across():
    seed_catalog([
        catalog_card("b1-4", "Charizard", number="4", rarity="Rare Holo",
                     types=["Fire", "Flying"]),
        catalog_card("b1-58", "Pikachu", number="58", rarity="Common",
                     types=["Lightning"]),
        catalog_card("b2-4", "Chansey", number="4", rarity="Rare Holo",
                     types=["Colorless"]),
        catalog_card("b3-9", "Blastoise", number="9", rarity="Rare Holo",
                     types=["Water"]),
    ])
    # a list ORs within the set facet (any of these sets)
    envelope, _ = db_search(set_id=["b1", "b2"])
    assert {c["id"] for c in envelope["data"]} == {"b1-4", "b1-58", "b2-4"}
    # rarity list ORs too
    envelope, _ = db_search(rarity=["Common", "Rare Holo"])
    assert envelope["totalCount"] == 4
    # type list ORs (delimiter-fenced membership)
    envelope, _ = db_search(type_=["Fire", "Water"])
    assert {c["id"] for c in envelope["data"]} == {"b1-4", "b3-9"}
    # different facets still AND together
    envelope, _ = db_search(set_id=["b1", "b2"], rarity=["Rare Holo"])
    assert {c["id"] for c in envelope["data"]} == {"b1-4", "b2-4"}
    # a single string still works (backward-compatible callers)
    envelope, _ = db_search(set_id="b3")
    assert [c["id"] for c in envelope["data"]] == ["b3-9"]


def test_pagination_envelope_and_natural_number_order():
    seed_catalog([catalog_card(f"b1-{i}", "Pikachu", number=str(i))
                  for i in range(1, 61)])
    page1, _ = db_search(name="pikachu", page=1)
    assert (page1["page"], page1["pageSize"], page1["totalCount"]) == (1, 50, 60)
    # natural order: 1, 2, ... 10 — not the lexicographic 1, 10, 11, ...
    assert [c["number"] for c in page1["data"][:3]] == ["1", "2", "3"]
    page2, _ = db_search(name="pikachu", page=2)
    assert len(page2["data"]) == 10
    assert page2["data"][0]["number"] == "51"


def test_newest_sets_sort_first():
    seed_catalog([
        catalog_card("old-1", "Pikachu", release="2001/01/01"),
        catalog_card("new-1", "Pikachu", release="2026/05/30"),
        catalog_card("mid-1", "Pikachu", release="2024/06/15"),
    ])
    envelope, _ = db_search(name="pikachu")
    assert [c["id"] for c in envelope["data"]] == ["new-1", "mid-1", "old-1"]


def test_search_reports_stale_page_ids():
    seed_catalog([catalog_card("b1-1", "Pikachu"), catalog_card("b1-2", "Pikachu")])
    age_price("b1-2")
    _, stale = db_search(name="pikachu")
    assert stale == ["b1-2"]


# ---- Router: catalog-served lists -------------------------------------------

def test_synced_catalog_answers_search_without_upstream(client, cards_upstream):
    seed_catalog([catalog_card("b1-1", "Pikachu"), catalog_card("b1-2", "Pikachu Ex")])
    body = client.get("/search", params={"q": "pikachu"}).json()
    assert body["totalCount"] == 2
    assert body["pageSize"] == 50
    assert cards_upstream.card_calls() == []  # never left the DB


def test_unsynced_catalog_still_proxies_upstream(client, cards_upstream):
    seed_catalog([catalog_card("b1-1", "Pikachu")], synced=False)
    cards_upstream.card_lists['name:"pikachu"'] = [catalog_card("b1-1", "Pikachu")]
    body = client.get("/search", params={"q": "pikachu"}).json()
    assert body["totalCount"] == 1
    assert len(cards_upstream.card_calls()) == 1  # partial catalog not trusted


def test_word_drop_fallback_runs_against_the_catalog(client, cards_upstream):
    seed_catalog([catalog_card("b1-1", "Pikachu")])
    body = client.get("/search", params={"q": "sleepy pikachu"}).json()
    assert body["totalCount"] == 1
    assert cards_upstream.card_calls() == []


def test_set_name_recognition_scopes_catalog_search(client, cards_upstream):
    cards_upstream.sets = [{"id": "swsh11", "name": "Lost Origin", "total": 217}]
    seed_catalog([
        catalog_card("swsh11-25", "Pikachu", set_id="swsh11", set_name="Lost Origin"),
        catalog_card("b1-58", "Pikachu"),
    ])
    body = client.get("/search", params={"q": "pikachu lost origin"}).json()
    assert [c["id"] for c in body["data"]] == ["swsh11-25"]
    assert cards_upstream.card_calls() == []


def test_catalog_miss_falls_back_upstream_then_serves_locally(client, cards_upstream):
    seed_catalog([catalog_card("b1-1", "Pikachu")])
    cards_upstream.card_lists['name:"eevee"'] = [catalog_card("b9-1", "Eevee")]

    first = client.get("/search", params={"q": "eevee"}).json()
    assert first["totalCount"] == 1
    assert len(cards_upstream.card_calls()) == 1  # proxied — catalog had nothing

    second = client.get("/search", params={"q": "eevee"}).json()
    assert second["totalCount"] == 1
    assert len(cards_upstream.card_calls()) == 1  # fallback got upserted


def test_filtered_cards_served_from_catalog(client, cards_upstream):
    seed_catalog([
        catalog_card("b1-4", "Charizard", rarity="Rare Holo", types=["Fire"]),
        catalog_card("b1-58", "Pikachu", rarity="Common", types=["Lightning"]),
    ])
    body = client.get("/cards", params={"set_id": "B1", "rarity": "Rare Holo",
                                        "type": "Fire"}).json()
    assert [c["id"] for c in body["data"]] == ["b1-4"]
    assert cards_upstream.card_calls() == []


def test_stale_list_page_triggers_one_background_refresh(client, cards_upstream, refreshes):
    seed_catalog([catalog_card("b1-1", "Pikachu"), catalog_card("b1-2", "Pikachu")])
    age_price("b1-2")
    client.get("/search", params={"q": "pikachu"})
    assert refreshes == [["b1-2"]]


# ---- Router: set pages and the completeness check ----------------------------

def test_full_set_served_from_catalog(client, cards_upstream):
    cards_upstream.sets = [{"id": "b9", "name": "Nine", "total": 2}]
    seed_catalog([catalog_card("b9-1", "Eevee", set_id="b9"),
                  catalog_card("b9-2", "Flareon", set_id="b9")])
    body = client.get("/sets/b9/cards").json()
    assert body["totalCount"] == 2
    assert cards_upstream.card_calls() == []


def test_half_crawled_set_proxies_until_complete(client, cards_upstream):
    cards_upstream.sets = [{"id": "b9", "name": "Nine", "total": 3}]
    full_set = [catalog_card(f"b9-{i}", f"Card {i}", set_id="b9") for i in (1, 2, 3)]
    seed_catalog(full_set[:2])  # catalog is short — a new set mid-crawl
    cards_upstream.card_lists["set.id:b9"] = full_set

    first = client.get("/sets/b9/cards").json()
    assert first["totalCount"] == 3  # proxied: no confidently-short pages
    assert len(cards_upstream.card_calls()) == 1

    second = client.get("/sets/b9/cards").json()  # upsert completed the set
    assert second["totalCount"] == 3
    assert len(cards_upstream.card_calls()) == 1


# ---- Stamp/mark variety cards (catalog-only, synthetic ids) ------------------

def test_variety_card_served_without_a_stale_refresh(client, cards_upstream, refreshes):
    # A variety card lives only in the catalog; even with a stale price there's
    # nothing upstream to refresh, so it's served plainly — no `refreshing` flag
    # and no background fetch queued.
    seed_catalog([catalog_card("swshp-SWSH006~v208260",
                               "Rillaboom (Prerelease) [Staff]",
                               number="6", set_id="swshp")])
    age_price("swshp-SWSH006~v208260")
    card = client.get("/cards/swshp-SWSH006~v208260").json()
    assert card["name"] == "Rillaboom (Prerelease) [Staff]"
    assert "refreshing" not in card
    assert refreshes == []


def test_unknown_variety_id_404s_without_proxying(client, cards_upstream):
    # A synthetic variety id with no catalog row can't be answered by upstream,
    # so 404 immediately instead of a pointless proxy round-trip.
    assert client.get("/cards/base1-4~v999999").status_code == 404
    assert cards_upstream.card_calls() == []
