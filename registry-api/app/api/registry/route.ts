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
    
    const mcpsWithEntrypoint = mcps.map(mcp => ({
      ...mcp,
      entrypoint: mcp.entrypoint
    }));
    
    return NextResponse.json({
      success: true,
      mcps: mcpsWithEntrypoint,
      count: mcpsWithEntrypoint.length
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