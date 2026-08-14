"""Price-alert evaluation for the watchlist, run at the end of the daily job.

A `watchlist_items` row with a `target_price` is an alert: email the user when
the card's price crosses the target in `direction` ("below" — "tell me when it
drops below $X" — or "above" — a sell/recovery target). The daily snapshot job
has just recorded today's price for every card, so `evaluate` reads the current
price straight from the shared snapshot store (`latest_prices`) and needs no
upstream call.

Alerts are **edge-triggered with a re-arm latch** so a card sitting past its
target doesn't email the user every single day:

  * condition met and `last_alerted_at` is NULL  -> send, then stamp it
  * condition met and already stamped            -> stay quiet (still triggered)
  * condition NOT met and stamped                -> clear it (re-arm for next time)

So the user gets one email per "crossing episode" and a fresh one only after the
price recovers past the target and crosses again. Triggered cards are grouped
**one email per user** (a user watching five cards that all dip gets one mail,
not five). Delivery goes to every user who set a target — verification is not
required (setting a target is the opt-in). Best-effort: a send failure leaves
the item un-stamped so the next run retries, and never aborts the daily job.
"""
import html
import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.models import User, WatchlistItem, utcnow
from app.services import mailer
from app.services.price_history import latest_prices

load_dotenv()

log = logging.getLogger("watchlist_alerts")

# Where the "view card" links in the email point (the frontend origin) — the
# same env var the reset/verification links use, so one setting names the site.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")


@dataclass
class AlertRun:
    """What the alert pass did, for the daily job's summary block."""
    users_notified: int = 0   # distinct users emailed
    alerts_sent: int = 0      # triggered items included in an email
    rearmed: int = 0          # items whose price crossed back (latch cleared)
    failures: int = 0         # users whose email send raised
    triggered_ids: list[int] = field(default_factory=list)  # items newly alerted


def is_triggered(direction: str, price: float, target: float) -> bool:
    """Whether `price` meets a `direction`/`target` alert condition."""
    if direction == "above":
        return price >= target
    return price <= target  # "below" is the default


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _line(item: WatchlistItem, price: float) -> str:
    """One plain-text alert line, e.g.
    'Charizard is now $95.00 — dropped below your $100.00 target'."""
    verb = "risen above" if item.direction == "above" else "dropped below"
    return (f"{item.card_name or item.card_id} is now {_money(price)} "
            f"— {verb} your {_money(item.target_price)} target")


def _alert_email_text(username: str, rows: list[tuple[WatchlistItem, float]]) -> str:
    intro = ("A card on your watchlist hit its price target:"
             if len(rows) == 1
             else f"{len(rows)} cards on your watchlist hit their price targets:")
    body = [f"Hi {username},", "", intro, ""]
    for item, price in rows:
        body.append(f"  - {_line(item, price)}")
        body.append(f"    {FRONTEND_BASE_URL}/card/{item.card_id}")
    body += ["", "Manage your watchlist any time at "
             f"{FRONTEND_BASE_URL}/watchlist", "",
             "These are third-party market estimates, not offers to buy or sell.",
             "To stop an alert, remove the card from your watchlist or clear its "
             "target price."]
    return "\n".join(body)


def _alert_email_html(username: str, rows: list[tuple[WatchlistItem, float]]) -> str:
    # Same dark-palette, image-free table layout as the reset/verification emails
    # (index.css tokens inlined — clients strip <style>). Username and card names
    # are user/third-party data — escape them.
    name = html.escape(username)
    heading = ("A watchlist card hit its target" if len(rows) == 1
               else f"{len(rows)} watchlist cards hit their targets")
    card_rows = []
    for item, price in rows:
        card_name = html.escape(item.card_name or item.card_id)
        verb = "risen above" if item.direction == "above" else "dropped below"
        link = f"{FRONTEND_BASE_URL}/card/{html.escape(item.card_id)}"
        card_rows.append(f"""\
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="margin:0 0 12px;background-color:#151517;border:1px solid #303037;border-radius:14px;">
            <tr><td style="padding:16px 18px;">
              <p style="margin:0 0 4px;font-size:15px;font-weight:700;color:#f2f2ef;">
                <a href="{link}" style="color:#f2f2ef;text-decoration:none;">{card_name}</a>
              </p>
              <p style="margin:0;font-size:13px;line-height:1.5;color:#9c9ca4;">
                Now <span style="color:#56cf9e;font-weight:600;">{_money(price)}</span>
                — {verb} your {_money(item.target_price)} target.
              </p>
            </td></tr>
          </table>""")
    cards_html = "\n".join(card_rows)
    return f"""\
<div style="margin:0;padding:0;background-color:#0a0a0b;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#0a0a0b;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:460px;background-color:#1e1e21;border:1px solid #303037;border-radius:18px;">
        <tr><td style="padding:36px 36px 32px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          <p style="margin:0 0 24px;font-size:18px;font-weight:700;letter-spacing:-0.02em;color:#f2eee3;">
            <span style="color:#56cf9e;">&#9679;</span>&nbsp;Mintly
          </p>
          <h1 style="margin:0 0 10px;font-size:23px;font-weight:700;letter-spacing:-0.02em;color:#f2f2ef;">
            {heading}
          </h1>
          <p style="margin:0 0 22px;font-size:14px;line-height:1.6;color:#9c9ca4;">
            Hi {name}, a price you asked us to watch just moved.
          </p>
          {cards_html}
          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px 0 0;"><tr>
            <td style="background-color:#f2eee3;border-radius:999px;">
              <a href="{FRONTEND_BASE_URL}/watchlist"
                 style="display:inline-block;padding:12px 28px;font-family:inherit;font-size:14px;font-weight:600;color:#0a0a0b;text-decoration:none;border-radius:999px;">
                Open your watchlist
              </a>
            </td>
          </tr></table>
          <p style="margin:26px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            These are third-party market estimates, not offers to buy or sell. To
            stop an alert, remove the card from your watchlist or clear its target.
          </p>
        </td></tr>
      </table>
      <p style="margin:18px 0 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#9c9ca4;">
        Mintly - Pok&eacute;mon TCG portfolio tracker
      </p>
    </td></tr>
  </table>
</div>
"""


def _subject(rows: list[tuple[WatchlistItem, float]]) -> str:
    if len(rows) == 1:
        item = rows[0][0]
        return f"Price alert: {item.card_name or item.card_id} hit your target"
    return f"Price alert: {len(rows)} watchlist cards hit their targets"


def evaluate(db: Session) -> AlertRun:
    """Evaluate every alert against today's snapshots, re-arm the ones that
    crossed back, and email the users whose cards newly crossed. Returns an
    AlertRun for the job log."""
    run = AlertRun()
    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.target_price.isnot(None))
             .all())
    if not items:
        return run

    prices = latest_prices(db, [i.card_id for i in items])  # {card_id: (price, date)}

    # Group the newly-triggered items per user; re-arm the ones that recovered.
    to_notify: dict[int, list[tuple[WatchlistItem, float]]] = {}
    rearm_dirty = False
    for item in items:
        hit = prices.get(item.card_id)
        if hit is None:
            continue  # no price on record yet — can't evaluate
        price = hit[0]
        if is_triggered(item.direction, price, item.target_price):
            if item.last_alerted_at is None:
                to_notify.setdefault(item.user_id, []).append((item, price))
        elif item.last_alerted_at is not None:
            item.last_alerted_at = None  # crossed back — arm for the next crossing
            run.rearmed += 1
            rearm_dirty = True
    if rearm_dirty:
        db.commit()

    if not to_notify:
        return run

    now = utcnow()
    for user_id, rows in to_notify.items():
        user = db.get(User, user_id)
        if user is None or not user.email:
            continue
        try:
            mailer.send_email(
                to=user.email,
                subject=_subject(rows),
                body=_alert_email_text(user.username, rows),
                html=_alert_email_html(user.username, rows),
            )
        except Exception:  # noqa: BLE001 — one user's send must not abort the pass
            log.warning("watchlist alert email to user %d failed", user_id,
                        exc_info=True)
            run.failures += 1
            continue
        # Stamp the latch only after a successful send, so a failed send retries
        # next run instead of silently swallowing the alert.
        for item, _price in rows:
            item.last_alerted_at = now
            run.triggered_ids.append(item.id)
        run.users_notified += 1
        run.alerts_sent += len(rows)
    db.commit()
    return run
