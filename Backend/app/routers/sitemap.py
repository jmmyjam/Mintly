import os
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CatalogCard
from app.services.rate_limit import rate_limit

load_dotenv()

# The public origin the URLs are built on — the same env var the password-reset
# links use, so one setting names the site everywhere.
_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")

# The public frontend routes: pages that render without auth. Authed pages
# (portfolio, profile) are deliberately absent — crawlers only see their login
# prompt, and markup must describe visible content.
_STATIC_PATHS = ["/", "/search", "/terms", "/privacy"]

router = APIRouter(dependencies=[Depends(rate_limit("api", times=120, seconds=60))])


@router.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    # Card-detail pages are the long-tail search surface; the catalog holds
    # every crawled card, so its ids are the URL list. A catalog hiccup still
    # serves the static pages — a crawler should never see a 500 here.
    paths = list(_STATIC_PATHS)
    try:
        rows = db.query(CatalogCard.card_id).order_by(CatalogCard.card_id).all()
        paths.extend(f"/card/{card_id}" for (card_id,) in rows)
    except Exception:
        pass
    body = "\n".join(f"  <url><loc>{escape(_BASE_URL + p)}</loc></url>" for p in paths)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")
