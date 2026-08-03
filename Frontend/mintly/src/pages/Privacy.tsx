export default function Privacy() {
  return (
    <div className="page legal-page">
      <h1>Privacy Policy</h1>
      <p className="legal-updated">Last updated: August 3, 2026</p>

      <h2>1. What we collect</h2>
      <p>
        When you register we store your email address, username, a hashed
        version of your password (never the password itself), and the time you
        accepted the Terms of Service. When you use the portfolio we store the
        cards you add: card id, name, quantity, purchase price, and purchase
        date, along with the names of any portfolios you create to organize
        them. To protect against abuse (such as password-guessing), our servers
        also keep a short-lived, in-memory count of recent requests per network
        address; these counts are not stored durably or linked to your account.
        If you request a password reset, we store a hashed, single-use reset
        code that expires after 30 minutes. We also record whether and when you
        have confirmed your email address, and store a hashed, single-use
        verification code the same way when a verification email is sent.
      </p>

      <h2>2. How it's used</h2>
      <p>
        This data exists solely to run the service: logging you in, showing
        your portfolio, and computing its value over time. Your email address
        is used only for signing in, for confirming your address with a
        verification link, and for sending a password-reset link when you
        request one; we don&apos;t send marketing email. We do not sell your
        data or share it with advertisers.
      </p>

      <h2>3. Cookies and local storage</h2>
      <p>
        Mintly stores a login token in your browser's local storage so you stay
        signed in for up to 7 days, along with your display and accessibility
        preferences (such as reduced motion or larger text), which stay on your
        device and are never sent to our servers. You can end every active
        session at any time from your profile page (Sign out of other devices),
        which invalidates outstanding login tokens. No third-party tracking
        cookies are used on Mintly itself. If you follow an outbound link to
        TCGplayer or eBay, that retailer or its affiliate network may set its
        own cookies after you leave Mintly, governed by their privacy policies.
      </p>

      <h2>4. Card scanning</h2>
      <p>
        The optional card scanner uses your device&apos;s camera to identify a
        card. When you scan, the captured photo is sent to Mintly&apos;s own
        server, which matches it against our database of card images to find the
        card and returns the closest matches for you to confirm. The image is
        used only to compute that match: it is not linked to your account, not
        shown to anyone, and not kept. It is discarded once the match is made.
        The matching runs entirely on Mintly&apos;s own hardware; the image is
        never sent to any third party.
      </p>

      <h2>5. Third parties</h2>
      <p>
        Card searches and price lookups are served through the Pokémon TCG API.
        For cards it cannot price, Mintly fetches TCGplayer price data from
        TCGCSV, a public daily mirror, and may also query recent sold listings
        on eBay to estimate a value. Your account details are never sent to any
        of these services, only the card name, number, or set needed to find
        results and prices. Account emails (the password-reset link and the
        email-verification link) are delivered through an email provider, which
        processes your email address solely to deliver those messages. The site
        itself is served through Cloudflare, which sits
        between your browser and our server to route traffic securely and
        protect against attacks; to do this it processes connection metadata
        such as your IP address, subject to its own privacy policy. Some
        outbound links to TCGplayer and eBay are affiliate links: following one
        tells the retailer or its affiliate network that the visit came from
        Mintly, so Mintly can earn a commission on qualifying purchases. These
        links contain only the card being looked up, never your account
        details.
      </p>

      <h2>6. Your data</h2>
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

      <h2>7. Contact</h2>
      <p>
        Questions about this policy or a request about your data? Email us at{" "}
        <a href="mailto:mintlytcg@gmail.com">mintlytcg@gmail.com</a>.
      </p>

      <h2>8. Changes</h2>
      <p>
        If this policy changes, the date above will be updated. Material changes
        will be noted on the site.
      </p>
    </div>
  );
}
