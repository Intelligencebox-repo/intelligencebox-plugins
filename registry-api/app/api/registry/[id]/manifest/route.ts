import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';
import { loadManifestFromFilesystem, mergeMcpWithManifest } from '@/lib/manifest';

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
    const fileManifest = await loadManifestFromFilesystem(params.id);
    const merged = mergeMcpWithManifest(mcp, fileManifest);

    const manifest = {
      id: merged.id,
      name: merged.name,
      description: merged.description,
      author: merged.author,
      version: merged.version,
      dockerImage: merged.dockerImage,
      dockerTag: merged.dockerTag,
      entrypoint: merged.entrypoint ?? 'node /app/dist/index.js',
      configSchema: merged.configSchema,
      requirements: merged.requirements,
      icon: merged.icon,
      category: merged.category,
      tags: merged.tags,
      documentationUrl: merged.documentationUrl,
      features: merged.features,
      dockerDefaults: merged.dockerDefaults,
      transport: merged.transport,
      port: merged.port,
      sseEndpoint: merged.sseEndpoint,
      needsFileAccess: merged.needsFileAccess,
      volumeMounts: merged.volumeMounts
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
