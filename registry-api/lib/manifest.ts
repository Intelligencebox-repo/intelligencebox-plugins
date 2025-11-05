import path from 'path';
import { promises as fs } from 'fs';

type ManifestShape = Record<string, any>;

const MANIFEST_FILENAME = 'manifest.json';
const SERVERS_ROOT = path.resolve(process.cwd(), '..', 'servers');

/**
 * Attempt to read the manifest.json belonging to the provided MCP id by scanning the servers folder.
 * Returns null when the manifest cannot be found so callers can gracefully fall back to DB values.
 */
export async function loadManifestFromFilesystem(id: string): Promise<ManifestShape | null> {
  let dirEntries;

  try {
    dirEntries = await fs.readdir(SERVERS_ROOT, { withFileTypes: true });
  } catch (error: any) {
    if (error?.code === 'ENOENT') {
      return null;
    }
    throw error;
  }

  for (const entry of dirEntries) {
    if (!entry.isDirectory()) {
      continue;
    }

    const manifestPath = path.join(SERVERS_ROOT, entry.name, MANIFEST_FILENAME);

    try {
      const raw = await fs.readFile(manifestPath, 'utf-8');
      const manifest = JSON.parse(raw);

      if (manifest?.id === id) {
        return manifest;
      }
    } catch (error: any) {
      if (error?.code === 'ENOENT') {
        continue;
      }

      // Surface JSON parsing errors: these indicate a bad manifest file which should not be ignored.
      throw new Error(`Failed to parse manifest at ${manifestPath}: ${error.message}`);
    }
  }

  return null;
}

function selectDockerDefaults(mcp: any, manifest: ManifestShape | null) {
  const manifestDefaults = manifest?.dockerDefaults ?? {};
  const storedDefaults = mcp?.dockerDefaults ?? {};

  const needsFileAccess =
    manifestDefaults.needsFileAccess ??
    storedDefaults.needsFileAccess ??
    mcp?.needsFileAccess ??
    false;

  const dockerDefaults: Record<string, any> = {
    containerPort:
      manifestDefaults.containerPort ??
      storedDefaults.containerPort ??
      mcp?.port,
    sseEndpoint:
      manifestDefaults.sseEndpoint ??
      storedDefaults.sseEndpoint ??
      mcp?.sseEndpoint,
    protocol:
      manifestDefaults.protocol ??
      storedDefaults.protocol ??
      'tcp',
    needsPortMapping:
      manifestDefaults.needsPortMapping ??
      storedDefaults.needsPortMapping ??
      (manifest?.transport ?? mcp?.transport) === 'sse',
    defaultHostPort:
      manifestDefaults.defaultHostPort ??
      storedDefaults.defaultHostPort ??
      mcp?.port,
    needsFileAccess,
    resources:
      manifestDefaults.resources ??
      storedDefaults.resources ?? {
        memory: '512m',
        cpus: '0.5'
      }
  };

  const volumeMounts =
    manifestDefaults.volumeMounts ??
    storedDefaults.volumeMounts ??
    mcp?.volumeMounts;

  if (volumeMounts !== undefined && volumeMounts !== null) {
    dockerDefaults.volumeMounts = volumeMounts;
  }

  return dockerDefaults;
}

/**
 * Merge the database MCP document with its corresponding manifest file (when present).
 * Manifest values win over DB values so updates in the filesystem are immediately reflected.
 */
export function mergeMcpWithManifest(mcp: any, manifest: ManifestShape | null) {
  const dockerDefaults = selectDockerDefaults(mcp, manifest);

  const merged = {
    ...mcp,
    ...(manifest ?? {}),
    dockerDefaults,

    // Maintain legacy compatibility fields alongside dockerDefaults.
    transport: manifest?.transport ?? mcp.transport ?? 'stdio',
    entrypoint: manifest?.entrypoint ?? mcp.entrypoint,
    dockerImage: manifest?.dockerImage ?? mcp.dockerImage,
    dockerTag: manifest?.dockerTag ?? mcp.dockerTag ?? 'latest',
    version: manifest?.version ?? mcp.version,
    requirements: manifest?.requirements ?? mcp.requirements,
    configSchema: manifest?.configSchema ?? mcp.configSchema,
    tags: manifest?.tags ?? mcp.tags,
    category: manifest?.category ?? mcp.category,
    icon: manifest?.icon ?? mcp.icon,
    name: manifest?.name ?? mcp.name,
    description: manifest?.description ?? mcp.description,
    author: manifest?.author ?? mcp.author,
    documentationUrl: manifest?.documentationUrl ?? mcp.documentationUrl,
    features: manifest?.features ?? mcp.features,
    needsFileAccess: dockerDefaults.needsFileAccess
  };

  if (Object.prototype.hasOwnProperty.call(dockerDefaults, 'volumeMounts')) {
    merged.volumeMounts = dockerDefaults.volumeMounts;
  } else {
    delete merged.volumeMounts;
  }

  return merged;
}
