'use client';

import { useState, useEffect } from 'react';

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
  icon?: string;
  category: string;
  tags?: string[];
  documentationUrl?: string;
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

export default function RegistryBrowser() {
  const [mcps, setMcps] = useState<MCP[]>([]);
  const [filteredMcps, setFilteredMcps] = useState<MCP[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedMcp, setSelectedMcp] = useState<MCP | null>(null);
  const [showManifest, setShowManifest] = useState(false);

  useEffect(() => {
    fetchMcps();
    fetchCategories();
  }, []);

  useEffect(() => {
    filterMcps();
  }, [searchQuery, selectedCategory, mcps]);

  const fetchMcps = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/registry');
      const data = await response.json();
      if (data.success) {
        setMcps(data.mcps);
        setFilteredMcps(data.mcps);
      }
    } catch (err) {
      setError('Failed to fetch MCPs');
    } finally {
      setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const response = await fetch('/api/categories');
      const data = await response.json();
      if (data.success) {
        setCategories(data.categories);
      }
    } catch (err) {
      console.error('Failed to fetch categories');
    }
  };

  const filterMcps = () => {
    let filtered = [...mcps];
    
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(mcp => mcp.category === selectedCategory);
    }
    
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(mcp => 
        mcp.name.toLowerCase().includes(query) ||
        mcp.description.toLowerCase().includes(query) ||
        mcp.author.toLowerCase().includes(query) ||
        mcp.tags?.some(tag => tag.toLowerCase().includes(query))
      );
    }
    
    setFilteredMcps(filtered);
  };

  const fetchManifest = async (id: string) => {
    try {
      const response = await fetch(`/api/registry/${id}/manifest`);
      const data = await response.json();
      if (data.success) {
        return data.manifest;
      }
    } catch (err) {
      console.error('Failed to fetch manifest');
    }
    return null;
  };

  const handleDownloadManifest = async (mcp: MCP) => {
    const manifest = await fetchManifest(mcp.id);
    if (manifest) {
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${mcp.id}-manifest.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  const handleShowManifest = async (mcp: MCP) => {
    setSelectedMcp(mcp);
    const manifest = await fetchManifest(mcp.id);
    if (manifest) {
      const manifestData = {
        ...manifest,
        featured: mcp.featured
      } as MCP;

      if (!Object.prototype.hasOwnProperty.call(manifest, 'volumeMounts')) {
        delete (manifestData as Partial<MCP>).volumeMounts;
      }

      if (manifestData.dockerDefaults && !Object.prototype.hasOwnProperty.call(manifestData.dockerDefaults, 'volumeMounts')) {
        delete manifestData.dockerDefaults.volumeMounts;
      }

      setSelectedMcp(manifestData);
      setShowManifest(true);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-4">MCP Registry</h1>
          <p className="text-gray-600">Browse and download Model Context Protocol servers</p>
        </div>

        <div className="bg-white rounded-lg shadow-md p-6 mb-8">
          <div className="flex flex-col md:flex-row gap-4">
            <input
              type="text"
              placeholder="Search MCPs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 p-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="p-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Categories</option>
              {categories.map(cat => (
                <option key={cat} value={cat}>
                  {cat.charAt(0).toUpperCase() + cat.slice(1)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-12">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
            <p className="mt-4 text-gray-600">Loading MCPs...</p>
          </div>
        ) : error ? (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredMcps.map((mcp) => (
              <div key={mcp.id} className="bg-white rounded-lg shadow-md hover:shadow-lg transition-shadow">
                <div className="p-6">
                  {mcp.featured && (
                    <span className="inline-block px-3 py-1 text-xs bg-yellow-100 text-yellow-800 rounded-full mb-3">
                      Featured
                    </span>
                  )}
                  <h3 className="text-xl font-semibold mb-2">{mcp.name}</h3>
                  <p className="text-gray-600 mb-4 line-clamp-3">{mcp.description}</p>
                  
                  <div className="text-sm text-gray-500 mb-4">
                    <div className="mb-1">
                      <span className="font-medium">Author:</span> {mcp.author}
                    </div>
                    <div className="mb-1">
                      <span className="font-medium">Version:</span> {mcp.version}
                    </div>
                    <div className="mb-1">
                      <span className="font-medium">Category:</span> {mcp.category}
                    </div>
                  </div>

                  {mcp.tags && mcp.tags.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-4">
                      {mcp.tags.map((tag, index) => (
                        <span key={index} className="px-2 py-1 text-xs bg-gray-100 text-gray-700 rounded">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <button
                      onClick={() => handleShowManifest(mcp)}
                      className="flex-1 bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors"
                    >
                      View Details
                    </button>
                    <button
                      onClick={() => handleDownloadManifest(mcp)}
                      className="flex-1 bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600 transition-colors"
                    >
                      Download Manifest
                    </button>
                  </div>
                  
                  {mcp.documentationUrl && (
                    <a
                      href={mcp.documentationUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block mt-3 text-center text-blue-600 hover:text-blue-800 text-sm"
                    >
                      View Documentation →
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {filteredMcps.length === 0 && !loading && (
          <div className="text-center py-12">
            <p className="text-gray-500">No MCPs found matching your criteria</p>
          </div>
        )}

        {showManifest && selectedMcp && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg max-w-4xl w-full max-h-[80vh] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b p-6">
                <div className="flex justify-between items-start">
                  <div>
                    <h2 className="text-2xl font-bold">{selectedMcp.name}</h2>
                    <p className="text-gray-600 mt-1">{selectedMcp.description}</p>
                  </div>
                  <button
                    onClick={() => {
                      setShowManifest(false);
                      setSelectedMcp(null);
                    }}
                    className="text-gray-500 hover:text-gray-700"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
              
              <div className="p-6">
                <div className="grid grid-cols-2 gap-4 mb-6">
                  <div>
                    <h3 className="font-semibold text-gray-700 mb-1">Docker Image</h3>
                    <p className="text-gray-600">{selectedMcp.dockerImage}:{selectedMcp.dockerTag || 'latest'}</p>
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-700 mb-1">Version</h3>
                    <p className="text-gray-600">{selectedMcp.version}</p>
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-700 mb-1">Author</h3>
                    <p className="text-gray-600">{selectedMcp.author}</p>
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-700 mb-1">Category</h3>
                    <p className="text-gray-600">{selectedMcp.category}</p>
                  </div>
                </div>

                {selectedMcp.entrypoint && (
                  <div className="mb-6">
                    <h3 className="font-semibold text-gray-700 mb-1">Entrypoint</h3>
                    <code className="block bg-gray-100 p-3 rounded text-sm">
                      {Array.isArray(selectedMcp.entrypoint) 
                        ? selectedMcp.entrypoint.join(' ') 
                        : selectedMcp.entrypoint}
                    </code>
                  </div>
                )}

                <div className="mb-6">
                  <h3 className="font-semibold text-gray-700 mb-2">Installation</h3>
                  <div className="bg-gray-100 p-4 rounded">
                    <p className="text-sm text-gray-600 mb-2">To install this MCP, add the following to your Claude configuration:</p>
                    <code className="block bg-white p-3 rounded text-sm border">
                      {JSON.stringify({
                        [selectedMcp.id]: {
                          dockerImage: selectedMcp.dockerImage,
                          dockerTag: selectedMcp.dockerTag || 'latest',
                          entrypoint: selectedMcp.entrypoint
                        }
                      }, null, 2)}
                    </code>
                  </div>
                </div>

                <div className="flex gap-3">
                  <button
                    onClick={() => handleDownloadManifest(selectedMcp)}
                    className="flex-1 bg-green-500 text-white px-6 py-3 rounded hover:bg-green-600 transition-colors"
                  >
                    Download Manifest
                  </button>
                  {selectedMcp.documentationUrl && (
                    <a
                      href={selectedMcp.documentationUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex-1 bg-blue-500 text-white px-6 py-3 rounded hover:bg-blue-600 transition-colors text-center"
                    >
                      View Documentation
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
