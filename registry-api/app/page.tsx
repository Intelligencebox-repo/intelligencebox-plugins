export default function Home() {
  return (
    <main style={{ padding: '2rem', fontFamily: 'monospace' }}>
      <h1>MCP Registry API</h1>
      <p>Version: 1.0.0</p>
      
      <h2>Available Endpoints:</h2>
      <ul style={{ lineHeight: '1.8' }}>
        <li>GET /api/registry - List all MCPs</li>
        <li>GET /api/registry/:id - Get MCP details</li>
        <li>GET /api/registry/:id/manifest - Get MCP manifest</li>
        <li>GET /api/search?q=query - Search MCPs</li>
        <li>GET /api/categories - Get available categories</li>
        <li>GET /api/health - Health check</li>
      </ul>
      
      <h2>Admin Endpoints (requires authentication):</h2>
      <ul style={{ lineHeight: '1.8' }}>
        <li>POST /api/admin/registry - Create new MCP</li>
        <li>PUT /api/admin/registry/:id - Update MCP</li>
        <li>DELETE /api/admin/registry/:id - Delete MCP</li>
      </ul>
    </main>
  );
}