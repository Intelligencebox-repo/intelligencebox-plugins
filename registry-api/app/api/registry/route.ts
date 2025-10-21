import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';

export async function GET(request: NextRequest) {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const searchParams = request.nextUrl.searchParams;
    const category = searchParams.get('category');
    const search = searchParams.get('search');
    const featured = searchParams.get('featured');
    
    const filter: any = {
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    };
    
    if (category) {
      filter.category = category;
    }
    
    if (featured === 'true') {
      filter.featured = true;
    }
    
    if (search) {
      filter.$or = [
        { name: { $regex: search, $options: 'i' } },
        { description: { $regex: search, $options: 'i' } },
        { tags: { $regex: search, $options: 'i' } }
      ];
    }
    
    const mcps = await collection.find(filter).toArray();
    
    const mcpsWithAllFields = mcps.map(mcp => ({
      ...mcp,
      entrypoint: mcp.entrypoint,

      // NEW: Build dockerDefaults structure if not present (supports both old and new formats)
      dockerDefaults: mcp.dockerDefaults || {
        containerPort: mcp.port,
        sseEndpoint: mcp.sseEndpoint,
        protocol: 'tcp' as const,
        needsPortMapping: mcp.transport === 'sse',
        defaultHostPort: mcp.port,
        needsFileAccess: mcp.needsFileAccess || false,
        volumeMounts: mcp.volumeMounts || {},
        resources: mcp.dockerDefaults?.resources || {
          memory: '512m',
          cpus: '0.5'
        }
      },

      // Keep legacy fields for backward compatibility
      needsFileAccess: mcp.needsFileAccess || false,
      volumeMounts: mcp.volumeMounts || {}
    }));
    
    return NextResponse.json({
      success: true,
      mcps: mcpsWithAllFields,
      count: mcpsWithAllFields.length
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to fetch MCPs',
        message: error.message
      },
      { status: 500 }
    );
  }
}