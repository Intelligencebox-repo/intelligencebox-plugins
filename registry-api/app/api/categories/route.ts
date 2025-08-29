import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';

export async function GET(request: NextRequest) {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const categories = await collection.distinct('category', {
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    });
    
    return NextResponse.json({
      success: true,
      categories
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to fetch categories',
        message: error.message
      },
      { status: 500 }
    );
  }
}