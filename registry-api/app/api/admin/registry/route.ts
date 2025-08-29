import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';
import { checkAdminAuth } from '@/lib/auth';

export async function POST(request: NextRequest) {
  if (!checkAdminAuth(request)) {
    return NextResponse.json(
      {
        success: false,
        error: 'Unauthorized: Invalid password'
      },
      { status: 401 }
    );
  }

  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const body = await request.json();
    const mcp = {
      ...body,
      createdAt: new Date(),
      updatedAt: new Date()
    };
    
    const existing = await collection.findOne({ id: mcp.id });
    if (existing) {
      return NextResponse.json(
        {
          success: false,
          error: 'MCP with this ID already exists'
        },
        { status: 409 }
      );
    }
    
    await collection.insertOne(mcp);
    
    return NextResponse.json(
      {
        success: true,
        mcp
      },
      { status: 201 }
    );
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to create MCP',
        message: error.message
      },
      { status: 500 }
    );
  }
}