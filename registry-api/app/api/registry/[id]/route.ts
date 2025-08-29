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
    
    return NextResponse.json({
      success: true,
      mcp
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to fetch MCP',
        message: error.message
      },
      { status: 500 }
    );
  }
}