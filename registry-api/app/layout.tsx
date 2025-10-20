import './globals.css'

export const metadata = {
  title: 'MCP Registry API - Intelligencebox',
  description: 'Model Context Protocol Registry API',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}