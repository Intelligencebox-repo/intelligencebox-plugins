import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  return NextResponse.json({
    name: 'MCP Registry API',
    version: '1.0.0',
    endpoints: [
      'GET /api/registry - List all MCPs',
      'GET /api/registry/:id - Get MCP details',
      'GET /api/registry/:id/manifest - Get MCP manifest',
      'GET /api/search?q=query - Search MCPs',
      'GET /api/categories - Get available categories',
      'GET /api/health - Health check'
    ]
  });
}