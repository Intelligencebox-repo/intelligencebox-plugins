import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;
    const q = searchParams.get('q');
    
    if (!q || typeof q !== 'string') {
      return NextResponse.json(
        {
          success: false,
          error: 'Query parameter "q" is required'
        },
        { status: 400 }
      );
    }
    
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const mcps = await collection.find({
      enabled: true,
      visibility: { $in: ['public', 'beta'] },
      $or: [
        { name: { $regex: q, $options: 'i' } },
        { description: { $regex: q, $options: 'i' } },
        { tags: { $regex: q, $options: 'i' } },
        { author: { $regex: q, $options: 'i' } }
      ]
    }).limit(20).toArray();
    
    return NextResponse.json({
      success: true,
      query: q,
      results: mcps,
      count: mcps.length
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Search failed',
        message: error.message
      },
      { status: 500 }
    );
  }
}