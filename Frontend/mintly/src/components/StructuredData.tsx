// JSON-LD structured data block for search engines. Google reads these from
// the body as well as the head, so pages can render one wherever convenient
// and it mounts/unmounts with the page.
export default function StructuredData({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      // "<" is escaped so externally sourced strings (card names, artists)
      // can never close the script tag early
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, '\\u003c') }}
    />
  )
}
