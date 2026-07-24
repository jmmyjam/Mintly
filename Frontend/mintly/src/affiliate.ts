import type { Card } from './api'

// Impact tracking-link base for the TCGplayer affiliate program (looks like
// https://tcgplayer.pxf.io/c/<pub>/<link>/<prog>), set at build time. Unset =
// plain untracked links — the pre-approval behavior.
const IMPACT_LINK: string = import.meta.env.VITE_TCGPLAYER_IMPACT_LINK ?? ''

// Impact deeplinks only attribute (and may reject) destinations on the
// advertiser's own domain — upstream's prices.pokemontcg.io redirect must
// stay a plain link.
const TCGPLAYER_DOMAIN = /^https:\/\/(www\.)?tcgplayer\.com\//

// Fallback when a card has no stored TCGplayer url: a search for its name +
// number lands on (or near) the product page.
export function tcgplayerSearchUrl(card: Pick<Card, 'name' | 'number'>): string {
  const q = [card.name, card.number].filter(Boolean).join(' ')
  return `https://www.tcgplayer.com/search/pokemon/product?${new URLSearchParams({ productLineName: 'pokemon', q })}`
}

// The CardDetail buy link: the card's stored TCGplayer url (a direct product
// page for TCGCSV-priced cards; upstream's prices.pokemontcg.io redirect
// otherwise), else the search fallback — wrapped in the Impact tracking link
// only for tcgplayer.com destinations. `affiliate` gates the rel="sponsored"
// and the FTC disclosure line next to the button.
export function tcgplayerBuyLink(card: Card): { href: string; affiliate: boolean } {
  const dest = card.tcgplayer?.url ?? tcgplayerSearchUrl(card)
  if (IMPACT_LINK && TCGPLAYER_DOMAIN.test(dest)) {
    return { href: `${IMPACT_LINK}?u=${encodeURIComponent(dest)}`, affiliate: true }
  }
  return { href: dest, affiliate: false }
}
