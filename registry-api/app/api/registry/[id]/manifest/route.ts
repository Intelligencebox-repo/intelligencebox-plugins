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

      // NEW: Build dockerDefaults structure (supports both old and new formats)
      dockerDefaults: mcp.dockerDefaults || {
        containerPort: mcp.port,
        sseEndpoint: mcp.sseEndpoint,
        protocol: 'tcp' as const,
        needsPortMapping: mcp.transport === 'sse',
        defaultHostPort: mcp.port,
        needsFileAccess: mcp.needsFileAccess || false,
        // Try to read volumeMounts from dockerDefaults first, then fall back to root level
        volumeMounts: mcp.dockerDefaults?.volumeMounts || mcp.volumeMounts || {},
        resources: mcp.dockerDefaults?.resources || {
          memory: '512m',
          cpus: '0.5'
        }
      },

      // Keep legacy fields for backward compatibility
      transport: mcp.transport || 'stdio',
      port: mcp.port,
      sseEndpoint: mcp.sseEndpoint,
      needsFileAccess: mcp.needsFileAccess || false,
      volumeMounts: mcp.volumeMounts || {}
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