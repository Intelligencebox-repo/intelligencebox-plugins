import express from 'express';
import cors from 'cors';
import { MongoClient } from 'mongodb';

const app = express();
app.use(cors());
app.use(express.json());

// MongoDB connection
const MONGODB_URL = process.env.MONGODB_URL;

let client: MongoClient;

async function getDatabase() {
  if (!client) {
    if (!MONGODB_URL) {
      throw new Error('MONGODB_URL environment variable is not set');
    }
    client = new MongoClient(MONGODB_URL);
    await client.connect();
  }
  return client.db('mcp_registry');
}

// GET /api/registry - List all public MCPs
app.get('/api/registry', async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const { category, search, featured } = req.query;
    
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
    
    // Ensure each MCP has entrypoint field
    const mcpsWithEntrypoint = mcps.map(mcp => ({
      ...mcp,
      entrypoint: mcp.entrypoint // Include entrypoint from database (can be string or array)
    }));
    
    res.json({
      success: true,
      mcps: mcpsWithEntrypoint,
      count: mcpsWithEntrypoint.length
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to fetch MCPs',
      message: error.message
    });
  }
});

// GET /api/registry/:id - Get specific MCP details
app.get('/api/registry/:id', async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const mcp = await collection.findOne({
      id: req.params.id,
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    });
    
    if (!mcp) {
      return res.status(404).json({
        success: false,
        error: 'MCP not found'
      });
    }
    
    res.json({
      success: true,
      mcp
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to fetch MCP',
      message: error.message
    });
  }
});

// GET /api/registry/:id/manifest - Get MCP manifest for installation
app.get('/api/registry/:id/manifest', async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const mcp = await collection.findOne({
      id: req.params.id,
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    });
    
    if (!mcp) {
      return res.status(404).json({
        success: false,
        error: 'MCP not found'
      });
    }
    
    // Return manifest format for installation
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
      documentationUrl: mcp.documentationUrl
    };
    
    res.json({
      success: true,
      manifest
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to fetch manifest',
      message: error.message
    });
  }
});

app.get('/api/search', async (req, res) => {
  try {
    const { q } = req.query;
    
    if (!q || typeof q !== 'string') {
      return res.status(400).json({
        success: false,
        error: 'Query parameter "q" is required'
      });
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
    
    res.json({
      success: true,
      query: q,
      results: mcps,
      count: mcps.length
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Search failed',
      message: error.message
    });
  }
});

// GET /api/categories - Get available categories
app.get('/api/categories', async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const categories = await collection.distinct('category', {
      enabled: true,
      visibility: { $in: ['public', 'beta'] }
    });
    
    res.json({
      success: true,
      categories
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to fetch categories',
      message: error.message
    });
  }
});

// Middleware to check admin password
const checkAdminAuth = (req: any, res: any, next: any) => {
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({
      success: false,
      error: 'Unauthorized: No password provided'
    });
  }
  
  const password = authHeader.substring(7); // Remove 'Bearer ' prefix
  const adminPassword = process.env.ADMIN_PASSWORD || 'default-password-change-me';
  
  if (password !== adminPassword) {
    return res.status(401).json({
      success: false,
      error: 'Unauthorized: Invalid password'
    });
  }
  
  next();
};

app.post('/api/admin/registry', checkAdminAuth, async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const mcp = {
      ...req.body,
      createdAt: new Date(),
      updatedAt: new Date()
    };
    
    // Check if MCP already exists
    const existing = await collection.findOne({ id: mcp.id });
    if (existing) {
      return res.status(409).json({
        success: false,
        error: 'MCP with this ID already exists'
      });
    }
    
    await collection.insertOne(mcp);
    
    res.status(201).json({
      success: true,
      mcp
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to create MCP',
      message: error.message
    });
  }
});

// PUT /api/admin/registry/:id - Update an MCP
app.put('/api/admin/registry/:id', checkAdminAuth, async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const updates = {
      ...req.body,
      updatedAt: new Date()
    };
    
    // Remove fields that shouldn't be updated
    delete updates._id;
    delete updates.id;
    delete updates.createdAt;
    
    const result = await collection.findOneAndUpdate(
      { id: req.params.id },
      { $set: updates },
      { returnDocument: 'after' }
    );
    
    if (!result) {
      return res.status(404).json({
        success: false,
        error: 'MCP not found'
      });
    }
    
    res.json({
      success: true,
      mcp: result
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to update MCP',
      message: error.message
    });
  }
});

// DELETE /api/admin/registry/:id - Delete an MCP
app.delete('/api/admin/registry/:id', checkAdminAuth, async (req, res) => {
  try {
    const db = await getDatabase();
    const collection = db.collection('registry');
    
    const result = await collection.deleteOne({ id: req.params.id });
    
    if (result.deletedCount === 0) {
      return res.status(404).json({
        success: false,
        error: 'MCP not found'
      });
    }
    
    res.json({
      success: true,
      message: 'MCP deleted successfully'
    });
  } catch (error: any) {
    res.status(500).json({
      success: false,
      error: 'Failed to delete MCP',
      message: error.message
    });
  }
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({
    success: true,
    status: 'healthy',
    timestamp: new Date().toISOString()
  });
});

// Default route
app.get('/', (req, res) => {
  res.json({
    name: 'MCP Registry API',
    version: '1.0.0',
    endpoints: [
      'GET /api/registry - List all MCPs',
      'GET /api/registry/:id - Get MCP details',
      'GET /api/registry/:id/manifest - Get MCP manifest',
      'GET /api/search?q=query - Search MCPs',
      'GET /api/categories - Get available categories',
      'GET /api/health - Health check'
    ]
  });
});

// For local development
if (process.env.NODE_ENV !== 'production' && !process.env.VERCEL) {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`MCP Registry API running on port ${PORT}`);
  });
}

// For Vercel - export the Express app
export default app;