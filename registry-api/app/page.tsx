import Link from 'next/link';

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-16">
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold text-gray-800 mb-4">MCP Registry</h1>
          <p className="text-xl text-gray-600">Model Context Protocol Server Registry & Management</p>
        </div>


        <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          <Link href="/registry" className="block">
            <div className="bg-white rounded-xl shadow-lg hover:shadow-xl transition-shadow p-8 h-full">
              <div className="flex items-center mb-4">
                <svg className="w-12 h-12 text-blue-500 mr-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                <h2 className="text-2xl font-bold text-gray-800">Browse Registry</h2>
              </div>
              <p className="text-gray-600 mb-4">
                Explore available MCP servers, search by category, and download manifest files for installation.
              </p>
              <div className="text-blue-600 font-medium">
                Browse MCPs →
              </div>
            </div>
          </Link>

          <Link href="/admin" className="block">
            <div className="bg-white rounded-xl shadow-lg hover:shadow-xl transition-shadow p-8 h-full">
              <div className="flex items-center mb-4">
                <svg className="w-12 h-12 text-green-500 mr-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
                <h2 className="text-2xl font-bold text-gray-800">Admin Dashboard</h2>
              </div>
              <p className="text-gray-600 mb-4">
                Manage MCP servers, upload manifests, and configure registry settings with authentication.
              </p>
              <div className="text-green-600 font-medium">
                Manage Registry →
              </div>
            </div>
          </Link>
        </div>

        <div className="mt-16 bg-white rounded-xl shadow-lg p-8 max-w-4xl mx-auto">
          <h3 className="text-2xl font-bold text-gray-800 mb-6">API Endpoints</h3>
          
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <h4 className="font-semibold text-gray-700 mb-3">Public Endpoints</h4>
              <ul className="space-y-2 text-sm">
                <li className="flex items-start">
                  <span className="text-blue-500 mr-2">GET</span>
                  <span className="text-gray-600">/api/registry - List all MCPs</span>
                </li>
                <li className="flex items-start">
                  <span className="text-blue-500 mr-2">GET</span>
                  <span className="text-gray-600">/api/registry/:id - Get MCP details</span>
                </li>
                <li className="flex items-start">
                  <span className="text-blue-500 mr-2">GET</span>
                  <span className="text-gray-600">/api/registry/:id/manifest - Get manifest</span>
                </li>
                <li className="flex items-start">
                  <span className="text-blue-500 mr-2">GET</span>
                  <span className="text-gray-600">/api/search?q=query - Search MCPs</span>
                </li>
                <li className="flex items-start">
                  <span className="text-blue-500 mr-2">GET</span>
                  <span className="text-gray-600">/api/categories - Get categories</span>
                </li>
              </ul>
            </div>
            
            <div>
              <h4 className="font-semibold text-gray-700 mb-3">Admin Endpoints</h4>
              <ul className="space-y-2 text-sm">
                <li className="flex items-start">
                  <span className="text-green-500 mr-2">POST</span>
                  <span className="text-gray-600">/api/admin/registry - Create MCP</span>
                </li>
                <li className="flex items-start">
                  <span className="text-yellow-500 mr-2">PUT</span>
                  <span className="text-gray-600">/api/admin/registry/:id - Update MCP</span>
                </li>
                <li className="flex items-start">
                  <span className="text-red-500 mr-2">DELETE</span>
                  <span className="text-gray-600">/api/admin/registry/:id - Delete MCP</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}