"""Who counts as a site admin.

Admin access is configuration, not schema: ADMIN_EMAILS is a comma-separated
list of account email addresses (case-insensitive). Unset — the default — means
no admins at all: the /admin endpoints 404 for everyone and the frontend never
shows a link, so the feature is invisible until the env var names an account.
Keying on the account email needs no migration; list only addresses that
already belong to your own registered account (registration doesn't verify
email ownership, so a listed-but-unregistered address could be claimed by
anyone).
"""

import os

from dotenv import load_dotenv

from app.models import User

load_dotenv()

# Read at import time like the app's other env config (mailer, ebay_prices);
# tests monkeypatch this set directly.
_ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
}


def is_admin(user: User) -> bool:
    """True when the user's account email is on the configured admin list."""
    return bool(user.email) and user.email.strip().lower() in _ADMIN_EMAILS
