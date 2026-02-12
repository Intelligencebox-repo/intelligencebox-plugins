import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import http from 'http';
import { promisify } from 'util';
import { execFile } from 'child_process';
import { PDFParse } from 'pdf-parse';
import XLSX from 'xlsx';
import { ExtractWirelistInput } from './schema.js';

const execFileAsync = promisify(execFile);
// Concorrenza per le richieste parallele
const VISION_CONCURRENCY = parseInt(process.env.VISION_CONCURRENCY || '10', 10);
const VISION_MAX_RETRIES = parseInt(process.env.VISION_MAX_RETRIES || '3', 10);
const DEFAULT_PDF_RENDER_DPI = 300;
const DEFAULT_PDF_TILE_GRID = 2; // 2x2 tiles by default to help read small red IDs

// Vision API configuration (OpenAI-compatible proxy)
// NOTE: Non usare const per API key - dotenv potrebbe non aver ancora caricato le variabili al momento dell'import
const OPENROUTER_MODEL = process.env.OPENROUTER_MODEL || 'openrouter/google/gemini-3-flash-preview';
const OPENROUTER_BASE_URL = process.env.OPENROUTER_BASE_URL || 'https://proxy.intelligencebox.it/v1';

function ensureApiKey(): string {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) {
    throw new Error('OPENROUTER_API_KEY non configurata. Impostare la variabile d\'ambiente OPENROUTER_API_KEY nel file .env');
  }
  return key;
}

function getVisionModel(): string {
  return OPENROUTER_MODEL;
}

// Auto-detect environment for webhook URL
function isRunningInDocker(): boolean {
  // Check common Docker indicators
  try {
    // /.dockerenv exists in Docker containers
    require('fs').accessSync('/.dockerenv');
    return true;
  } catch {
    // Check cgroup for docker/containerd
    try {
      const cgroup = require('fs').readFileSync('/proc/1/cgroup', 'utf8');
      return cgroup.includes('docker') || cgroup.includes('containerd');
    } catch {
      return false;
    }
  }
}

function getProgressWebhookUrl(): string {
  if (process.env.PROGRESS_WEBHOOK_URL) {
    return process.env.PROGRESS_WEBHOOK_URL;
  }

  const inDocker = isRunningInDocker();

  // Check if box-server is on the same Docker network (full Docker deployment)
  const boxServerOnNetwork = process.env.DOCKER_ENV === 'true' ||
                              process.env.BOX_SERVER_HOST === 'box-server';

  if (inDocker) {
    if (boxServerOnNetwork) {
      // Full Docker: both services on same network
      return 'http://box-server:3001/api/mcp/progress';
    } else {
      // Dev mode: MCP in Docker, box-server on host
      // Use host.docker.internal to reach host from container
      return 'http://host.docker.internal:3001/api/mcp/progress';
    }
  }

  // Not in Docker: local development
  return 'http://127.0.0.1:3001/api/mcp/progress';
}

const PROGRESS_WEBHOOK_URL = getProgressWebhookUrl();

function log(message: string): void {
  process.stderr.write(`[wirelist] ${message}\n`);
}

// Log the webhook URL at startup for debugging
log(`Progress webhook URL: ${PROGRESS_WEBHOOK_URL}`);

export interface ProgressPayload {
  invocationId: string;
  toolName: string;
  status: 'in_progress' | 'completed' | 'failed';
  progress: number; // 0-100
  message: string;
}

async function sendProgress(payload: ProgressPayload): Promise<void> {
  return new Promise((resolve) => {
    try {
      const url = new URL(PROGRESS_WEBHOOK_URL);
      const data = JSON.stringify(payload);

      const options: http.RequestOptions = {
        hostname: url.hostname,
        port: url.port || 3001,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data)
        },
        timeout: 5000
      };

      const req = http.request(options, (res) => {
        if (res.statusCode !== 200) {
          log(`Progress webhook returned ${res.statusCode}`);
        }
        // Consume response to free up resources
        res.resume();
        resolve();
      });

      req.on('error', (err: NodeJS.ErrnoException) => {
        log(`Progress webhook error: code=${err.code || 'none'}, errno=${err.errno || 'none'}, syscall=${err.syscall || 'none'}, message=${err.message}`);
        resolve(); // Non-blocking: continue even if webhook fails
      });

      req.on('timeout', () => {
        log(`Progress webhook timeout after 5s`);
        req.destroy();
        resolve();
      });

      req.write(data);
      req.end();
    } catch (err: any) {
      log(`Progress webhook setup error: ${err.message}`);
      resolve();
    }
  });
}

export interface ProgressContext {
  invocationId?: string;
  toolName?: string;
}

async function reportProgress(ctx: ProgressContext | undefined, progress: number, message: string, status: 'in_progress' | 'completed' | 'failed' = 'in_progress'): Promise<void> {
  if (!ctx?.invocationId) return;
  await sendProgress({
    invocationId: ctx.invocationId,
    toolName: ctx.toolName || 'extract_wirelist',
    status,
    progress: Math.round(Math.min(100, Math.max(0, progress))),
    message
  });
}

// Only exclude generic phase/ground indicators, NOT L1/L2/L3 which are often real wire IDs
const PHASE_ONLY_IDS = new Set(['N', 'PE', 'PEN']);

function isNumericCoordinate(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  return /^-?\d+(?:[.,]\d+)?$/.test(value.trim());
}

function markRimandoEndpoint(endpoint: unknown, note?: string): { endpoint: string | undefined; note?: string } {
  if (typeof endpoint !== 'string') return { endpoint: endpoint as any, note };
  if (!isNumericCoordinate(endpoint)) return { endpoint, note };

  const labeled = `rimando ${endpoint.trim()}`;
  const combinedNote = [note, `rimando/coord: ${endpoint.trim()}`].filter(Boolean).join(' | ');
  return { endpoint: labeled, note: combinedNote };
}

function sanitizeGaugeValue(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;

  const lower = trimmed.toLowerCase();
  if (lower.includes('mm')) {
    return trimmed;
  }

  if (/^\d+\s*x\s*\d+/i.test(lower)) {
    return trimmed;
  }

  const numeric = Number(lower.replace(',', '.'));
  if (!Number.isNaN(numeric) && numeric > 0 && numeric <= 70) {
    // Limite a 70mm² per evitare che rimandi pagina (es. 160.2) finiscano nella sezione
    return trimmed;
  }

  return undefined;
}

function sanitizeLengthValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const numeric = Number(value.replace(',', '.'));
    if (!Number.isNaN(numeric) && numeric > 0 && numeric < 1_000_000) {
      return numeric;
    }
  }
  return undefined;
}

function shouldDropWireId(id?: string): boolean {
  if (!id) return false;
  const trimmed = id.trim();
  if (/^W/i.test(trimmed)) return true; // Escludi cavi Wxxx
  if (PHASE_ONLY_IDS.has(trimmed.toUpperCase())) return true; // Evita ID solo di fase
  return false;
}

// ============================================================
// Wire Graph Resolution - Tracciamento fili attraverso pagine
// ============================================================

type EndpointType = 'component' | 'reference' | 'terminal';

interface WireNode {
  name: string;
  type: EndpointType;
  page?: number;
  foglio?: number;  // Sheet number from cartiglio
}

interface WireEdge {
  from: string;
  to: string;
  page?: number;
}

interface WireGraphData {
  nodes: WireNode[];
  edges: WireEdge[];
}

/**
 * Classifica un endpoint come componente, rimando (reference), o morsettiera (terminal)
 */
function classifyEndpoint(endpoint: string): EndpointType {
  const trimmed = endpoint.trim().toLowerCase();
  // Rimandi: "rimando 108.8", "rimando 174.8"
  if (trimmed.startsWith('rimando')) return 'reference';
  // Morsettiere: X1.xx, XT1.xx, X2:xx, XT3:xx
  if (/^-?x\d+[.:]/i.test(trimmed) || /^-?xt\d+[.:]/i.test(trimmed)) return 'terminal';
  return 'component';
}

/**
 * Normalizza rimando a solo numero pagina (ignora posizione)
 * "rimando 105.1" → "rimando 105"
 * "rimando 104.8" → "rimando 104"
 * Questo permette di collegare rimandi tra pagine anche se le posizioni differiscono
 */
function normalizeRimando(endpoint: string): string {
  const match = endpoint.match(/^rimando\s+(\d+)\.?\d*$/i);
  if (match) {
    return `rimando ${match[1]}`;
  }
  return endpoint;
}

/**
 * Rende un nodo rimando unico per foglio sorgente, evitando cortocircuiti nel grafo.
 * "rimando 105" su foglio 108 → "rimando 105@108"
 */
function makeRimandoUnique(endpoint: string, foglio?: number): string {
  if (foglio !== undefined && /^rimando\s+\d+$/i.test(endpoint)) {
    return `${endpoint}@${foglio}`;
  }
  return endpoint;
}

/**
 * Costruisce un grafo per ogni ID filo.
 * I nodi rimando sono resi unici per foglio sorgente per evitare che rimandi
 * su pagine diverse vengano fusi in un unico nodo (creando connessioni fantasma).
 */
function buildWireGraph(wires: WireRecord[]): Map<string, WireGraphData> {
  const graphs = new Map<string, WireGraphData>();

  for (const wire of wires) {
    const id = wire.id?.trim();
    if (!id) continue;

    if (!graphs.has(id)) {
      graphs.set(id, { nodes: [], edges: [] });
    }

    const g = graphs.get(id)!;

    // Normalize rimando to page-only, then make unique per source foglio
    if (wire.from) {
      const normalized = normalizeRimando(wire.from.trim());
      const unique = makeRimandoUnique(normalized, wire.foglio);
      g.nodes.push({ name: unique, type: classifyEndpoint(normalized), page: wire.page, foglio: wire.foglio });
    }
    if (wire.to) {
      const normalized = normalizeRimando(wire.to.trim());
      const unique = makeRimandoUnique(normalized, wire.foglio);
      g.nodes.push({ name: unique, type: classifyEndpoint(normalized), page: wire.page, foglio: wire.foglio });
    }

    // Add edge with unique rimando names
    if (wire.from && wire.to) {
      const fromNorm = normalizeRimando(wire.from.trim());
      const toNorm = normalizeRimando(wire.to.trim());
      g.edges.push({
        from: makeRimandoUnique(fromNorm, wire.foglio),
        to: makeRimandoUnique(toNorm, wire.foglio),
        page: wire.page
      });
    }
  }

  // Post-process: connect complementary rimandi across fogli
  // If foglio X has "rimando Y@X" and foglio Y has "rimando X@Y", add cross-page edge
  for (const [, graph] of graphs) {
    // Collect rimando nodes with their target foglio and source foglio
    const rimandoByTargetFoglio = new Map<number, { nodeName: string; sourceFoglio?: number }[]>();

    for (const node of graph.nodes) {
      if (node.type === 'reference') {
        // Match unique rimando format: "rimando 105@108" → target=105, source=108
        const match = node.name.match(/^rimando\s+(\d+)@(\d+)$/i);
        if (match) {
          const targetFoglio = parseInt(match[1], 10);
          const sourceFoglio = parseInt(match[2], 10);
          if (!rimandoByTargetFoglio.has(targetFoglio)) {
            rimandoByTargetFoglio.set(targetFoglio, []);
          }
          rimandoByTargetFoglio.get(targetFoglio)!.push({
            nodeName: node.name,
            sourceFoglio
          });
        } else {
          // Fallback: rimando without @foglio (foglio was undefined)
          const fallbackMatch = node.name.match(/^rimando\s+(\d+)$/i);
          if (fallbackMatch) {
            const targetFoglio = parseInt(fallbackMatch[1], 10);
            if (!rimandoByTargetFoglio.has(targetFoglio)) {
              rimandoByTargetFoglio.set(targetFoglio, []);
            }
            rimandoByTargetFoglio.get(targetFoglio)!.push({
              nodeName: node.name,
              sourceFoglio: node.foglio
            });
          }
        }
      }
    }

    // Connect rimandi: if foglio X has "rimando Y@X" and foglio Y has "rimando X@Y"
    for (const [targetFoglio, rimandos] of rimandoByTargetFoglio) {
      for (const rimando of rimandos) {
        const sourceFoglio = rimando.sourceFoglio;
        if (sourceFoglio === undefined) continue;

        // Look for rimandi on the target foglio that point back to source foglio
        const reverseRimandos = rimandoByTargetFoglio.get(sourceFoglio);
        if (reverseRimandos) {
          for (const reverseRimando of reverseRimandos) {
            if (reverseRimando.sourceFoglio === targetFoglio) {
              graph.edges.push({
                from: rimando.nodeName,
                to: reverseRimando.nodeName
              });
            }
          }
        }
      }
    }
  }

  return graphs;
}

/**
 * BFS per trovare i nodi reali DIRETTAMENTE adiacenti (connessi solo tramite rimandi intermedi).
 * A differenza del BFS classico, si FERMA ai nodi reali senza attraversarli.
 * Questo evita connessioni fantasma: per una catena A→B→C, trova solo A↔B e B↔C, non A↔C.
 */
function bfsReachableRealNodes(
  adj: Map<string, Set<string>>,
  start: string,
  realNodes: Set<string>
): Set<string> {
  const visited = new Set<string>();
  const queue: string[] = [start];
  const reachable = new Set<string>();

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (visited.has(current)) continue;
    visited.add(current);

    // Se è un nodo reale (non un rimando) e non è il punto di partenza, aggiungilo
    // ma NON continuare ad esplorare oltre: ferma la BFS a questo nodo
    if (realNodes.has(current) && current !== start) {
      reachable.add(current);
      continue; // Non attraversare nodi reali - trova solo adiacenti diretti
    }

    // Esplora i vicini solo per nodi non-reali (rimandi) o il nodo di partenza
    const neighbors = adj.get(current);
    if (neighbors) {
      for (const neighbor of neighbors) {
        if (!visited.has(neighbor)) {
          queue.push(neighbor);
        }
      }
    }
  }

  return reachable;
}

/**
 * Risolve le connessioni tra nodi reali (componenti/morsettiere) attraverso i rimandi
 */
function resolveWireConnections(graphs: Map<string, WireGraphData>): WireRecord[] {
  const resolved: WireRecord[] = [];

  for (const [wireId, graph] of graphs) {
    // Get unique real endpoints (not references)
    const realNodesSet = new Set<string>();
    const nodePageMap = new Map<string, number>();

    for (const node of graph.nodes) {
      if (node.type !== 'reference') {
        realNodesSet.add(node.name);
        // Track first page where node appears
        if (node.page !== undefined && !nodePageMap.has(node.name)) {
          nodePageMap.set(node.name, node.page);
        }
      }
    }

    if (realNodesSet.size < 2) continue;

    // Build adjacency list (undirected graph)
    const adj = new Map<string, Set<string>>();
    for (const edge of graph.edges) {
      if (!adj.has(edge.from)) adj.set(edge.from, new Set());
      if (!adj.has(edge.to)) adj.set(edge.to, new Set());
      adj.get(edge.from)!.add(edge.to);
      adj.get(edge.to)!.add(edge.from);
    }

    // Find all pairs of connected real nodes using BFS
    const visitedPairs = new Set<string>();
    for (const start of realNodesSet) {
      const reachable = bfsReachableRealNodes(adj, start, realNodesSet);
      for (const end of reachable) {
        // Create canonical key to avoid duplicates (A→B = B→A)
        const key = [start, end].sort().join('|');
        if (!visitedPairs.has(key)) {
          visitedPairs.add(key);
          resolved.push({
            id: wireId,
            from: start,
            to: end,
            page: nodePageMap.get(start) ?? nodePageMap.get(end)
          });
        }
      }
    }
  }

  return resolved;
}

// ============================================================
// Visual Graph Generation - Grafo visuale dello schema elettrico
// ============================================================

type ComponentType = 'breaker' | 'relay' | 'power' | 'terminal' | 'fuse' | 'switch' | 'lamp' | 'plc' | 'motor' | 'other';

interface SchemaGraphNode {
  id: string;
  type: ComponentType;
  label: string;
  page?: number;
}

interface SchemaGraphEdge {
  source: string;
  target: string;
  wireId: string;
  label: string;
}

interface SchemaGraph {
  nodes: SchemaGraphNode[];
  edges: SchemaGraphEdge[];
}

/**
 * Classifica un componente in base al prefisso della sua sigla
 */
function classifyComponentType(ref: string): ComponentType {
  // Remove leading dash and get prefix (letters before numbers)
  const cleaned = ref.replace(/^-/, '').toUpperCase();
  const prefix = cleaned.replace(/\d+.*/, '');

  switch (prefix) {
    case 'QF':
    case 'QM':
    case 'QS':
      return 'breaker'; // Magnetotermici, sezionatori
    case 'KM':
    case 'KA':
    case 'K':
      return 'relay'; // Relè, contattori
    case 'TS':
    case 'PS':
    case 'G':
      return 'power'; // Alimentatori, generatori
    case 'XT':
    case 'X':
      return 'terminal'; // Morsettiere
    case 'FS':
    case 'FU':
      return 'fuse'; // Fusibili
    case 'SB':
    case 'SA':
    case 'S':
      return 'switch'; // Pulsanti, selettori
    case 'HL':
    case 'H':
      return 'lamp'; // Lampade spia
    case 'AP':
    case 'PLC':
    case 'CPU':
      return 'plc'; // PLC, moduli
    case 'M':
    case 'MOT':
      return 'motor'; // Motori
    default:
      return 'other';
  }
}

const COMPONENT_COLORS: Record<ComponentType, string> = {
  breaker: '#90EE90',  // Light green
  relay: '#87CEEB',    // Sky blue
  power: '#FFB6C1',    // Light pink
  terminal: '#D3D3D3', // Light gray
  fuse: '#FFA500',     // Orange
  switch: '#FFFF00',   // Yellow
  lamp: '#DDA0DD',     // Plum
  plc: '#00CED1',      // Dark cyan
  motor: '#98FB98',    // Pale green
  other: '#FFFFFF'     // White
};

/**
 * Separa un endpoint in componente e PIN.
 * Il componente è il riferimento base (lettere+numeri, eventualmente con dash compound),
 * il PIN è il terminale numerico finale.
 *
 * Es: "QM102.13" → { component: "QM102", pin: "13" }
 *     "AP602-EN101:X1.21" → { component: "AP602-EN101", pin: "21" }
 *     "AP601-ID101.X1:21" → { component: "AP601-ID101", pin: "21" }
 *     "XT3.24.1" → { component: "XT3", pin: "24.1" }
 *     "-QM102.13" → { component: "-QM102", pin: "13" }
 *     "XT1.1102" → { component: "XT1", pin: "1102" }
 *     "KM131.2" → { component: "KM131", pin: "2" }
 */
function splitComponentPin(endpoint: string): { component: string; pin: string } {
  if (!endpoint) return { component: '', pin: '' };
  const trimmed = endpoint.trim();

  // Handle compound module addresses with X-card identifiers:
  //   "AP602-EN101:X1.21"       → AP602-EN101, 21
  //   "AP601-ID101.X1:21"       → AP601-ID101, 21
  //   "AP601-OD102.DO-01/X1.11" → AP601-OD102, 11
  // Pattern: base component + anything + X-card separator + final pin
  const compoundMatch = trimmed.match(/^(-?[A-Za-z]+\d+(?:-[A-Za-z]+\d+)*)[.:\/].*?[.:\/]X\d+[.:]([\d.]+)$/);
  if (compoundMatch) {
    return { component: compoundMatch[1], pin: compoundMatch[2] };
  }

  // Simpler compound: "AP602-EN101:X1.21" (direct X-card after component)
  const simpleCompound = trimmed.match(/^(-?[A-Za-z]+\d+(?:-[A-Za-z]+\d+)*)[:.]X\d+[:.]([\d.]+)$/);
  if (simpleCompound) {
    return { component: simpleCompound[1], pin: simpleCompound[2] };
  }

  // Find first '.' or ':' separator
  const sepIdx = trimmed.search(/[.:]/);
  if (sepIdx <= 0) return { component: trimmed, pin: '' };

  const component = trimmed.slice(0, sepIdx);
  const pin = trimmed.slice(sepIdx + 1);

  // If pin contains nested component refs (vision artifact), extract just the final number
  // e.g., "KM838.11" → "11", "DO-01/X1.11" → "11"
  const finalNumMatch = pin.match(/[.:\/]([\d.]+)$/);
  if (finalNumMatch && /[A-Za-z]/.test(pin)) {
    return { component, pin: finalNumMatch[1] };
  }

  return { component, pin };
}

/**
 * Estrae il riferimento base del componente (senza pin/terminale)
 */
function extractComponentBase(endpoint: string): string {
  // Handle formats like "QM102.13", "QM102:13", "-QM102.13", "XT3.24.1"
  const cleaned = endpoint.replace(/^-/, '').trim();
  // Match component reference (letters + numbers) before separator
  const match = cleaned.match(/^([A-Za-z]+\d+)/);
  return match ? match[1] : cleaned;
}

/**
 * Costruisce il grafo visuale dello schema elettrico dai fili estratti
 */
function buildSchemaGraph(wires: WireRecord[], components: ComponentRecord[]): SchemaGraph {
  const nodesMap = new Map<string, SchemaGraphNode>();
  const edges: SchemaGraphEdge[] = [];

  // Add nodes from wires
  for (const wire of wires) {
    if (!wire.from || !wire.to) continue;

    // Extract component base references
    const fromBase = extractComponentBase(wire.from);
    const toBase = extractComponentBase(wire.to);

    // Add nodes if not already present
    if (!nodesMap.has(fromBase)) {
      nodesMap.set(fromBase, {
        id: fromBase,
        type: classifyComponentType(fromBase),
        label: fromBase,
        page: wire.page
      });
    }

    if (!nodesMap.has(toBase)) {
      nodesMap.set(toBase, {
        id: toBase,
        type: classifyComponentType(toBase),
        label: toBase,
        page: wire.page
      });
    }

    // Add edge
    edges.push({
      source: fromBase,
      target: toBase,
      wireId: wire.id || '',
      label: wire.id ? `Filo ${wire.id}` : ''
    });
  }

  // Enrich node labels with component descriptions if available
  for (const comp of components) {
    if (!comp.ref) continue;
    const baseRef = extractComponentBase(comp.ref);
    const node = nodesMap.get(baseRef);
    if (node && comp.description) {
      node.label = `${baseRef}\\n${comp.description.slice(0, 30)}`;
    }
  }

  return {
    nodes: Array.from(nodesMap.values()),
    edges
  };
}

/**
 * Genera il file DOT (Graphviz) dal grafo
 */
function generateDotGraph(graph: SchemaGraph): string {
  const lines: string[] = [
    'digraph ElectricalSchema {',
    '  rankdir=LR;',
    '  node [shape=box, style=filled, fontname="Arial"];',
    '  edge [fontname="Arial", fontsize=10];',
    ''
  ];

  // Add nodes
  for (const node of graph.nodes) {
    const color = COMPONENT_COLORS[node.type] || COMPONENT_COLORS.other;
    const label = node.label.replace(/"/g, '\\"');
    lines.push(`  "${node.id}" [label="${label}", fillcolor="${color}"];`);
  }

  lines.push('');

  // Add edges (deduplicate same source-target pairs)
  const edgeKeys = new Set<string>();
  for (const edge of graph.edges) {
    const key = `${edge.source}|${edge.target}|${edge.wireId}`;
    if (edgeKeys.has(key)) continue;
    edgeKeys.add(key);

    const label = edge.wireId || '';
    lines.push(`  "${edge.source}" -> "${edge.target}" [label="${label}"];`);
  }

  lines.push('}');
  return lines.join('\n');
}

/**
 * Genera il file JSON del grafo per visualizzazione web
 */
function generateJsonGraph(graph: SchemaGraph): string {
  return JSON.stringify({
    nodes: graph.nodes.map(n => ({
      id: n.id,
      type: n.type,
      label: n.label.replace(/\\n/g, '\n'),
      color: COMPONENT_COLORS[n.type] || COMPONENT_COLORS.other
    })),
    edges: graph.edges.map(e => ({
      source: e.source,
      target: e.target,
      wireId: e.wireId,
      label: e.label
    }))
  }, null, 2);
}

/**
 * Genera un file HTML standalone con visualizzazione D3.js interattiva
 */
function generateHtmlGraph(graph: SchemaGraph): string {
  const jsonData = JSON.stringify({
    nodes: graph.nodes.map(n => ({
      id: n.id,
      type: n.type,
      label: n.label.replace(/\\n/g, '\n'),
      color: COMPONENT_COLORS[n.type] || COMPONENT_COLORS.other
    })),
    links: graph.edges.map(e => ({
      source: e.source,
      target: e.target,
      wireId: e.wireId,
      label: e.label
    }))
  });

  return `<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Schema Elettrico - Grafo Interattivo</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; }
    #container { display: flex; height: 100vh; }
    #sidebar {
      width: 280px;
      background: #16213e;
      padding: 20px;
      overflow-y: auto;
      border-right: 1px solid #0f3460;
    }
    #graph { flex: 1; }
    h1 { font-size: 18px; margin-bottom: 20px; color: #e94560; }
    h2 { font-size: 14px; margin: 15px 0 10px; color: #0f4c75; }
    .legend-item {
      display: flex;
      align-items: center;
      margin: 5px 0;
      cursor: pointer;
      padding: 5px;
      border-radius: 4px;
    }
    .legend-item:hover { background: rgba(255,255,255,0.1); }
    .legend-color {
      width: 20px;
      height: 20px;
      border-radius: 3px;
      margin-right: 10px;
      border: 1px solid #333;
    }
    .legend-label { font-size: 12px; }
    #search {
      width: 100%;
      padding: 8px;
      margin-bottom: 15px;
      border: 1px solid #0f3460;
      border-radius: 4px;
      background: #1a1a2e;
      color: #eee;
    }
    #info {
      margin-top: 20px;
      padding: 10px;
      background: rgba(0,0,0,0.2);
      border-radius: 4px;
      font-size: 12px;
    }
    .node { cursor: pointer; }
    .node text { font-size: 11px; fill: #333; pointer-events: none; }
    .link { stroke: #999; stroke-opacity: 0.6; }
    .link-label { font-size: 9px; fill: #666; }
    .highlighted { stroke: #e94560; stroke-width: 3; }
    .dimmed { opacity: 0.2; }
  </style>
</head>
<body>
  <div id="container">
    <div id="sidebar">
      <h1>Schema Elettrico</h1>
      <input type="text" id="search" placeholder="Cerca componente o filo...">
      <h2>Legenda Componenti</h2>
      <div id="legend"></div>
      <div id="info">
        <strong>Istruzioni:</strong><br>
        • Trascina i nodi per riposizionarli<br>
        • Scroll per zoom<br>
        • Click su un nodo per evidenziare le connessioni<br>
        • Usa la ricerca per trovare componenti/fili
      </div>
    </div>
    <div id="graph"></div>
  </div>
  <script>
    const data = ${jsonData};

    const legendItems = {
      breaker: { label: 'Magnetotermici (QF/QM)', color: '#90EE90' },
      relay: { label: 'Relè/Contattori (K)', color: '#87CEEB' },
      power: { label: 'Alimentatori (TS/PS)', color: '#FFB6C1' },
      terminal: { label: 'Morsettiere (X/XT)', color: '#D3D3D3' },
      fuse: { label: 'Fusibili (FS/FU)', color: '#FFA500' },
      switch: { label: 'Pulsanti (S)', color: '#FFFF00' },
      lamp: { label: 'Lampade (H)', color: '#DDA0DD' },
      plc: { label: 'PLC/Moduli (AP)', color: '#00CED1' },
      motor: { label: 'Motori (M)', color: '#98FB98' },
      other: { label: 'Altri', color: '#FFFFFF' }
    };

    // Build legend
    const legendEl = document.getElementById('legend');
    const activeTypes = new Set(Object.keys(legendItems));

    Object.entries(legendItems).forEach(([type, info]) => {
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML = \`<div class="legend-color" style="background:\${info.color}"></div><span class="legend-label">\${info.label}</span>\`;
      item.onclick = () => {
        if (activeTypes.has(type)) {
          activeTypes.delete(type);
          item.style.opacity = 0.4;
        } else {
          activeTypes.add(type);
          item.style.opacity = 1;
        }
        updateVisibility();
      };
      legendEl.appendChild(item);
    });

    // Setup SVG
    const container = document.getElementById('graph');
    const width = container.clientWidth;
    const height = container.clientHeight;

    const svg = d3.select('#graph')
      .append('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .attr('viewBox', [0, 0, width, height]);

    const g = svg.append('g');

    // Zoom behavior
    const zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Arrow marker
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', '#999')
      .attr('d', 'M0,-5L10,0L0,5');

    // Force simulation
    const simulation = d3.forceSimulation(data.nodes)
      .force('link', d3.forceLink(data.links).id(d => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(50));

    // Links
    const link = g.append('g')
      .selectAll('line')
      .data(data.links)
      .join('line')
      .attr('class', 'link')
      .attr('stroke-width', 2)
      .attr('marker-end', 'url(#arrow)');

    // Link labels
    const linkLabel = g.append('g')
      .selectAll('text')
      .data(data.links)
      .join('text')
      .attr('class', 'link-label')
      .text(d => d.wireId);

    // Nodes
    const node = g.append('g')
      .selectAll('g')
      .data(data.nodes)
      .join('g')
      .attr('class', 'node')
      .call(d3.drag()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended));

    node.append('rect')
      .attr('width', 60)
      .attr('height', 30)
      .attr('x', -30)
      .attr('y', -15)
      .attr('rx', 4)
      .attr('fill', d => d.color)
      .attr('stroke', '#333')
      .attr('stroke-width', 1);

    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .text(d => d.id);

    // Tooltip
    node.append('title').text(d => d.label);

    // Click to highlight
    node.on('click', (event, d) => {
      const connected = new Set();
      connected.add(d.id);
      data.links.forEach(l => {
        if (l.source.id === d.id) connected.add(l.target.id);
        if (l.target.id === d.id) connected.add(l.source.id);
      });

      node.classed('dimmed', n => !connected.has(n.id));
      link.classed('dimmed', l => l.source.id !== d.id && l.target.id !== d.id);
      link.classed('highlighted', l => l.source.id === d.id || l.target.id === d.id);
    });

    svg.on('click', (event) => {
      if (event.target.tagName === 'svg') {
        node.classed('dimmed', false);
        link.classed('dimmed', false);
        link.classed('highlighted', false);
      }
    });

    // Search
    document.getElementById('search').addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase();
      if (!query) {
        node.classed('dimmed', false);
        link.classed('dimmed', false);
        return;
      }
      const matching = new Set();
      data.nodes.forEach(n => {
        if (n.id.toLowerCase().includes(query) || n.label.toLowerCase().includes(query)) {
          matching.add(n.id);
        }
      });
      data.links.forEach(l => {
        if (l.wireId && l.wireId.toLowerCase().includes(query)) {
          matching.add(l.source.id || l.source);
          matching.add(l.target.id || l.target);
        }
      });
      node.classed('dimmed', n => !matching.has(n.id));
      link.classed('dimmed', l => !matching.has(l.source.id) && !matching.has(l.target.id));
    });

    function updateVisibility() {
      node.classed('dimmed', n => !activeTypes.has(n.type));
    }

    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      linkLabel
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);

      node.attr('transform', d => \`translate(\${d.x},\${d.y})\`);
    });

    function dragstarted(event) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }
  </script>
</body>
</html>`;
}

/**
 * Normalizza e risolvi i fili estratti.
 * @param wires - Tutti i fili (panel + cross-panel). I fili del quadro target
 *   hanno la proprietà _panel=true; quelli cross-panel no.
 * @param hasCrossPanel - Se true, i fili includono dati cross-panel e il filtro
 *   post-risoluzione terrà solo fili con almeno un endpoint dal quadro target.
 */
function normalizeWires(wires: WireRecord[], hasCrossPanel?: boolean): { wires: WireRecord[]; warnings: string[] } {
  const normWarnings: string[] = [];
  const scored = (wire: WireRecord): number => {
    const fields: (keyof WireRecord)[] = [
      'id',
      'from',
      'to',
      'cable',
      'gauge',
      'color',
      'length_mm',
      'terminal_a',
      'terminal_b',
      'note'
    ];
    return fields.reduce<number>((acc, field) => {
      const val = wire[field];
      if (typeof val === 'string') return acc + (val.trim() ? 1 : 0);
      if (typeof val === 'number') return acc + (Number.isFinite(val) ? 1 : 0);
      return acc;
    }, 0);
  };

  const normalized = wires
    .map(w => {
    const updated: WireRecord = { ...w };

    // Pattern tipo "105.8 / 24" o "108.8/L1" -> sezione = numero, ID = resto
    if (typeof updated.id === 'string') {
      const match = updated.id.match(/^\\s*(\\d+(?:\\.\\d+)?)\\s*[\\/\\\\]\\s*([A-Za-z0-9_.-]+)\\s*$/);
      if (match) {
        const [, gaugeVal, idVal] = match;
        if (!updated.gauge) updated.gauge = gaugeVal;
        updated.id = idVal;
      }
    }

    if (typeof updated.id === 'string') {
      updated.id = updated.id.trim();
    }
    if (typeof updated.from === 'string') {
      updated.from = updated.from.trim();
    }
    if (typeof updated.to === 'string') {
      updated.to = updated.to.trim();
    }
    if (typeof updated.cable === 'string') {
      updated.cable = updated.cable.trim();
    }
    if (typeof updated.color === 'string') {
      updated.color = updated.color.trim();
    }
    if (typeof updated.gauge === 'number') {
      updated.gauge = String(updated.gauge);
    }

    // Se un capo è solo numerico (rimando pagina/coord) e l'altro no, etichetta come "rimando <valore>" per non scartarlo
    const fromMark = markRimandoEndpoint(updated.from, updated.note);
    updated.from = fromMark.endpoint;
    updated.note = fromMark.note;
    const toMark = markRimandoEndpoint(updated.to, updated.note);
    updated.to = toMark.endpoint;
    updated.note = toMark.note;

    updated.gauge = sanitizeGaugeValue(updated.gauge);
    updated.length_mm = sanitizeLengthValue(updated.length_mm);

    return updated;
  });

  const filtered = normalized
    // Escludi fili marcati come cavo o fasi
    .filter(w => !shouldDropWireId(typeof w.id === 'string' ? w.id : undefined))
    // Scarta fili senza estremi o senza ID leggibile
    .filter(w => {
      const hasId = typeof w.id === 'string' && w.id.trim().length > 0;
      const hasFrom = typeof w.from === 'string' && w.from.trim().length > 0;
      const hasTo = typeof w.to === 'string' && w.to.trim().length > 0;
      return hasId && hasFrom && hasTo;
    })
    // Ignora fili con entrambi gli estremi solo coordinate numeriche (posizionamenti, non sigle)
    .filter(w => !(isNumericCoordinate(w.from) && isNumericCoordinate(w.to)));

  // Correzione mislettura morsettiere: "XT2" → "XT12" se entrambi compaiono nei dati.
  // La visione spesso tronca il nome leggendo solo l'ultima cifra.
  const xtNames = new Set<string>();
  for (const w of filtered) {
    for (const ep of [w.from, w.to]) {
      const m = (ep || '').match(/^-?(XT\d+)/i);
      if (m) xtNames.add(m[1].toUpperCase());
    }
  }
  const xtCorrections = new Map<string, string>();
  for (const name of xtNames) {
    const shortDigits = name.slice(2); // e.g., "2" from "XT2"
    // Check if a longer XT name exists where the short number is a trailing portion
    // and exactly one leading digit was dropped (e.g., XT2 → XT12, XT6 → XT16)
    for (const longer of xtNames) {
      if (longer === name) continue;
      const longDigits = longer.slice(2); // e.g., "12" from "XT12"
      if (longDigits.endsWith(shortDigits) && longDigits.length === shortDigits.length + 1) {
        xtCorrections.set(name, longer);
        log(`[normalizeWires] Correzione morsettiera: ${name} → ${longer} (probabile mislettura cifra iniziale)`);
        break;
      }
    }
  }
  if (xtCorrections.size > 0) {
    for (const w of filtered) {
      for (const field of ['from', 'to'] as const) {
        const ep = w[field] || '';
        const m = ep.match(/^(-?)(XT\d+)(.*)/i);
        if (m) {
          const key = m[2].toUpperCase();
          const replacement = xtCorrections.get(key);
          if (replacement) {
            w[field] = `${m[1]}${replacement}${m[3]}`;
          }
        }
      }
    }
    normWarnings.push(`Correzione automatica morsettiere: ${[...xtCorrections.entries()].map(([k, v]) => `${k}→${v}`).join(', ')}`);
  }

  // Dedup: tiles/zoom can cause repeats; keep the best-populated row
  // IMPORTANTE: NON ordinare from/to e NON includere page nella chiave
  // Questo permette di mantenere connessioni distinte per fili comuni (es. filo "24" a più componenti)
  // e di fare merge cross-page dello stesso segmento di filo
  const deduped = new Map<string, WireRecord>();
  for (const wire of filtered) {
    const id = typeof wire.id === 'string' ? wire.id.trim() : '';
    const from = typeof wire.from === 'string' ? wire.from.trim() : '';
    const to = typeof wire.to === 'string' ? wire.to.trim() : '';
    // Chiave: id|from|to - mantiene direzione e permette fili comuni a destinazioni diverse
    const key = `${id}|${from}|${to}`;

    const existing = deduped.get(key);
    if (!existing) {
      deduped.set(key, wire);
      continue;
    }

    const mergedNote = [existing.note, wire.note].filter(Boolean).join(' | ');
    const candidate = scored(wire) > scored(existing) ? { ...wire } : { ...existing };
    if (mergedNote) candidate.note = mergedNote;
    deduped.set(key, candidate);
  }

  const sanitizedWires = Array.from(deduped.values());

  // Costruisci set di endpoint appartenenti al quadro target (per filtro cross-panel).
  // Usa i fili normalizzati/sanitizzati che hanno il tag _panel=true.
  // Solo endpoint NON-rimando vanno nel set (i rimandi vengono risolti nel grafo).
  let panelEndpoints: Set<string> | undefined;
  if (hasCrossPanel) {
    panelEndpoints = new Set<string>();
    for (const w of sanitizedWires) {
      if (!(w as any)._panel) continue;
      const from = (w.from || '').trim().toLowerCase();
      const to = (w.to || '').trim().toLowerCase();
      if (from && !from.startsWith('rimando')) panelEndpoints.add(from);
      if (to && !to.startsWith('rimando')) panelEndpoints.add(to);
    }
    log(`[wire-graph] Panel endpoint set: ${panelEndpoints.size} endpoint unici dal quadro target`);
  }

  // ============================================================
  // Wire Graph Resolution - Traccia fili attraverso i rimandi
  // ============================================================

  // Separa fili completi (senza rimandi) da quelli con rimandi
  const hasRimando = (w: WireRecord): boolean => {
    const from = w.from?.toLowerCase() || '';
    const to = w.to?.toLowerCase() || '';
    return from.includes('rimando') || to.includes('rimando');
  };

  const completeWires = sanitizedWires.filter(w => !hasRimando(w));
  const wiresWithRimandi = sanitizedWires.filter(w => hasRimando(w));

  // Se ci sono fili con rimandi, costruisci il grafo e risolvi le connessioni
  if (wiresWithRimandi.length > 0) {
    // Include TUTTI i fili nel grafo (anche quelli completi) per costruire le connessioni
    const graphs = buildWireGraph(sanitizedWires);
    const resolved = resolveWireConnections(graphs);

    // Rileva rimandi non risolti (fili con rimandi che non hanno prodotto connessioni risolte)
    const resolvedWireIds = new Set(resolved.map(w => w.id));
    for (const wire of wiresWithRimandi) {
      const wireId = wire.id?.trim() || '';
      if (!resolvedWireIds.has(wireId)) {
        const from = wire.from || '?';
        const to = wire.to || '?';
        const msg = `Filo "${wireId}" (da ${from} a ${to}, pagina ${wire.page ?? '?'}): rimando non risolto - connessione cross-pagina incompleta`;
        normWarnings.push(msg);
        log(`[wire-graph] WARN: ${msg}`);
      }
    }

    // Dedup finale: combina fili già completi con quelli risolti
    const finalDedup = new Map<string, WireRecord>();

    // Prima aggiungi i fili completi (priorità)
    for (const wire of completeWires) {
      const key = `${wire.id}|${wire.from}|${wire.to}`;
      finalDedup.set(key, wire);
    }

    // Poi aggiungi i fili risolti (se non già presenti)
    for (const wire of resolved) {
      const key = `${wire.id}|${wire.from}|${wire.to}`;
      const reverseKey = `${wire.id}|${wire.to}|${wire.from}`;
      if (!finalDedup.has(key) && !finalDedup.has(reverseKey)) {
        finalDedup.set(key, wire);
      }
    }

    log(`[wire-graph] Input: ${sanitizedWires.length} fili, Completi: ${completeWires.length}, Con rimandi: ${wiresWithRimandi.length}, Risolti: ${resolved.length}, Output: ${finalDedup.size}`);

    let finalWires = Array.from(finalDedup.values());

    // Filtra fili cross-panel: mantieni solo quelli con almeno un endpoint nel quadro target
    if (panelEndpoints) {
      const beforeCount = finalWires.length;
      finalWires = finalWires.filter(w => {
        const from = (w.from || '').trim().toLowerCase();
        const to = (w.to || '').trim().toLowerCase();
        return panelEndpoints!.has(from) || panelEndpoints!.has(to);
      });
      const crossPanelResolved = beforeCount - finalWires.length;
      if (crossPanelResolved > 0) {
        log(`[wire-graph] Filtro cross-panel: ${crossPanelResolved} fili di altri quadri rimossi, ${finalWires.length} fili del quadro target mantenuti`);
      }
    }

    return { wires: finalWires, warnings: normWarnings };
  }

  // Nessun rimando da risolvere - filtra cross-panel se necessario
  let result = sanitizedWires;
  if (panelEndpoints) {
    result = sanitizedWires.filter(w => {
      const from = (w.from || '').trim().toLowerCase();
      const to = (w.to || '').trim().toLowerCase();
      return panelEndpoints!.has(from) || panelEndpoints!.has(to);
    });
  }
  return { wires: result, warnings: normWarnings };
}

function normalizeComponents(components: ComponentRecord[]): ComponentRecord[] {
  const normalized = components
    // Filtra componenti evidentemente errati: ref solo numerico/decimale senza descrizione
    .filter(c => {
      if (!c) return false;
      const ref = typeof c.ref === 'string' ? c.ref.trim() : '';
      const desc = typeof c.description === 'string' ? c.description.trim() : '';
      const gaugeLike = ref !== '' && /^-?\\d+(?:\\.\\d+)?$/.test(ref);
      if (gaugeLike && desc === '') {
        return false; // scarta ref che sono solo numeri/gauge senza descrizione
      }
      return true;
    })
    .map(c => {
      const updated: ComponentRecord = { ...c };
      if (typeof updated.ref === 'string') {
        // Esempio "-QM102/1" o "QM104:1" -> ref = QM102, terminale in note
        const refMatch = updated.ref.match(/^(-?[A-Za-z0-9]+)([:\\/])(.*)$/);
        if (refMatch) {
          const [, base, , suffix] = refMatch;
          const suffixTrimmed = suffix.trim();
          updated.note = [updated.note, `terminale/suffisso: ${suffixTrimmed}`].filter(Boolean).join(' | ');
          updated.ref = base;
        }
      }
      return updated;
    });

  const deduped = new Map<string, ComponentRecord>();
  for (const comp of normalized) {
    const ref = typeof comp.ref === 'string' ? comp.ref.trim() : '';
    if (!ref) continue;

    const existing = deduped.get(ref);
    if (!existing) {
      deduped.set(ref, comp);
      continue;
    }

    const merged: ComponentRecord = { ...existing };
    const existingDesc = typeof existing.description === 'string' ? existing.description.trim() : '';
    const newDesc = typeof comp.description === 'string' ? comp.description.trim() : '';
    if (!existingDesc && newDesc) merged.description = newDesc;

    const existingQty = typeof existing.quantity === 'number' ? existing.quantity : undefined;
    const newQty = typeof comp.quantity === 'number' ? comp.quantity : undefined;
    if (existingQty !== undefined && newQty !== undefined) merged.quantity = existingQty + newQty;
    else if (existingQty === undefined && newQty !== undefined) merged.quantity = newQty;

    const existingWires = Array.isArray(existing.wires) ? existing.wires : [];
    const newWires = Array.isArray(comp.wires) ? comp.wires : [];
    const mergedWires = Array.from(new Set([...existingWires, ...newWires].map(w => String(w).trim()).filter(Boolean)));
    if (mergedWires.length) merged.wires = mergedWires;

    const existingNote = typeof existing.note === 'string' ? existing.note.trim() : '';
    const newNote = typeof comp.note === 'string' ? comp.note.trim() : '';
    const mergedNote = [existingNote, newNote].filter(Boolean).join(' | ');
    if (mergedNote) merged.note = mergedNote;

    const existingPage = typeof existing.page === 'number' ? existing.page : undefined;
    const newPage = typeof comp.page === 'number' ? comp.page : undefined;
    if (existingPage === undefined && newPage !== undefined) merged.page = newPage;

    deduped.set(ref, merged);
  }

  return Array.from(deduped.values());
}

async function runBatchPool<T>(items: T[], limit: number, worker: (item: T, index: number, total: number) => Promise<void>) {
  let index = 0;
  const total = items.length;
  const active = new Set<Promise<void>>();

  const startNext = () => {
    if (index >= total) return;
    const current = index++;
    const p = worker(items[current], current, total)
      .catch(err => {
        // Bubble up later
        throw err;
      })
      .finally(() => {
        active.delete(p);
      });
    active.add(p);
  };

  for (let i = 0; i < Math.min(limit, total); i++) {
    startNext();
  }

  while (active.size) {
    await Promise.race(active);
    startNext();
  }
}

export interface WireRecord {
  [key: string]: unknown;
  id?: string;
  from?: string;
  to?: string;
  cable?: string;
  gauge?: string;
  color?: string;
  length_mm?: number;
  terminal_a?: string;
  terminal_b?: string;
  note?: string;
  page?: number;
  foglio?: number;  // Sheet number from cartiglio (distinct from PDF page number)
}

export interface ComponentRecord {
  [key: string]: unknown;
  ref?: string;
  description?: string;
  quantity?: number;
  manufacturer?: string;
  part_number?: string;
  location?: string;
  note?: string;
  wires?: string[]; // ID fili o riferimenti collegati
  page?: number;
}

export interface ExtractionMetadata {
  source_file: string;
  panel_id?: string;
  pages_used?: number;
  text_chars?: number;
  truncated_text?: boolean;
  project?: string;
  note?: string;
  model?: string;
  extracted_at: string;
}

export interface ExtractionResult {
  output_excel_path: string;
  output_url: string;
  wires: number;
  components: number;
  warnings: string[];
  metadata: ExtractionMetadata;
  // Visual graph output paths (optional)
  graph_dot_path?: string;
  graph_json_path?: string;
  graph_html_path?: string;
  graph_html_url?: string;
}

// ============================================================
// Qwen3-VL Extraction via Ollama
// ============================================================

interface QwenExtractionResult {
  ubicazione: string;        // es. "+A1", "+P0", etc.
  foglio?: number;           // numero foglio dal cartiglio
  has_schema: boolean;       // true se pagina ha schema di principio
  wires: WireRecord[];
  components: ComponentRecord[];
  warnings: string[];
}

async function extractWithVision(
  imageBase64: string,
  pageNumber: number,
  debugFolder?: string
): Promise<QwenExtractionResult> {
  const model = getVisionModel();

  const prompt = `Analizza questa pagina di schema elettrico SACMI.

STEP 1: Leggi il CARTIGLIO (riquadro in basso a destra) e trova:
- "Ubicazione" o "Location" o "Yerleşim" → valore (es. "+A1", "+P0")
- "Foglio" o "Sheet" o "Kağıt" → numero pagina

STEP 2: Determina se la pagina contiene uno SCHEMA ELETTRICO da estrarre:
- SÌ schema (has_schema=true) = qualsiasi pagina con:
  • Numeri filo ROSSI (spesso barrati) come 24, 24.1, 1102, 1103
  • Sigle componenti (QM102, KA115E, XT1, AP601) con pin/terminali
  • Linee di connessione (solide O tratteggiate)
  • Include: schemi di potenza, schemi di comando, schemi consensi/segnali
- NON schema (has_schema=false) = pagine SENZA fili numerati rossi:
  • Copertina, indice, legenda
  • BOM/distinta materiali (tabelle senza connessioni)
  • Layout fisico/disposizione quadro (planimetrie)
  • Pagine solo testo o tabelle

CODIFICA COLORI nello schema:
- BLU: nomi/sigle dei componenti (QM102, KA115E, XT1, AP601)
- ROSSO: numeri dei fili (spesso con barra trasversale), es. 24, 1102, 2905
- VIOLA: note e annotazioni
- VERDE: rimandi a pagine/fogli (riferimenti incrociati)

STEP 3: Se has_schema=true, estrai:
- FILI: id (numero ROSSO barrato), from (componente.pin), to (componente.pin)
  - I numeri dei fili sono ROSSI e spesso BARRATI (barra trasversale)
  - from/to sono sigle componente BLU con pin (es. "QM376.2", "KM376.1", "-XT1.24")
  - Se un capo è un rimando pagina (VERDE), scrivi "rimando X.Y" (es. "rimando 134.8")
- COMPONENTI: ref (sigla BLU come QM376, KM376, XT1), description

IMPORTANTE:
- Estrai TUTTI i segmenti di filo, anche quelli con rimandi su entrambi i lati
- Se un filo si collega a PIÙ componenti, crea UNA RIGA SEPARATA per ogni connessione
- I componenti con prefisso "-" (es. -QM376) appartengono comunque al quadro indicato in Ubicazione
- Trasformatori amperometrici (TA): il filo di potenza PASSA ATTRAVERSO il TA ma NON è connesso elettricamente ad esso. Non creare connessioni filo-TA per il filo passante. Il TA ha i propri fili secondari separati (es. 2905)
- Morsettiere (XT): leggi TUTTE le cifre della sigla. Nomi come XT12, XT16 sono comuni - non confondere con XT1, XT2, XT6. Verifica attentamente ogni cifra

Rispondi SOLO in JSON valido:
{
  "ubicazione": "+A1",
  "foglio": 133,
  "has_schema": true,
  "wires": [{"id": "24", "from": "QM376.2", "to": "KM376.1", "page": ${pageNumber}}],
  "components": [{"ref": "QM376", "description": "Magnetotermico", "page": ${pageNumber}}],
  "warnings": []
}`;

  // Retry loop with exponential backoff for rate limiting
  for (let attempt = 1; attempt <= VISION_MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(`${OPENROUTER_BASE_URL}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${ensureApiKey()}`,
          'HTTP-Referer': 'https://intelligencebox.ai',
          'X-Title': 'IntelligenceBox Wirelist Extractor'
        },
        body: JSON.stringify({
          model,
          messages: [{
            role: 'user',
            content: [
              { type: 'text', text: prompt },
              {
                type: 'image_url',
                image_url: {
                  url: `data:image/png;base64,${imageBase64}`
                }
              }
            ]
          }],
          response_format: { type: 'json_object' }
        })
      });

      // Handle rate limiting - retry with backoff
      if (response.status === 503 || response.status === 429) {
        const waitMs = Math.pow(2, attempt) * 1000; // 2s, 4s, 8s
        log(`Pagina ${pageNumber}: rate limited (${response.status}), retry ${attempt}/${VISION_MAX_RETRIES} in ${waitMs / 1000}s...`);
        if (attempt < VISION_MAX_RETRIES) {
          await new Promise(r => setTimeout(r, waitMs));
          continue;
        }
        throw new Error(`OpenRouter rate limited (${response.status}) after ${VISION_MAX_RETRIES} retries`);
      }

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`OpenRouter returned ${response.status}: ${errorText}`);
      }

      const result = await response.json() as { choices?: Array<{ message?: { content?: string } }> };
      const content = result.choices?.[0]?.message?.content;

      if (!content) {
        return {
          ubicazione: '',
          has_schema: false,
          wires: [],
          components: [],
          warnings: [`Pagina ${pageNumber}: nessuna risposta da ${model}`]
        };
      }

      // Parse JSON response - handle potential markdown code blocks
      let jsonContent = content.trim();
      if (jsonContent.startsWith('```json')) {
        jsonContent = jsonContent.slice(7);
      } else if (jsonContent.startsWith('```')) {
        jsonContent = jsonContent.slice(3);
      }
      if (jsonContent.endsWith('```')) {
        jsonContent = jsonContent.slice(0, -3);
      }
      jsonContent = jsonContent.trim();

      const parsed = JSON.parse(jsonContent) as QwenExtractionResult;

      // Save debug output if folder specified
      if (debugFolder) {
        const paddedNum = String(pageNumber).padStart(4, '0');
        const jsonPath = path.join(debugFolder, `page-${paddedNum}-extraction.json`);
        await fs.writeFile(jsonPath, JSON.stringify({
          pageNumber,
          ubicazione: parsed.ubicazione,
          foglio: parsed.foglio,
          has_schema: parsed.has_schema,
          wires: parsed.wires || [],
          components: parsed.components || [],
          warnings: parsed.warnings || [],
          rawResponse: content
        }, null, 2));
      }

      return {
        ubicazione: parsed.ubicazione || '',
        foglio: parsed.foglio,
        has_schema: parsed.has_schema ?? false,
        wires: (parsed.wires || []).map(w => ({ ...w, page: pageNumber, foglio: parsed.foglio })),
        components: (parsed.components || []).map(c => ({ ...c, page: pageNumber })),
        warnings: parsed.warnings || []
      };

    } catch (error: any) {
      // Retry on fetch failures (network errors, connection refused, etc.)
      const isRetriable = error.message?.includes('fetch failed') ||
                          error.message?.includes('ECONNRESET') ||
                          error.message?.includes('ETIMEDOUT') ||
                          error.message?.includes('ECONNREFUSED');

      if (isRetriable && attempt < VISION_MAX_RETRIES) {
        const waitMs = Math.pow(2, attempt) * 1000;
        log(`Pagina ${pageNumber}: ${error.message}, retry ${attempt}/${VISION_MAX_RETRIES} in ${waitMs / 1000}s...`);
        await new Promise(r => setTimeout(r, waitMs));
        continue;
      }

      log(`Errore vision pagina ${pageNumber}: ${error.message}`);
      return {
        ubicazione: '',
        has_schema: false,
        wires: [],
        components: [],
        warnings: [`Pagina ${pageNumber}: errore ${model} - ${error.message}`]
      };
    }
  }

  // Should not reach here, but TypeScript needs a return
  return {
    ubicazione: '',
    has_schema: false,
    wires: [],
    components: [],
    warnings: [`Pagina ${pageNumber}: max retries exceeded`]
  };
}

/**
 * Verifica se l'ubicazione estratta corrisponde al panel_id richiesto
 * Normalizza rimuovendo prefissi +/- per match flessibile (A1 == +A1)
 */
function pageMatchesPanelId(ubicazione: string, panelId: string): boolean {
  if (!ubicazione || !panelId) return false;
  // Normalizza: rimuovi +/- iniziale, rimuovi spazi interni, uppercase
  // Handles "+ A1" == "+A1" == "A1"
  const normalize = (s: string) => s.replace(/[\s+\-]/g, '').toUpperCase();
  return normalize(ubicazione) === normalize(panelId);
}

async function commandExists(command: string): Promise<boolean> {
  try {
    await execFileAsync('which', [command]);
    return true;
  } catch {
    return false;
  }
}

async function extractPdfText(filePath: string): Promise<{ fullText: string; pageTexts: string[] }> {
  try {
    const buffer = await fs.readFile(filePath);
    log(`Lettura PDF ${filePath}`);
    const parser = new PDFParse({ data: buffer });
    const result = await parser.getText();
    const pages = Array.isArray((result as any).pages)
      ? (result as any).pages.map((p: any) => typeof p.text === 'string' ? p.text : '').filter(Boolean)
      : [];
    return {
      fullText: result.text || '',
      pageTexts: pages
    };
  } catch (error: any) {
    throw new Error(`PDF extraction failed: ${error.message}`);
  }
}

function getPdfRenderDpi(): number {
  const raw = process.env.PDF_RENDER_DPI || process.env.PDF_IMAGE_DPI;
  const parsed = raw ? Number(raw) : DEFAULT_PDF_RENDER_DPI;
  if (!Number.isFinite(parsed)) return DEFAULT_PDF_RENDER_DPI;
  return Math.min(600, Math.max(72, Math.round(parsed)));
}

function getPdfTileGrid(): number {
  const raw = process.env.PDF_RENDER_TILE_GRID || process.env.PDF_TILE_GRID;
  const parsed = raw ? Number(raw) : DEFAULT_PDF_TILE_GRID;
  if (!Number.isFinite(parsed)) return DEFAULT_PDF_TILE_GRID;
  const grid = Math.round(parsed);
  if (grid <= 1) return 1;
  return Math.min(4, Math.max(2, grid));
}

function readPngDimensions(buffer: Buffer): { width: number; height: number } | undefined {
  if (buffer.length < 24) return undefined;
  const signature = buffer.subarray(0, 8);
  const pngSig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (!signature.equals(pngSig)) return undefined;
  // IHDR chunk starts at byte 8; width/height at byte 16/20
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  if (!width || !height) return undefined;
  return { width, height };
}

interface PageZoomImage {
  image: string;
  label: string;
}

interface PageImageSet {
  full: string;
  zooms: PageZoomImage[];
}

function computeTileRects(params: { width: number; height: number; grid: number; overlapRatio?: number }): Array<{ x: number; y: number; w: number; h: number; label: string }> {
  const grid = Math.max(1, params.grid);
  const overlapRatio = params.overlapRatio ?? 0.06;
  if (grid === 1) return [];

  const tileW = Math.ceil(params.width / grid);
  const tileH = Math.ceil(params.height / grid);
  const overlapW = Math.max(0, Math.round(tileW * overlapRatio));
  const overlapH = Math.max(0, Math.round(tileH * overlapRatio));
  const rects: Array<{ x: number; y: number; w: number; h: number; label: string }> = [];

  for (let row = 0; row < grid; row++) {
    for (let col = 0; col < grid; col++) {
      const x0 = Math.max(0, col * tileW - (col > 0 ? overlapW : 0));
      const y0 = Math.max(0, row * tileH - (row > 0 ? overlapH : 0));
      const x1 = Math.min(params.width, (col + 1) * tileW + (col < grid - 1 ? overlapW : 0));
      const y1 = Math.min(params.height, (row + 1) * tileH + (row < grid - 1 ? overlapH : 0));
      const w = Math.max(1, x1 - x0);
      const h = Math.max(1, y1 - y0);
      rects.push({
        x: x0,
        y: y0,
        w,
        h,
        label: `Zoom tile r${row + 1}c${col + 1} (${grid}x${grid})`
      });
    }
  }

  return rects;
}

async function convertPdfToImageSets(filePath: string, startPage: number, endPage: number): Promise<PageImageSet[]> {
  const pageSets: PageImageSet[] = [];
  const hasPdftoppm = await commandExists('pdftoppm');
  if (!hasPdftoppm) {
    log('pdftoppm non trovato: impossibile convertire PDF in immagini');
    return pageSets;
  }

  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'wirelist-'));
  const prefix = path.join(tempDir, 'page');
  const first = Math.max(1, startPage);
  const last = Math.max(first, endPage);
  const totalPages = last - first + 1;
  const dpi = getPdfRenderDpi();
  const tileGrid = getPdfTileGrid();
  log(`Converto PDF in PNG (pagine ${first}-${last}, totale ${totalPages} pagine, ${dpi} DPI, tileGrid=${tileGrid})`);
  log(`Inizio conversione PDF... questo può richiedere diversi minuti per ${totalPages} pagine`);
  const conversionStart = Date.now();
  await execFileAsync('pdftoppm', ['-png', '-r', String(dpi), '-aa', 'yes', '-aaVector', 'yes', '-f', String(first), '-l', String(last), filePath, prefix]);
  const conversionTime = ((Date.now() - conversionStart) / 1000).toFixed(1);
  log(`Conversione PDF completata in ${conversionTime}s`);

  const files = (await fs.readdir(tempDir))
    .filter(name => name.endsWith('.png'))
    .sort((a, b) => {
      const aNum = Number(a.match(/-(\d+)\.png$/)?.[1] ?? 0);
      const bNum = Number(b.match(/-(\d+)\.png$/)?.[1] ?? 0);
      return aNum - bNum || a.localeCompare(b);
    });

  const pageNumbers: number[] = [];
  const pageDims: Array<{ width: number; height: number } | undefined> = [];

  for (const file of files) {
    const match = file.match(/-(\d+)\.png$/);
    const pageNum = match ? Number(match[1]) : undefined;
    if (!pageNum) continue;

    const data = await fs.readFile(path.join(tempDir, file));
    const dims = readPngDimensions(data);
    pageNumbers.push(pageNum);
    pageDims.push(dims);
    pageSets.push({ full: data.toString('base64'), zooms: [] });
  }

  if (tileGrid <= 1 || pageSets.length === 0) {
    return pageSets;
  }

  // Generate zoom tiles per page to help the model read small red wire IDs (often "barrati").
  const totalTiles = pageSets.length * tileGrid * tileGrid;
  log(`Generazione ${totalTiles} tile zoom (${tileGrid}x${tileGrid} per pagina)...`);
  const tileStart = Date.now();
  let tilesGenerated = 0;

  for (let i = 0; i < pageSets.length; i++) {
    const pageNum = pageNumbers[i];
    const dims = pageDims[i];
    if (!dims) continue;

    const rects = computeTileRects({ width: dims.width, height: dims.height, grid: tileGrid });
    for (let tileIndex = 0; tileIndex < rects.length; tileIndex++) {
      const rect = rects[tileIndex];
      const tilePrefix = path.join(tempDir, `tile-${String(pageNum).padStart(3, '0')}-${String(tileIndex + 1).padStart(2, '0')}`);
      await execFileAsync('pdftoppm', [
        '-png',
        '-singlefile',
        '-r',
        String(dpi),
        '-aa',
        'yes',
        '-aaVector',
        'yes',
        '-f',
        String(pageNum),
        '-l',
        String(pageNum),
        '-x',
        String(rect.x),
        '-y',
        String(rect.y),
        '-W',
        String(rect.w),
        '-H',
        String(rect.h),
        filePath,
        tilePrefix
      ]);

      const tilePath = `${tilePrefix}.png`;
      const tileData = await fs.readFile(tilePath);
      pageSets[i].zooms.push({ image: tileData.toString('base64'), label: rect.label });
      tilesGenerated++;

      // Log progress every 20 tiles or at completion
      if (tilesGenerated % 20 === 0 || tilesGenerated === totalTiles) {
        log(`Tile zoom: ${tilesGenerated}/${totalTiles} generati`);
      }
    }
  }

  const tileTime = ((Date.now() - tileStart) / 1000).toFixed(1);
  log(`Generazione tile completata in ${tileTime}s`);

  return pageSets;
}

async function loadImageAsBase64(filePath: string): Promise<string> {
  const buffer = await fs.readFile(filePath);
  return buffer.toString('base64');
}

function heuristicWireParse(text: string): WireRecord[] {
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const wires: WireRecord[] = [];

  for (const line of lines) {
    const match = line.match(/^([A-Za-z0-9._/-]+)\s+([A-Za-z0-9._/-]+)\s*(?:-|–|>)\s*([A-Za-z0-9._/-]+)/);
    if (match) {
      wires.push({
        id: match[1],
        from: match[2],
        to: match[3],
      });
    }
    if (wires.length >= 80) {
      break;
    }
  }

  return wires;
}

// Old GPT extraction function removed - now using extractWithVision() via OpenRouter

function buildTaglioFili(wires: WireRecord[]) {
  const aggregates = new Map<string, { cable?: string; gauge?: string; color?: string; total_mm: number; count: number }>();

  for (const wire of wires) {
    if (!wire.length_mm || Number.isNaN(wire.length_mm)) {
      continue;
    }
    const key = `${wire.cable || ''}|${wire.gauge || ''}|${wire.color || ''}`;
    if (!aggregates.has(key)) {
      aggregates.set(key, {
        cable: wire.cable,
        gauge: wire.gauge,
        color: wire.color,
        total_mm: 0,
        count: 0
      });
    }
    const agg = aggregates.get(key)!;
    agg.total_mm += wire.length_mm || 0;
    agg.count += 1;
  }

  return Array.from(aggregates.values()).map(row => ({
    'Cavo': row.cable || '',
    'Sezione': row.gauge || '',
    'Colore': row.color || '',
    'Lunghezza totale (mm)': Math.round(row.total_mm),
    'Numero pezzi': row.count
  }));
}

function buildSiglatura(wires: WireRecord[]) {
  const rows = wires.flatMap(wire => {
    const fromSplit = splitComponentPin(wire.from || '');
    const toSplit = splitComponentPin(wire.to || '');

    const head = wire.from ? [{
      'Componente': fromSplit.component,
      'PIN': fromSplit.pin,
      'Sigla': wire.from,
      'ID filo': wire.id || '',
      'Estremità': 'A',
      'Note': wire.note || ''
    }] : [];

    const tail = wire.to ? [{
      'Componente': toSplit.component,
      'PIN': toSplit.pin,
      'Sigla': wire.to,
      'ID filo': wire.id || '',
      'Estremità': 'B',
      'Note': wire.note || ''
    }] : [];

    return [...head, ...tail];
  });

  if (!rows.length) {
    rows.push({
      'Componente': '',
      'PIN': '',
      'Sigla': '',
      'ID filo': '',
      'Estremità': '',
      'Note': 'Nessun filo estratto'
    });
  }

  return rows;
}

async function buildWorkbook(params: {
  wires: WireRecord[];
  components: ComponentRecord[];
  metadata: ExtractionMetadata;
  rawText?: string;
  addRawTextSheet: boolean;
  outputPath: string;
}): Promise<void> {
  const workbook = XLSX.utils.book_new();

  const wireRows = (params.wires.length ? params.wires : [{}]).map(wire => {
    const fromSplit = splitComponentPin(wire.from || '');
    const toSplit = splitComponentPin(wire.to || '');
    return {
      'ID': wire.id || '',
      'Da': fromSplit.component,
      'PIN Da': fromSplit.pin,
      'DA INIZIO': fromSplit.pin ? `${fromSplit.component} | ${fromSplit.pin}` : fromSplit.component,
      'A': toSplit.component,
      'PIN A': toSplit.pin,
      'A FINE': toSplit.pin ? `${toSplit.component} | ${toSplit.pin}` : toSplit.component,
      'Cavo': wire.cable || '',
      'Sezione': wire.gauge || '',
      'Colore': wire.color || '',
      'Lunghezza (mm)': wire.length_mm ?? '',
      'Terminale A': wire.terminal_a || '',
      'Terminale B': wire.terminal_b || '',
      'Pagina': wire.page ?? '',
      'Note': wire.note || ''
    };
  });
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(wireRows, { header: [
      'ID', 'Da', 'PIN Da', 'DA INIZIO', 'A', 'PIN A', 'A FINE',
      'Cavo', 'Sezione', 'Colore',
      'Lunghezza (mm)', 'Terminale A', 'Terminale B', 'Pagina', 'Note'
    ] }),
    'LISTA FILI'
  );

  const componentRows = (params.components.length ? params.components : [{}]).map(comp => ({
    'Rif': comp.ref || '',
    'Descrizione': comp.description || '',
    'Quantità': comp.quantity ?? '',
    'Produttore': comp.manufacturer || '',
    'Codice': comp.part_number || '',
    'Posizione': comp.location || '',
    'Fili associati': Array.isArray(comp.wires) ? comp.wires.join(', ') : '',
    'Pagina': comp.page ?? '',
    'Note': comp.note || ''
  }));
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(componentRows, { header: [
      'Rif', 'Descrizione', 'Quantità', 'Produttore', 'Codice', 'Posizione', 'Fili associati', 'Pagina', 'Note'
    ] }),
    'DISTINTA'
  );

  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(buildSiglatura(params.wires)),
    'SIGLATURA'
  );

  const taglio = buildTaglioFili(params.wires);
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(taglio.length ? taglio : [{
      'Cavo': '',
      'Sezione': '',
      'Colore': '',
      'Lunghezza totale (mm)': '',
      'Numero pezzi': ''
    }]),
    'TAGLIO FILI'
  );

  if (params.addRawTextSheet && params.rawText) {
    const rawLines = params.rawText.split(/\r?\n/).map((line, idx) => ({
      Riga: idx + 1,
      Testo: line
    }));

    XLSX.utils.book_append_sheet(
      workbook,
      XLSX.utils.json_to_sheet(rawLines.length ? rawLines : [{ Riga: 1, Testo: '' }]),
      'RAW_TEXT'
    );
  }

  await fs.mkdir(path.dirname(params.outputPath), { recursive: true });
  XLSX.writeFile(workbook, params.outputPath);
}

export async function extractWirelistToExcel(input: ExtractWirelistInput): Promise<ExtractionResult> {
  const warnings: string[] = [];
  const resolvedPath = path.resolve(input.file_path);
  // Default output to mounted volume so files are accessible from host
  const defaultOutputDir = process.env.OUTPUT_DIR || '/dataai/outputs';
  const outputPath = path.resolve(
    input.output_excel_path || path.join(defaultOutputDir, `wirelist-${Date.now()}.xlsx`)
  );

  // Progress tracking context
  const progressCtx: ProgressContext = {
    invocationId: input.invocation_id,
    toolName: 'extract_wirelist'
  };

  await reportProgress(progressCtx, 0, 'Avvio estrazione wirelist...');

  const startPage = Math.max(1, input.start_page ?? 1);
  const maxPages = input.max_pages ?? Number(process.env.DEFAULT_MAX_PAGES || 300);
  const boundedMaxPages = Math.min(maxPages, 1000);
  const requestedEnd = input.end_page ? Math.max(input.end_page, startPage) : undefined;
  const endPage = requestedEnd
    ? Math.min(requestedEnd, startPage + boundedMaxPages - 1)
    : startPage + boundedMaxPages - 1;
  const useVision = input.use_vision ?? true;

  let rawText = '';
  let pageTexts: string[] = [];
  let imageSets: PageImageSet[] = [];
  const ext = path.extname(resolvedPath).toLowerCase();

  await reportProgress(progressCtx, 5, 'Lettura file sorgente...');

  try {
    if (ext === '.pdf') {
      await reportProgress(progressCtx, 8, 'Estrazione testo da PDF...');
      const pdfText = await extractPdfText(resolvedPath);
      const startIdx = Math.max(0, startPage - 1);
      const endIdx = Math.min(pdfText.pageTexts.length, endPage);
      pageTexts = pdfText.pageTexts.slice(startIdx, endIdx);
      rawText = pageTexts.length ? pageTexts.join('\n') : pdfText.fullText;
      if (startIdx >= pdfText.pageTexts.length && pdfText.pageTexts.length) {
        warnings.push(`start_page=${startPage} oltre il numero di pagine (${pdfText.pageTexts.length}).`);
      }

      if (useVision) {
        await reportProgress(progressCtx, 12, 'Conversione PDF in immagini...');
        imageSets = await convertPdfToImageSets(resolvedPath, startPage, endPage);
        await reportProgress(progressCtx, 20, `Convertite ${imageSets.length} pagine in immagini`);
        if (!imageSets.length) {
          warnings.push('Impossibile convertire il PDF in immagini: assicurati che poppler-utils/pdftoppm sia installato.');
        }
      } else if (!rawText || rawText.trim().length < 30) {
        warnings.push("PDF con poco testo e visione disattivata: l'estrazione potrebbe essere incompleta.");
      }
    } else if (['.png', '.jpg', '.jpeg', '.tiff', '.bmp'].includes(ext)) {
      await reportProgress(progressCtx, 10, 'Caricamento immagine...');
      imageSets = [{ full: await loadImageAsBase64(resolvedPath), zooms: [] }];
      warnings.push('File immagine: uso visione/LLM per estrazione.');
      await reportProgress(progressCtx, 20, 'Immagine caricata');
    } else {
      await reportProgress(progressCtx, 10, 'Lettura file testo...');
      rawText = await fs.readFile(resolvedPath, 'utf-8');
      await reportProgress(progressCtx, 20, 'File testo letto');
    }
  } catch (error: any) {
    await reportProgress(progressCtx, 0, `Errore lettura file: ${error.message}`, 'failed');
    throw new Error(`Impossibile leggere il file: ${error.message}`);
  }

  // textForModel removed - now using Qwen vision directly

  let wires: WireRecord[] = [];
  let components: ComponentRecord[] = [];
  // Wires from pages that don't match panel_id but have has_schema=true.
  // These are needed for cross-panel rimandi resolution (e.g., foglio 104 in panel "+"
  // that contains TA/FS components referenced by rimandi on +A1 pages).
  const crossPanelWires: WireRecord[] = [];

  await reportProgress(progressCtx, 22, 'Preparazione estrazione con modello AI...');

  // Create debug folder if specified
  let debugFolder: string | undefined;
  if (input.debug_output_folder) {
    debugFolder = path.resolve(input.debug_output_folder);
    await fs.mkdir(debugFolder, { recursive: true });
    log(`Debug output folder: ${debugFolder}`);

    // Save all page images immediately during extraction setup
    if (imageSets.length > 0) {
      log(`Saving ${imageSets.length} page images to debug folder...`);
      for (let i = 0; i < imageSets.length; i++) {
        const pageNum = startPage + i;
        const paddedNum = String(pageNum).padStart(4, '0');

        // Save full page image
        if (imageSets[i].full) {
          const imagePath = path.join(debugFolder, `page-${paddedNum}.png`);
          await fs.writeFile(imagePath, Buffer.from(imageSets[i].full, 'base64'));
        }

        // Save zoom tile images
        if (imageSets[i].zooms?.length) {
          for (let j = 0; j < imageSets[i].zooms.length; j++) {
            const tile = imageSets[i].zooms[j];
            const tilePath = path.join(debugFolder, `page-${paddedNum}-tile-${j + 1}.png`);
            await fs.writeFile(tilePath, Buffer.from(tile.image, 'base64'));
          }
        }

        // Log progress every 20 pages
        if ((i + 1) % 20 === 0 || i === imageSets.length - 1) {
          log(`Debug images saved: ${i + 1}/${imageSets.length}`);
        }
      }
      log(`All debug images saved to ${debugFolder}`);
    }
  }

  // ============================================================
  // Estrazione con Gemini via OpenRouter
  // ============================================================
  if (imageSets.length > 0) {
    const totalPages = imageSets.length;
    log(`Invio ${totalPages} pagine a ${OPENROUTER_MODEL} via OpenRouter (concorrenza ${VISION_CONCURRENCY})`);
    await reportProgress(progressCtx, 25, `Estrazione ${totalPages} pagine con Gemini Flash...`);

    let completedPages = 0;
    let skippedPages = 0;

    // Process pages with concurrency control
    const processPage = async (pageIndex: number): Promise<void> => {
      const pageNum = startPage + pageIndex;
      const imageBase64 = imageSets[pageIndex].full;

      if (!imageBase64) {
        warnings.push(`Pagina ${pageNum}: immagine mancante`);
        return;
      }

      try {
        const qwenResult = await extractWithVision(imageBase64, pageNum, debugFolder);

        // Filtro su tipo pagina (schema di principio)
        if (!qwenResult.has_schema) {
          log(`Pagina ${pageNum}: no schema di principio - SKIP`);
          skippedPages++;
          return;
        }

        const matchesPanel = !input.panel_id || pageMatchesPanelId(qwenResult.ubicazione, input.panel_id);

        if (!matchesPanel) {
          // Pagina di un altro quadro: salva SOLO fili con rimandi per la risoluzione cross-panel.
          // Fili completamente interni ad un altro quadro non servono.
          const relevantWires = qwenResult.wires.filter(w => {
            const from = (w.from || '').toLowerCase();
            const to = (w.to || '').toLowerCase();
            return from.includes('rimando') || to.includes('rimando');
          });
          if (relevantWires.length > 0) {
            crossPanelWires.push(...relevantWires);
            log(`Pagina ${pageNum}: ubicazione="${qwenResult.ubicazione}" ≠ "${input.panel_id}" - ${relevantWires.length}/${qwenResult.wires.length} fili con rimandi salvati per cross-panel`);
          } else {
            log(`Pagina ${pageNum}: ubicazione="${qwenResult.ubicazione}" ≠ "${input.panel_id}" - SKIP (nessun rimando)`);
          }
          skippedPages++;
          return;
        }

        // Avviso se foglio non leggibile dal cartiglio (i rimandi non potranno essere risolti)
        if (qwenResult.foglio === undefined || qwenResult.foglio === null) {
          const msg = `Pagina PDF ${pageNum}: impossibile leggere il numero foglio dal cartiglio. I rimandi da/verso questa pagina non saranno risolti.`;
          warnings.push(msg);
          log(msg);
        }

        // Accumula risultati del quadro target
        wires.push(...qwenResult.wires);
        components.push(...qwenResult.components);
        if (qwenResult.warnings.length) {
          warnings.push(...qwenResult.warnings);
        }

        log(`Pagina ${pageNum}: ubicazione="${qwenResult.ubicazione}" foglio=${qwenResult.foglio ?? 'n/d'} - ${qwenResult.wires.length} fili, ${qwenResult.components.length} componenti`);

      } catch (error: any) {
        warnings.push(`Pagina ${pageNum}: errore - ${error.message}`);
      }

      // Report progress
      completedPages++;
      const progress = 25 + Math.round((completedPages / totalPages) * 55);
      await reportProgress(progressCtx, progress, `Pagina ${completedPages}/${totalPages} - ${wires.length} fili, ${components.length} componenti (${skippedPages} skip)`);
    };

    // Run with concurrency pool
    await runBatchPool(
      imageSets.map((_, idx) => idx),
      VISION_CONCURRENCY,
      async (pageIndex) => {
        await processPage(pageIndex);
      }
    );

    log(`Estrazione completata: ${wires.length} fili, ${components.length} componenti, ${skippedPages} pagine saltate`);
    if (crossPanelWires.length > 0) {
      log(`Cross-panel: ${crossPanelWires.length} fili da altri quadri salvati per risoluzione rimandi`);
    }
  } else {
    warnings.push('Nessuna immagine disponibile per estrazione vision');
  }

  // Normalizzazioni post-process per ridurre nomi inventati/suffissi
  // Include cross-panel wires in the graph resolution so that rimandi pointing
  // to pages in other panels can be resolved. After resolution, the normalizeWires
  // function uses the panelWireCount to distinguish panel wires from cross-panel ones.
  await reportProgress(progressCtx, 82, 'Normalizzazione dati estratti...');
  // Tag panel wires for cross-panel filtering after graph resolution
  for (const w of wires) { (w as any)._panel = true; }
  const allWiresForResolution = [...wires, ...crossPanelWires];
  const wireResult = normalizeWires(allWiresForResolution, crossPanelWires.length > 0);
  wires = wireResult.wires;
  if (wireResult.warnings.length) {
    warnings.push(...wireResult.warnings);
  }
  components = normalizeComponents(components);

  if (!wires.length && rawText) {
    await reportProgress(progressCtx, 85, 'Tentativo estrazione euristica...');
    const heuristic = heuristicWireParse(rawText);
    if (heuristic.length) {
      warnings.push('Usata estrazione euristica di base perché il modello non ha restituito fili.');
      wires = heuristic;
    }
  }

  await reportProgress(progressCtx, 88, `Normalizzazione completata: ${wires.length} fili, ${components.length} componenti`);

  const pagesCount = imageSets.length || pageTexts.length || (rawText ? Math.max(1, endPage - startPage + 1) : undefined);

  const metadata: ExtractionMetadata = {
    source_file: resolvedPath,
    panel_id: input.panel_id,
    pages_used: pagesCount,
    text_chars: rawText.length,
    truncated_text: false,
    project: input.project,
    note: input.note,
    model: input.model || OPENROUTER_MODEL,
    extracted_at: new Date().toISOString()
  };

  await reportProgress(progressCtx, 90, 'Generazione file Excel...');

  await buildWorkbook({
    wires,
    components,
    metadata,
    rawText,
    addRawTextSheet: input.add_raw_text_sheet ?? true,
    outputPath
  });

  await reportProgress(progressCtx, 100, `Estrazione completata: ${wires.length} fili, ${components.length} componenti`, 'completed');

  // Visual graph generation (if requested)
  let graphDotPath: string | undefined;
  let graphJsonPath: string | undefined;
  let graphHtmlPath: string | undefined;
  let graphHtmlUrl: string | undefined;

  if (input.generate_graph && wires.length > 0) {
    await reportProgress(progressCtx, 95, 'Generazione grafo visuale...');

    const schemaGraph = buildSchemaGraph(wires, components);
    const format = input.graph_format || 'html';
    const basePath = outputPath.replace(/\.xlsx$/, '');

    // Generate DOT format
    if (format === 'dot' || format === 'all') {
      graphDotPath = `${basePath}-graph.dot`;
      const dotContent = generateDotGraph(schemaGraph);
      await fs.writeFile(graphDotPath, dotContent, 'utf-8');
      log(`Grafo DOT generato: ${graphDotPath}`);
    }

    // Generate JSON format
    if (format === 'json' || format === 'all') {
      graphJsonPath = `${basePath}-graph.json`;
      const jsonContent = generateJsonGraph(schemaGraph);
      await fs.writeFile(graphJsonPath, jsonContent, 'utf-8');
      log(`Grafo JSON generato: ${graphJsonPath}`);
    }

    // Generate HTML format (interactive D3.js visualization)
    if (format === 'html' || format === 'all') {
      graphHtmlPath = `${basePath}-graph.html`;
      const htmlContent = generateHtmlGraph(schemaGraph);
      await fs.writeFile(graphHtmlPath, htmlContent, 'utf-8');
      log(`Grafo HTML generato: ${graphHtmlPath}`);

      // Generate web-accessible URL
      graphHtmlUrl = graphHtmlPath
        .replace(/^\/dataai\//, '/files/')
        .replace(/^\/files\/dataai\//, '/files/');
    }

    log(`Grafo generato con ${schemaGraph.nodes.length} nodi e ${schemaGraph.edges.length} archi`);
  }

  // Return standardized paths for frontend URL resolution
  // output_excel_path: full container path (e.g., /dataai/outputs/wirelist-xxx.xlsx)
  // output_url: web-accessible relative path starting with /files/ (frontend will resolve to absolute URL)
  // The frontend's urlResolver.ts handles /files/... paths and converts them to absolute URLs
  const webPath = outputPath
    .replace(/^\/dataai\//, '/files/')
    .replace(/^\/files\/dataai\//, '/files/');

  return {
    output_excel_path: outputPath,
    output_url: webPath,
    wires: wires.length,
    components: components.length,
    warnings,
    metadata,
    graph_dot_path: graphDotPath,
    graph_json_path: graphJsonPath,
    graph_html_path: graphHtmlPath,
    graph_html_url: graphHtmlUrl
  };
}
