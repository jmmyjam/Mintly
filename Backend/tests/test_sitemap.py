"""/sitemap.xml — the crawler-facing URL list built from the card catalog."""

from test_catalog import catalog_card, seed_catalog

# Tests run with FRONTEND_BASE_URL unset, so the module default applies
BASE = "http://localhost:5173"


def test_sitemap_serves_static_pages_on_empty_catalog(client):
    res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    for path in ("/", "/search", "/terms", "/privacy"):
        assert f"<loc>{BASE}{path}</loc>" in res.text
    assert "/card/" not in res.text


def test_sitemap_lists_catalog_cards(client):
    seed_catalog([
        catalog_card("base1-4", "Charizard"),
        catalog_card("swsh11-25", "Pikachu"),
    ])
    res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert f"<loc>{BASE}/card/base1-4</loc>" in res.text
    assert f"<loc>{BASE}/card/swsh11-25</loc>" in res.text
    # still one <url> per entry: 4 static + 2 cards
    assert res.text.count("<url>") == 6


def test_sitemap_is_valid_xml(client):
    import xml.etree.ElementTree as ET

    seed_catalog([catalog_card("base1-4", "Charizard")])
    root = ET.fromstring(client.get("/sitemap.xml").text)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == f"{ns}urlset"
    locs = [url.find(f"{ns}loc").text for url in root.findall(f"{ns}url")]
    assert f"{BASE}/card/base1-4" in locs
