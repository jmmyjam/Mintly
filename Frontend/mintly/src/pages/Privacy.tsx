export default function Privacy() {
  return (
    <div className="page legal-page">
      <h1>Privacy Policy</h1>
      <p className="legal-updated">Last updated: July 22, 2026</p>

      <h2>1. What we collect</h2>
      <p>
        When you register we store your email address, username, a hashed
        version of your password (never the password itself), and the time you
        accepted the Terms of Service. When you use the portfolio we store the
        cards you add: card id, name, quantity, purchase price, and purchase
        date. To protect against abuse (such as password-guessing), our servers
        also keep a short-lived, in-memory count of recent requests per network
        address; these counts are not stored durably or linked to your account.
        If you request a password reset, we store a hashed, single-use reset
        code that expires after 30 minutes.
      </p>

      <h2>2. How it's used</h2>
      <p>
        This data exists solely to run the service — logging you in, showing
        your portfolio, and computing its value over time. Your email address
        is used only for signing in and for sending a password-reset link when
        you request one; we don&apos;t send marketing email. We do not sell
        your data or share it with advertisers.
      </p>

      <h2>3. Cookies and local storage</h2>
      <p>
        Mintly stores a login token in your browser's local storage so you stay
        signed in for up to 7 days, along with your display and accessibility
        preferences (such as reduced motion or larger text), which stay on your
        device and are never sent to our servers. No third-party tracking
        cookies are used.
      </p>

      <h2>4. Third parties</h2>
      <p>
        Card searches and price lookups are served through the Pokémon TCG API.
        For cards it cannot price, Mintly fetches TCGplayer price data from
        TCGCSV, a public daily mirror, and may also query recent sold listings
        on eBay to estimate a value. Your account details are never sent to any
        of these services — only the card name, number, or set needed to find
        results and prices. Password-reset emails are delivered through an
        email provider, which processes your email address solely to deliver
        that message. The site itself is served through Cloudflare, which sits
        between your browser and our server to route traffic securely and
        protect against attacks; to do this it processes connection metadata
        such as your IP address, subject to its own privacy policy.
      </p>

      <h2>5. Your data</h2>
      <p>
        You can view and update your email, username, and password from your
        profile page, and remove cards from your portfolio at any time, which
        deletes those records. You can also permanently delete your entire
        account from your profile page: this erases your email, username,
        password hash, and all of your portfolio records, and cannot be undone.
        To build price history, Mintly records a daily market price for cards
        that are searched or viewed; these snapshots are aggregate per-card
        figures, are not tied to your account, and contain nothing personal, so
        they remain after an account is deleted.
      </p>

      <h2>6. Contact</h2>
      <p>
        Questions about this policy or a request about your data? Email us at{" "}
        <a href="mailto:mintlytcg@gmail.com">mintlytcg@gmail.com</a>.
      </p>

      <h2>7. Changes</h2>
      <p>
        If this policy changes, the date above will be updated. Material changes
        will be noted on the site.
      </p>
    </div>
  );
}
