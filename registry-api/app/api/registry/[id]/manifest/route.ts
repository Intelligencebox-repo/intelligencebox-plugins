import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const mcp = await collection.findOne({
      id: params.id,
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    });
    
    if (!mcp) {
      return NextResponse.json(
        {
          success: false,
          error: 'MCP not found'
        },
        { status: 404 }
      );
    }
    
    const manifest = {
      id: mcp.id,
      name: mcp.name,
      description: mcp.description,
      author: mcp.author,
      version: mcp.version,
      dockerImage: mcp.dockerImage,
      dockerTag: mcp.dockerTag || 'latest',
      entrypoint: mcp.entrypoint || 'node /app/dist/index.js',
      configSchema: mcp.configSchema,
      requirements: mcp.requirements,
      icon: mcp.icon,
      category: mcp.category,
      tags: mcp.tags,
      documentationUrl: mcp.documentationUrl,
      needsFileAccess: mcp.needsFileAccess || false,
      volumeMounts: mcp.volumeMounts || {},
      transport: mcp.transport || 'stdio',
      port: mcp.port,
      sseEndpoint: mcp.sseEndpoint
    };
    
    return NextResponse.json({
      success: true,
      manifest
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to fetch manifest',
        message: error.message
      },
      { status: 500 }
    );
  }
}