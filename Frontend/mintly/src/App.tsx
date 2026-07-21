import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import StructuredData from './components/StructuredData'
import Home from './pages/Home'
import Search from './pages/Search'
import Portfolio from './pages/Portfolio'
import Profile from './pages/Profile'
import CardDetail from './pages/CardDetail'
import Login from './pages/Login'
import Terms from './pages/Terms'
import Privacy from './pages/Privacy'
import './App.css'

// Site-level structured data, on every route. Built from the page's own origin
// so it stays correct wherever the app is hosted (there's no configured public
// URL). Descriptions mirror the Home hero/feature copy — Google requires
// markup to describe visible content.
const origin = window.location.origin
const SITE_GRAPH = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'Organization',
      '@id': `${origin}/#organization`,
      name: 'Mintly',
      url: `${origin}/`,
      logo: { '@type': 'ImageObject', url: `${origin}/favicon.svg` },
    },
    {
      '@type': 'WebSite',
      '@id': `${origin}/#website`,
      name: 'Mintly',
      url: `${origin}/`,
      publisher: { '@id': `${origin}/#organization` },
      potentialAction: {
        '@type': 'SearchAction',
        target: {
          '@type': 'EntryPoint',
          urlTemplate: `${origin}/search?q={search_term_string}`,
        },
        'query-input': 'required name=search_term_string',
      },
    },
    {
      '@type': 'WebApplication',
      '@id': `${origin}/#app`,
      name: 'Mintly',
      url: `${origin}/`,
      applicationCategory: 'FinanceApplication',
      operatingSystem: 'Any',
      description:
        'Free Pokémon TCG portfolio tracker — search the card catalog, see ' +
        "live TCGPlayer market prices and price history, and track your collection's " +
        'value over time.',
      offers: { '@type': 'Offer', price: 0, priceCurrency: 'USD' },
    },
  ],
}

export default function App() {
  return (
    <BrowserRouter>
      <StructuredData data={SITE_GRAPH} />
      <Navbar />
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/card/:cardId" element={<CardDetail />} />
          <Route path="/login" element={<Login />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/privacy" element={<Privacy />} />
        </Routes>
      </main>
      <Footer />
    </BrowserRouter>
  )
}
