import AccessibilitySettings from '../components/AccessibilitySettings'

// Public accessibility statement (route /accessibility, linked from the Footer).
// It also hosts the display-preference controls so they're reachable without an
// account, not only from the signed-in Profile page.
export default function Accessibility() {
  return (
    <div className="page legal-page">
      <h1>Accessibility</h1>
      <p className="legal-updated">Last updated: July 29, 2026</p>

      <p>
        Mintly is built to be usable by everyone, including people who rely on
        assistive technology. We aim to meet the Web Content Accessibility
        Guidelines (WCAG) 2.1 at Level AA, the standard commonly referenced for
        the Americans with Disabilities Act (ADA) and similar laws.
      </p>

      <h2>Display preferences</h2>
      <p>
        You can adjust how Mintly looks right here, without an account. These
        settings are saved in your browser on this device and are never sent to
        our servers.
      </p>

      <AccessibilitySettings />

      <p style={{ marginTop: '16px' }}>
        You can also change these preferences from the Accessibility section of
        your profile once you are signed in. Mintly automatically respects your
        operating system's "reduce motion" setting as well.
      </p>

      <h2>What we have done</h2>
      <ul>
        <li>
          Every page uses semantic landmarks (navigation, main content, and
          footer) plus a "Skip to main content" link, so keyboard users can jump
          past the menu.
        </li>
        <li>
          Interactive elements are reachable and operable with a keyboard, and
          the element you are on shows a visible focus outline.
        </li>
        <li>
          Card images carry text alternatives, and purely decorative graphics
          are hidden from screen readers.
        </li>
        <li>
          Buttons, switches, and menus expose their name and state to assistive
          technology (the toggles above, for example, announce on or off).
        </li>
        <li>
          Text reflows and stays readable when zoomed, and the layout adapts
          from small phones to large screens without sideways scrolling.
        </li>
        <li>
          Color is never the only way information is conveyed. A price change,
          for instance, shows an arrow and a number, not just red or green.
        </li>
        <li>
          Animation is minimized when you turn on Reduce motion here or set that
          preference in your operating system.
        </li>
      </ul>

      <h2>Known limitations</h2>
      <p>We would rather be honest about where we still fall short:</p>
      <ul>
        <li>
          Card artwork comes from a third-party catalog. When an image is
          missing we show the card's name in its place, but we cannot change the
          artwork itself.
        </li>
        <li>
          The price history charts are visual. The figures they show (current
          price, daily change, and a full price table for cards with several
          variants) are also available as text on the same page, but the charts
          themselves are not yet fully described for screen readers.
        </li>
        <li>
          The card scanner relies on a device camera and is inherently visual.
          You can always search for a card by name instead.
        </li>
      </ul>
      <p>
        We keep testing with keyboards and screen readers and fix issues as we
        find them.
      </p>

      <h2>Give us feedback</h2>
      <p>
        If you hit a barrier using Mintly, or you need something in a different
        format, please tell us. Email{" "}
        <a href="mailto:mintlytcg@gmail.com">mintlytcg@gmail.com</a> and describe
        the problem, the page you were on, and the device or assistive
        technology you were using. We will do our best to respond and to put it
        right.
      </p>
    </div>
  )
}
