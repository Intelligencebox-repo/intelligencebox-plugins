import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import http from 'http';
import { promisify } from 'util';
import { execFile } from 'child_process';
import { PDFParse } from 'pdf-parse';
import OpenAI from 'openai';
import XLSX from 'xlsx';
import { ExtractWirelistInput } from './schema.js';

const execFileAsync = promisify(execFile);
const BATCH_PAGE_LIMIT = 1; // invia una pagina per richiesta
const BATCH_CONCURRENCY = 30; // concorrenza elevata (30 richieste massimo)
const DEFAULT_OPENAI_MODEL = 'gpt-5.2';
const DEFAULT_PDF_RENDER_DPI = 300;
const DEFAULT_PDF_TILE_GRID = 2; // 2x2 tiles by default to help read small red IDs

// Auto-detect environment: Docker uses box-server hostname, local dev uses 127.0.0.1
function getProgressWebhookUrl(): string {
  if (process.env.PROGRESS_WEBHOOK_URL) {
    // Replace localhost with 127.0.0.1 to avoid IPv6 issues
    return process.env.PROGRESS_WEBHOOK_URL.replace('localhost', '127.0.0.1');
  }
  // Detect Docker environment (DOCKER_ENV is set in docker-compose)
  const isDocker = process.env.DOCKER_ENV === 'true' ||
                   process.env.RUNNING_IN_DOCKER === 'true';
  return isDocker
    ? 'http://box-server:3001/api/mcp/progress'
    : 'http://127.0.0.1:3001/api/mcp/progress';
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

function previewArray<T extends Record<string, unknown>>(items: T[], keys: (keyof T)[], limit = 3): string {
  const slice = items.slice(0, limit);
  return slice.map(it => {
    const parts = keys.map(k => `${String(k)}=${it[k] ?? ''}`);
    return `{${parts.join(', ')}}`;
  }).join('; ');
}

function chunkArray<T>(arr: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

const PHASE_ONLY_IDS = new Set(['L1', 'L2', 'L3', 'N', 'PE', 'PEN']);

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

function normalizeWires(wires: WireRecord[]): WireRecord[] {
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

  // Dedup: tiles/zoom can cause repeats; keep the best-populated row
  const deduped = new Map<string, WireRecord>();
  for (const wire of filtered) {
    const id = typeof wire.id === 'string' ? wire.id.trim() : '';
    const from = typeof wire.from === 'string' ? wire.from.trim() : '';
    const to = typeof wire.to === 'string' ? wire.to.trim() : '';
    const page = wire.page ?? '';
    const endpoints = [from, to].sort((a, b) => a.localeCompare(b)).join('→');
    const key = `${id}|${endpoints}|${page}`;

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

  return Array.from(deduped.values());
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
}

interface ModelExtraction {
  wires?: WireRecord[];
  components?: ComponentRecord[];
  warnings?: string[];
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

function truncateForModel(text: string): { text: string; truncated: boolean } {
  // No truncation: keep the interface but always return the original text
  return { text, truncated: false };
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

interface PagePayload {
  pageImage?: string;
  pageZoomImages?: PageZoomImage[];
  pageText?: string;
  pageIndex: number;
  totalPages: number;
  pageNumber?: number;
  model?: string;
  project?: string;
}

async function extractWithModelBatch(params: {
  pages: PagePayload[];
  model?: string;
  project?: string;
}): Promise<ModelExtraction> {
  const model = params.model || process.env.OPENAI_MODEL || DEFAULT_OPENAI_MODEL;
  const client = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
    baseURL: process.env.OPENAI_BASE_URL
  });

  const content: OpenAI.Chat.Completions.ChatCompletionContentPart[] = [
    {
      type: 'text',
      text: [
        'Estrarre lista fili e componenti da uno schema elettrico seguendo le regole R26 (R1-R8: numeri fili rossi, frecce rosse, barre "\\\\", duplicazione per ganci, doppio elenco fili/componenti).',
        'Nota importante: i numeri dei fili sono spesso stampati in rosso e possono apparire "barrati" (una linea del filo rosso attraversa le cifre). Anche se barrati, vanno letti e usati come ID del filo.',
        'Ogni pagina può includere una immagine intera + più immagini "Zoom tile" della stessa pagina: usa i tile per leggere numeri piccoli (specialmente i numeri rossi barrati) e l\'immagine intera per il contesto.',
        'Stai ricevendo un batch di pagine (max 10). Indica per ogni riga il numero di pagina nel campo "page" riferito alla pagina originale.',
        'Salta pagine di esempio/legenda (spesso marcate "ESEMPIO") e ignora collegamenti/componenti tratteggiati o indicati come esterni/opzionali; non estrarre fili da quei tratti.',
        'Se un elemento è descritto su più pagine, accumula quantità e mantieni i riferimenti coerenti; non duplicare oggetti già contati.',
        'Per ogni filo imposta chiaramente il punto di partenza (`from`) e di arrivo (`to`) come sigle/morsetti/dispositivi.',
        'Per ogni componente aggiungi il campo "wires": array di ID o sigle dei fili collegati (se noti).',
        'Pattern importante: se trovi "105.8 / 24", l\'ID filo è "24" e la sezione/gauge è "105.8"; non creare nomi come "105.8_L1" o "L1".',
        'Per componenti come "-QM102/1" il riferimento è "QM102"; il suffisso "/1" va in note o nel terminale, non cambiare il nome in "L1".',
        'Sezione/gauge: inseriscila solo se appare in chiaro (es. "1,5 mm²", "2x4 mm2", AWG). Rimandi pagina/posizionamenti (es. 160.2, 108.8) NON sono sezioni: lascia vuote Sezione/Colore/Lunghezza se non esplicitate sul filo.',
        'Per i rimandi (es. "113.8 / 24.1" o frecce rosse con numeri di pagina): usa l\'ID filo (24.1) e metti come from/to il componente visibile; se il capo è solo un rimando di pagina, scrivi "rimando 113.8" (o simile) nel capo e nella nota per non perdere il collegamento.',
        'Non inventare nomi o suffissi: usa esattamente le sigle viste. Se un capo è solo una coordinata numerica (105.8, 157.4) o manca un capo, non inserire la riga.',
        'Escludi fili con ID che iniziano per "W" o ID solo di fase (L1/L2/L3/N/PE). NON creare ID con prefissi non visti o combinazioni gauge+fase (es. "106.8_L1").',
        'Non indovinare: se un dato non è leggibile o manca, lascia il campo vuoto/null. Non proporre ID o collegamenti ipotetici.',
        'Non aggiungere suffissi o prefissi mai visti nell\'immagine/testo. Riporta solo ciò che è visibile.',
        'I valori ammessi per ID/Ref devono apparire testualmente nell\'immagine o nel testo estratto; se non li trovi, lascia vuoto.',
        'Se un campo sembra ambiguo (es. testo tagliato), lascia vuoto invece di inventare.',
        'Attenzione: numeri come "134.8", "157.4" sono sezioni/quote dei cavi, NON codici componente: non creare componenti con ref numerici o solo decimali.',
        'Ogni filo deve avere sia `from` sia `to`: se non riesci a leggere almeno un capo, NON inserire la riga.',
        'Per i componenti, usa solo riferimenti leggibili; se non puoi associare fili credibili, lascia vuoto il campo wires o ometti la riga.',
        'Restituisci SOLO JSON con la struttura:',
        '{',
        '  "wires": [{ "id": string?, "from": string?, "to": string?, "cable": string?, "gauge": string?, "color": string?, "length_mm": number?, "terminal_a": string?, "terminal_b": string?, "note": string? }],',
        '  "components": [{ "ref": string?, "description": string, "quantity": number?, "manufacturer": string?, "part_number": string?, "location": string?, "note": string?, "wires": string[]? }],',
        '  "warnings": [string?]',
        '}',
        'Non inventare valori: lascia i campi vuoti se non sicuro. Lunghezze in millimetri se presenti. Evita testo narrativo.'
      ].join('\n')
    }
  ];

  if (params.project) {
    content.push({
      type: 'text',
      text: `Commessa/Progetto: ${params.project}`
    });
  }

  params.pages.forEach(page => {
    const pageLabel = page.pageNumber ?? (page.pageIndex + 1);
    const slotLabel = `${page.pageIndex + 1}/${page.totalPages}`;
    content.push({
      type: 'text',
      text: `Pagina originale ${pageLabel} (slot ${slotLabel})`
    });

    if (page.pageText) {
      content.push({
        type: 'text',
        text: `Testo pagina ${pageLabel}:\n${page.pageText}`
      });
    }

    if (page.pageImage) {
      content.push({
        type: 'text',
        text: `Immagine pagina intera ${pageLabel} (contesto)`
      });
      content.push({
        type: 'image_url',
        image_url: {
          url: `data:image/png;base64,${page.pageImage}`,
          detail: 'high'
        }
      });
    }

    if (page.pageZoomImages?.length) {
      page.pageZoomImages.forEach((tile, tileIdx) => {
        content.push({
          type: 'text',
          text: `Zoom ${tileIdx + 1}/${page.pageZoomImages!.length} - ${tile.label}`
        });
        content.push({
          type: 'image_url',
          image_url: {
            url: `data:image/png;base64,${tile.image}`,
            detail: 'high'
          }
        });
      });
    }
  });

  const result = await client.chat.completions.create({
    model,
    temperature: 0.2,
    messages: [
      { role: 'system', content: 'Sei un assistente tecnico che restituisce solo JSON valido.' },
      { role: 'user', content }
    ],
    response_format: { type: 'json_object' }
  });

  const raw = result.choices?.[0]?.message?.content;
  if (!raw) {
    log(`Batch: nessuna risposta dal modello`);
    return { warnings: ['Nessuna risposta dal modello.'] };
  }

  try {
    const parsed = JSON.parse(raw) as ModelExtraction;
    return parsed;
  } catch (error: any) {
    return {
      warnings: [`Impossibile parsare JSON del modello: ${error.message}`]
    };
  }
}

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
    const head = wire.from ? [{
      'Sigla': wire.from,
      'ID filo': wire.id || '',
      'Estremità': 'A',
      'Note': wire.note || ''
    }] : [];

    const tail = wire.to ? [{
      'Sigla': wire.to,
      'ID filo': wire.id || '',
      'Estremità': 'B',
      'Note': wire.note || ''
    }] : [];

    return [...head, ...tail];
  });

  if (!rows.length) {
    rows.push({
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

  const indicazioni = [
    { Campo: 'Sorgente', Valore: params.metadata.source_file },
    { Campo: 'Progetto', Valore: params.metadata.project || 'n/d' },
    { Campo: 'Note', Valore: params.metadata.note || 'n/d' },
    { Campo: 'Pagine analizzate', Valore: params.metadata.pages_used ?? 'n/d' },
    { Campo: 'Caratteri testo', Valore: params.metadata.text_chars ?? 'n/d' },
    { Campo: 'Testo troncato', Valore: params.metadata.truncated_text ? 'sì' : 'no' },
    { Campo: 'Modello', Valore: params.metadata.model || DEFAULT_OPENAI_MODEL },
    { Campo: 'Estratto il', Valore: params.metadata.extracted_at }
  ];
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(indicazioni),
    'INDICAZIONI'
  );

  const wireRows = (params.wires.length ? params.wires : [{}]).map(wire => ({
    'ID': wire.id || '',
    'Da': wire.from || '',
    'A': wire.to || '',
    'Cavo': wire.cable || '',
    'Sezione': wire.gauge || '',
    'Colore': wire.color || '',
    'Lunghezza (mm)': wire.length_mm ?? '',
    'Terminale A': wire.terminal_a || '',
    'Terminale B': wire.terminal_b || '',
    'Pagina': wire.page ?? '',
    'Note': wire.note || ''
  }));
  XLSX.utils.book_append_sheet(
    workbook,
    XLSX.utils.json_to_sheet(wireRows, { header: [
      'ID', 'Da', 'A', 'Cavo', 'Sezione', 'Colore',
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

  const { text: textForModel } = truncateForModel(rawText);
  // No truncation applied; truncated is always false

  let wires: WireRecord[] = [];
  let components: ComponentRecord[] = [];

  await reportProgress(progressCtx, 22, 'Preparazione estrazione con modello AI...');

  if (process.env.OPENAI_API_KEY) {
    try {
      const textualPages = pageTexts.length ? pageTexts : [textForModel];
      const pageItems = imageSets.length
        ? imageSets.map((set, i) => ({
            pageImage: set.full,
            pageZoomImages: set.zooms,
            pageText: textualPages[i] ?? textForModel,
            pageIndex: i,
            totalPages: imageSets.length,
            pageNumber: startPage + i,
            model: input.model,
            project: input.project
          }))
        : textualPages.map((text, i) => ({
            pageText: text,
            pageIndex: i,
            totalPages: textualPages.length,
            pageNumber: startPage + i,
            model: input.model,
            project: input.project
          }));

      const batches = chunkArray(pageItems, BATCH_PAGE_LIMIT);
      log(`Invio ${pageItems.length} pagine al modello in ${batches.length} batch (max ${BATCH_PAGE_LIMIT} per richiesta, concorrenza ${BATCH_CONCURRENCY})`);
      await reportProgress(progressCtx, 25, `Invio ${pageItems.length} pagine in ${batches.length} batch...`);

      let completedBatches = 0;
      const processBatch = async (batch: typeof pageItems, batchIndex: number, totalBatches: number) => {
        const preparedPages = batch.map(p => {
          const textToUse = p.pageText || textForModel;
          const { text: truncatedText } = truncateForModel(textToUse);
          return {
            ...p,
            pageText: truncatedText
          };
        });

        const batchResult = await extractWithModelBatch({
          pages: preparedPages,
          model: input.model,
          project: input.project
        });

        if (batchResult.warnings?.length) {
          warnings.push(...batchResult.warnings.map(w => `Batch ${batchIndex + 1}: ${w}`));
        }

        wires.push(...(batchResult.wires || []));
        components.push(...(batchResult.components || []));

        log(`[batch ${batchIndex + 1}/${totalBatches}] fili estratti=${batchResult.wires?.length || 0} preview=${previewArray(batchResult.wires || [], ['id', 'from', 'to'])}`);
        log(`[batch ${batchIndex + 1}/${totalBatches}] componenti estratti=${batchResult.components?.length || 0} preview=${previewArray(batchResult.components || [], ['ref', 'description', 'wires'])}`);

        // Report batch progress (25% to 80% range for batch processing)
        completedBatches++;
        const batchProgress = 25 + Math.round((completedBatches / totalBatches) * 55);
        await reportProgress(progressCtx, batchProgress, `Batch ${completedBatches}/${totalBatches} completato - ${wires.length} fili, ${components.length} componenti`);
      };

      await runBatchPool(batches, BATCH_CONCURRENCY, async (batch, idx) => {
        await processBatch(batch, idx, batches.length);
      });
    } catch (error: any) {
      warnings.push(`Errore chiamando il modello: ${error.message}`);
    }
  } else {
    warnings.push('OPENAI_API_KEY assente: estrazione automatica disattivata.');
  }

  // Normalizzazioni post-process per ridurre nomi inventati/suffissi
  await reportProgress(progressCtx, 82, 'Normalizzazione dati estratti...');
  wires = normalizeWires(wires);
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
    pages_used: pagesCount,
    text_chars: rawText.length,
    truncated_text: false,
    project: input.project,
    note: input.note,
    model: input.model || process.env.OPENAI_MODEL || DEFAULT_OPENAI_MODEL,
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
    metadata
  };
}
