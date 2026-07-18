export default function Privacy() {
  return (
    <div className="page legal-page">
      <h1>Privacy Policy</h1>
      <p className="legal-updated">Last updated: July 17, 2026</p>

      <h2>1. What we collect</h2>
      <p>
        When you register we store your email address, username, a hashed
        version of your password (never the password itself), and the time
        you accepted the Terms of Service. When you use the portfolio we
        store the cards you add: card id, name, quantity, purchase price, and
        purchase date. To protect against abuse (such as password-guessing),
        our servers also keep a short-lived, in-memory count of recent
        requests per network address; these counts are not stored durably or
        linked to your account.
      </p>

      <h2>2. How it's used</h2>
      <p>
        This data exists solely to run the service — logging you in, showing
        your portfolio, and computing its value over time. We do not sell your
        data or share it with advertisers.
      </p>

      <h2>3. Cookies and local storage</h2>
      <p>
        Mintly stores a login token in your browser's local storage so you
        stay signed in for up to 7 days. No third-party tracking cookies are
        used.
      </p>

      <h2>4. Third parties</h2>
      <p>
        Card searches and price lookups are served through the Pokémon TCG
        API. For cards it cannot price, Mintly also queries recent sold
        listings on eBay to estimate a value. Your account details are never
        sent to either service — only the card name, number, or set needed to
        find results and prices.
      </p>

      <h2>5. Your data</h2>
      <p>
        You can remove cards from your portfolio at any time, which deletes
        those records. To build price history, Mintly records a daily market
        price for cards that are searched or viewed; these snapshots are
        aggregate per-card figures, are not tied to your account, and contain
        nothing personal.
      </p>

      <h2>6. Changes</h2>
      <p>
        If this policy changes, the date above will be updated. Material
        changes will be noted on the site.
      </p>
    </div>
  )
}
