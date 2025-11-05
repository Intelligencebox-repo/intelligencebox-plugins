import { NextRequest, NextResponse } from 'next/server';
import { getDatabase } from '@/lib/mongodb';
import { checkAdminAuth } from '@/lib/auth';

export async function PUT(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
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
    const updates = {
      ...body,
      updatedAt: new Date()
    };
    const unset: Record<string, ''> = {};

    if (!Object.prototype.hasOwnProperty.call(body, 'volumeMounts')) {
      unset.volumeMounts = '';
    }

    if (Object.prototype.hasOwnProperty.call(updates, 'volumeMounts')) {
      if (updates.volumeMounts === null || updates.volumeMounts === undefined) {
        unset.volumeMounts = '';
        delete updates.volumeMounts;
      }
    }
    
    delete updates._id;
    delete updates.id;
    delete updates.createdAt;
    
    const updateDoc: Record<string, any> = {
      $set: updates
    };

    if (Object.keys(unset).length > 0) {
      updateDoc.$unset = unset;
    }

    const result = await collection.findOneAndUpdate(
      { id: params.id },
      updateDoc,
      { returnDocument: 'after' }
    );
    
    if (!result) {
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
      mcp: result
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to update MCP',
        message: error.message
      },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
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
    
    const result = await collection.deleteOne({ id: params.id });
    
    if (result.deletedCount === 0) {
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
      message: 'MCP deleted successfully'
    });
  } catch (error: any) {
    return NextResponse.json(
      {
        success: false,
        error: 'Failed to delete MCP',
        message: error.message
      },
      { status: 500 }
    );
  }
}
