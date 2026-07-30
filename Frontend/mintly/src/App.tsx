import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import StructuredData from './components/StructuredData'
import PageMessage from './components/PageMessage'
import Home from './pages/Home'
import Search from './pages/Search'
import Portfolio from './pages/Portfolio'
import Holding from './pages/Holding'
// Lazy-loaded: the scanner pulls in the Tesseract OCR runtime, so it's split
// into its own chunk that only downloads when someone opens /scan.
const Scan = lazy(() => import('./pages/Scan'))
import Profile from './pages/Profile'
import Admin from './pages/Admin'
import CardDetail from './pages/CardDetail'
import Login from './pages/Login'
import ResetPassword from './pages/ResetPassword'
import Terms from './pages/Terms'
import Privacy from './pages/Privacy'
import Accessibility from './pages/Accessibility'
import NotFound from './pages/NotFound'
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
        'Free Pokémon TCG portfolio tracker - search the card catalog, see ' +
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
      {/* First focusable element on every page: lets keyboard users skip the
          nav straight to the page content (WCAG 2.4.1 Bypass Blocks). */}
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <Navbar />
      <main className="main" id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route
            path="/scan"
            element={
              <Suspense fallback={<PageMessage>Loading…</PageMessage>}>
                <Scan />
              </Suspense>
            }
          />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/portfolio/:cardId" element={<Holding />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/card/:cardId" element={<CardDetail />} />
          <Route path="/login" element={<Login />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/accessibility" element={<Accessibility />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Footer />
    </BrowserRouter>
  )
}
