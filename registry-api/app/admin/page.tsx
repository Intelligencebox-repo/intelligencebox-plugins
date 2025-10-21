'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface MCP {
  _id?: string;
  id: string;
  name: string;
  description: string;
  author: string;
  version: string;
  dockerImage: string;
  dockerTag?: string;
  entrypoint?: string | string[];
  configSchema?: any;
  requirements?: string[];
  icon?: string;
  category: string;
  tags?: string[];
  documentationUrl?: string;
  enabled: boolean;
  visibility: 'public' | 'beta' | 'private';
  featured?: boolean;

  // NEW: Docker configuration structure
  dockerDefaults?: {
    containerPort?: number;
    sseEndpoint?: string;
    protocol?: 'tcp' | 'udp';
    needsPortMapping?: boolean;
    defaultHostPort?: number;
    needsFileAccess?: boolean;
    volumeMounts?: Record<string, string>;
    resources?: {
      memory: string;
      cpus: string;
    };
  };

  // Legacy fields (keep for backward compatibility)
  transport?: 'sse' | 'stdio';
  port?: number;
  sseEndpoint?: string;
  needsFileAccess?: boolean;
  volumeMounts?: Record<string, string>;
}

export default function AdminDashboard() {
  const [mcps, setMcps] = useState<MCP[]>([]);
  const [password, setPassword] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingMcp, setEditingMcp] = useState<MCP | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const router = useRouter();

  useEffect(() => {
    const storedPassword = localStorage.getItem('adminPassword');
    if (storedPassword) {
      setPassword(storedPassword);
      setIsAuthenticated(true);
      fetchMcps(storedPassword);
    }
  }, []);

  const fetchMcps = async (authPassword: string) => {
    try {
      setLoading(true);
      const response = await fetch('/api/registry');
      const data = await response.json();
      if (data.success) {
        setMcps(data.mcps);
      }
    } catch (err) {
      setError('Failed to fetch MCPs');
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    localStorage.setItem('adminPassword', password);
    setIsAuthenticated(true);
    fetchMcps(password);
  };

  const handleLogout = () => {
    localStorage.removeItem('adminPassword');
    setIsAuthenticated(false);
    setPassword('');
    setMcps([]);
  };

  const handleManifestUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setManifestFile(file);
      try {
        const text = await file.text();
        const manifest = JSON.parse(text);
        
        if (editingMcp) {
          setEditingMcp({ ...editingMcp, ...manifest });
        } else {
          setEditingMcp({
            id: manifest.id || '',
            name: manifest.name || '',
            description: manifest.description || '',
            author: manifest.author || '',
            version: manifest.version || '1.0.0',
            dockerImage: manifest.dockerImage || '',
            dockerTag: manifest.dockerTag || 'latest',
            entrypoint: manifest.entrypoint || '',
            configSchema: manifest.configSchema || {},
            requirements: manifest.requirements || [],
            icon: manifest.icon || '',
            category: manifest.category || 'general',
            tags: manifest.tags || [],
            documentationUrl: manifest.documentationUrl || '',
            enabled: true,
            visibility: 'public',

            // NEW: Preserve dockerDefaults from manifest
            dockerDefaults: manifest.dockerDefaults,

            // Legacy fields
            transport: manifest.transport,
            port: manifest.port,
            sseEndpoint: manifest.sseEndpoint,
            needsFileAccess: manifest.needsFileAccess,
            volumeMounts: manifest.volumeMounts,
            featured: false
          });
          setShowCreateForm(true);
        }
      } catch (err) {
        setError('Invalid manifest file');
      }
    }
  };

  const handleCreateMcp = async () => {
    if (!editingMcp) return;
    
    try {
      setLoading(true);
      const response = await fetch('/api/admin/registry', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${password}`
        },
        body: JSON.stringify(editingMcp)
      });
      
      const data = await response.json();
      if (data.success) {
        await fetchMcps(password);
        setEditingMcp(null);
        setShowCreateForm(false);
        setManifestFile(null);
      } else {
        setError(data.error);
      }
    } catch (err) {
      setError('Failed to create MCP');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateMcp = async () => {
    if (!editingMcp) return;
    
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/registry/${editingMcp.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${password}`
        },
        body: JSON.stringify(editingMcp)
      });
      
      const data = await response.json();
      if (data.success) {
        await fetchMcps(password);
        setEditingMcp(null);
        setManifestFile(null);
      } else {
        setError(data.error);
      }
    } catch (err) {
      setError('Failed to update MCP');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteMcp = async (id: string) => {
    if (!confirm('Are you sure you want to delete this MCP?')) return;
    
    try {
      setLoading(true);
      const response = await fetch(`/api/admin/registry/${id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${password}`
        }
      });
      
      const data = await response.json();
      if (data.success) {
        await fetchMcps(password);
      } else {
        setError(data.error);
      }
    } catch (err) {
      setError('Failed to delete MCP');
    } finally {
      setLoading(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="bg-white p-8 rounded-lg shadow-md w-96">
          <h1 className="text-2xl font-bold mb-6">Admin Login</h1>
          <form onSubmit={handleLogin}>
            <input
              type="password"
              placeholder="Admin Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full p-2 border rounded mb-4"
              required
            />
            <button
              type="submit"
              className="w-full bg-blue-500 text-white p-2 rounded hover:bg-blue-600"
            >
              Login
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="container mx-auto px-4 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold">MCP Registry Admin</h1>
          <div className="flex gap-4">
            <button
              onClick={() => {
                setEditingMcp({
                  id: '',
                  name: '',
                  description: '',
                  author: '',
                  version: '1.0.0',
                  dockerImage: '',
                  dockerTag: 'latest',
                  entrypoint: '',
                  category: 'general',
                  tags: [],
                  enabled: true,
                  visibility: 'public',
                  featured: false
                });
                setShowCreateForm(true);
              }}
              className="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600"
            >
              Create New MCP
            </button>
            <button
              onClick={handleLogout}
              className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600"
            >
              Logout
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
            {error}
            <button onClick={() => setError('')} className="float-right">×</button>
          </div>
        )}

        {(showCreateForm || editingMcp) && (
          <div className="bg-white p-6 rounded-lg shadow-md mb-8">
            <h2 className="text-xl font-bold mb-4">
              {editingMcp?._id ? 'Edit MCP' : 'Create New MCP'}
            </h2>
            
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">
                Upload Manifest (JSON)
              </label>
              <input
                type="file"
                accept=".json"
                onChange={handleManifestUpload}
                className="w-full p-2 border rounded"
              />
              {manifestFile && (
                <p className="text-sm text-green-600 mt-1">
                  Manifest loaded: {manifestFile.name}
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-1">ID</label>
                <input
                  type="text"
                  value={editingMcp?.id || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, id: e.target.value })}
                  className="w-full p-2 border rounded"
                  required
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input
                  type="text"
                  value={editingMcp?.name || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, name: e.target.value })}
                  className="w-full p-2 border rounded"
                  required
                />
              </div>

              <div className="col-span-2">
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea
                  value={editingMcp?.description || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, description: e.target.value })}
                  className="w-full p-2 border rounded"
                  rows={3}
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Author</label>
                <input
                  type="text"
                  value={editingMcp?.author || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, author: e.target.value })}
                  className="w-full p-2 border rounded"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Version</label>
                <input
                  type="text"
                  value={editingMcp?.version || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, version: e.target.value })}
                  className="w-full p-2 border rounded"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Docker Image</label>
                <input
                  type="text"
                  value={editingMcp?.dockerImage || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, dockerImage: e.target.value })}
                  className="w-full p-2 border rounded"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Docker Tag</label>
                <input
                  type="text"
                  value={editingMcp?.dockerTag || 'latest'}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, dockerTag: e.target.value })}
                  className="w-full p-2 border rounded"
                />
              </div>

              <div className="col-span-2">
                <label className="block text-sm font-medium mb-1">Entrypoint</label>
                <input
                  type="text"
                  value={Array.isArray(editingMcp?.entrypoint) ? editingMcp.entrypoint.join(' ') : editingMcp?.entrypoint || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, entrypoint: e.target.value })}
                  className="w-full p-2 border rounded"
                  placeholder="e.g., node /app/dist/index.js"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Category</label>
                <select
                  value={editingMcp?.category || 'general'}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, category: e.target.value })}
                  className="w-full p-2 border rounded"
                >
                  <option value="general">General</option>
                  <option value="productivity">Productivity</option>
                  <option value="development">Development</option>
                  <option value="data">Data</option>
                  <option value="ai">AI</option>
                  <option value="automation">Automation</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Visibility</label>
                <select
                  value={editingMcp?.visibility || 'public'}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, visibility: e.target.value as 'public' | 'beta' | 'private' })}
                  className="w-full p-2 border rounded"
                >
                  <option value="public">Public</option>
                  <option value="beta">Beta</option>
                  <option value="private">Private</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Tags (comma-separated)</label>
                <input
                  type="text"
                  value={editingMcp?.tags?.join(', ') || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, tags: e.target.value.split(',').map(t => t.trim()) })}
                  className="w-full p-2 border rounded"
                  placeholder="e.g., tool, api, integration"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Documentation URL</label>
                <input
                  type="url"
                  value={editingMcp?.documentationUrl || ''}
                  onChange={(e) => setEditingMcp({ ...editingMcp!, documentationUrl: e.target.value })}
                  className="w-full p-2 border rounded"
                />
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={editingMcp?.enabled || false}
                    onChange={(e) => setEditingMcp({ ...editingMcp!, enabled: e.target.checked })}
                    className="mr-2"
                  />
                  Enabled
                </label>
                
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={editingMcp?.featured || false}
                    onChange={(e) => setEditingMcp({ ...editingMcp!, featured: e.target.checked })}
                    className="mr-2"
                  />
                  Featured
                </label>
              </div>
            </div>

            <div className="flex gap-4 mt-6">
              <button
                onClick={editingMcp?._id ? handleUpdateMcp : handleCreateMcp}
                disabled={loading}
                className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 disabled:opacity-50"
              >
                {loading ? 'Saving...' : editingMcp?._id ? 'Update' : 'Create'}
              </button>
              <button
                onClick={() => {
                  setEditingMcp(null);
                  setShowCreateForm(false);
                  setManifestFile(null);
                }}
                className="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-md overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Author</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {mcps.map((mcp) => (
                <tr key={mcp.id}>
                  <td className="px-6 py-4">
                    <div>
                      <div className="text-sm font-medium text-gray-900">{mcp.name}</div>
                      <div className="text-sm text-gray-500">{mcp.description.substring(0, 50)}...</div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">{mcp.author}</td>
                  <td className="px-6 py-4 text-sm text-gray-900">{mcp.version}</td>
                  <td className="px-6 py-4 text-sm text-gray-900">{mcp.category}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-1 text-xs rounded-full ${
                      mcp.enabled ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                    }`}>
                      {mcp.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    {mcp.featured && (
                      <span className="ml-2 px-2 py-1 text-xs bg-yellow-100 text-yellow-800 rounded-full">
                        Featured
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-sm">
                    <button
                      onClick={() => setEditingMcp(mcp)}
                      className="text-blue-600 hover:text-blue-900 mr-3"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDeleteMcp(mcp.id)}
                      className="text-red-600 hover:text-red-900"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          
          {mcps.length === 0 && !loading && (
            <div className="text-center py-8 text-gray-500">
              No MCPs found
            </div>
          )}
        </div>
      </div>
    </div>
  );
}