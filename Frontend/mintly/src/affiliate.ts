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

// eBay Partner Network campaign id — the same value the backend's
// EBAY_EPN_CAMPAIGN_ID env var holds (it's a public click-attribution id, not
// a secret). Unset = plain untracked eBay links.
const EPN_CAMPAIGN_ID: string = import.meta.env.VITE_EBAY_EPN_CAMPAIGN_ID ?? ''

// The standard US ebay.com attribution set — mirrors _EPN_PARAMS in the
// backend's app/services/ebay_prices.py; keep the two in sync.
const EPN_PARAMS = {
  mkcid: '1',
  mkrid: '711-53200-19255-0',
  siteid: '0',
  mkevt: '1',
  toolid: '10001',
}

// Active-listings eBay search for one card. Sellers title cards with the full
// collector number ("Charizard 4/102"), so a plain-digit number gets the set's
// printedTotal appended — that pins the exact card; lettered numbers (TG12,
// SWSH066) are distinctive enough bare.
export function ebaySearchUrl(card: Pick<Card, 'name' | 'number' | 'set'>): string {
  let number = card.number ?? ''
  if (/^\d+$/.test(number) && card.set?.printedTotal) {
    number = `${number}/${card.set.printedTotal}`
  } else if (!number && card.set?.name) {
    number = card.set.name // numberless card: the set name disambiguates instead
  }
  const q = [card.name, number].filter(Boolean).join(' ')
  const params = new URLSearchParams({ _nkw: q })
  if (EPN_CAMPAIGN_ID) {
    for (const [k, v] of Object.entries(EPN_PARAMS)) params.set(k, v)
    params.set('campid', EPN_CAMPAIGN_ID)
  }
  return `https://www.ebay.com/sch/i.html?${params}`
}

// The CardDetail eBay button: `affiliate` gates rel="sponsored" and the FTC
// disclosure line, same contract as tcgplayerBuyLink.
export function ebayBuyLink(card: Pick<Card, 'name' | 'number' | 'set'>): { href: string; affiliate: boolean } {
  return { href: ebaySearchUrl(card), affiliate: Boolean(EPN_CAMPAIGN_ID) }
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
