import fs from 'fs/promises';
import path from 'path';
import os from 'os';
import { promisify } from 'util';
import { execFile } from 'child_process';
import { PDFParse } from 'pdf-parse';
import OpenAI from 'openai';
import XLSX from 'xlsx';
import { ExtractWirelistInput } from './schema.js';

const execFileAsync = promisify(execFile);
const MAX_TEXT_FOR_MODEL = 12000;
const BATCH_PAGE_LIMIT = 1; // invia una pagina per richiesta
const BATCH_CONCURRENCY = 30; // concorrenza elevata (30 richieste massimo)

function log(message: string): void {
  process.stderr.write(`[wirelist] ${message}\n`);
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
  return wires
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

    updated.gauge = sanitizeGaugeValue(updated.gauge);
    updated.length_mm = sanitizeLengthValue(updated.length_mm);

    return updated;
  })
  // Escludi fili marcati come cavo o fasi
  .filter(w => !shouldDropWireId(typeof w.id === 'string' ? w.id : undefined))
  // Scarta fili senza estremi o senza ID leggibile
  .filter(w => {
    const hasId = typeof w.id === 'string' && w.id.trim().length > 0;
    const hasFrom = typeof w.from === 'string' && w.from.trim().length > 0;
    const hasTo = typeof w.to === 'string' && w.to.trim().length > 0;
    return hasId && hasFrom && hasTo;
  })
  // Ignora fili con estremi che sono solo coordinate numeriche (posizionamenti, non sigle)
  .filter(w => !isNumericCoordinate(w.from) && !isNumericCoordinate(w.to));
}

function normalizeComponents(components: ComponentRecord[]): ComponentRecord[] {
  return components
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

async function convertPdfToImages(filePath: string, startPage: number, endPage: number): Promise<string[]> {
  const images: string[] = [];
  const hasPdftoppm = await commandExists('pdftoppm');
  if (!hasPdftoppm) {
    log('pdftoppm non trovato: impossibile convertire PDF in immagini');
    return images;
  }

  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'wirelist-'));
  const prefix = path.join(tempDir, 'page');
  const first = Math.max(1, startPage);
  const last = Math.max(first, endPage);
  log(`Converto PDF in PNG (pagine ${first}-${last})`);
  await execFileAsync('pdftoppm', ['-png', '-f', String(first), '-l', String(last), filePath, prefix]);

  const files = (await fs.readdir(tempDir)).filter(name => name.endsWith('.png')).sort();
  for (const file of files) {
    const data = await fs.readFile(path.join(tempDir, file));
    images.push(data.toString('base64'));
  }

  return images;
}

async function loadImageAsBase64(filePath: string): Promise<string> {
  const buffer = await fs.readFile(filePath);
  return buffer.toString('base64');
}

function truncateForModel(text: string): { text: string; truncated: boolean } {
  if (text.length <= MAX_TEXT_FOR_MODEL) {
    return { text, truncated: false };
  }

  return {
    text: text.slice(0, MAX_TEXT_FOR_MODEL),
    truncated: true
  };
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
  const model = params.model || process.env.OPENAI_MODEL || 'gpt-4.1';
  const client = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
    baseURL: process.env.OPENAI_BASE_URL
  });

  const content: OpenAI.Chat.Completions.ChatCompletionContentPart[] = [
    {
      type: 'text',
      text: [
        'Estrarre lista fili e componenti da uno schema elettrico seguendo le regole R26 (R1-R8: numeri fili rossi, frecce rosse, barre "\\\\", duplicazione per ganci, doppio elenco fili/componenti).',
        'Stai ricevendo un batch di pagine (max 10). Indica per ogni riga il numero di pagina nel campo "page" riferito alla pagina originale.',
        'Salta pagine di esempio/legenda (spesso marcate "ESEMPIO") e ignora collegamenti/componenti tratteggiati o indicati come esterni/opzionali; non estrarre fili da quei tratti.',
        'Se un elemento è descritto su più pagine, accumula quantità e mantieni i riferimenti coerenti; non duplicare oggetti già contati.',
        'Per ogni filo imposta chiaramente il punto di partenza (`from`) e di arrivo (`to`) come sigle/morsetti/dispositivi.',
        'Per ogni componente aggiungi il campo "wires": array di ID o sigle dei fili collegati (se noti).',
        'Pattern importante: se trovi "105.8 / 24", l\'ID filo è "24" e la sezione/gauge è "105.8"; non creare nomi come "105.8_L1" o "L1".',
        'Per componenti come "-QM102/1" il riferimento è "QM102"; il suffisso "/1" va in note o nel terminale, non cambiare il nome in "L1".',
        'Sezione/gauge: inseriscila solo se appare in chiaro (es. "1,5 mm²", "2x4 mm2", AWG). Rimandi pagina/posizionamenti (es. 160.2, 108.8) NON sono sezioni: lascia vuote Sezione/Colore/Lunghezza se non esplicitate sul filo.',
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
        text: `Testo pagina ${pageLabel} (troncato):\n${page.pageText}`
      });
    }

    if (page.pageImage) {
      content.push({
        type: 'image_url',
        image_url: {
          url: `data:image/png;base64,${page.pageImage}`,
          detail: 'high'
        }
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
    { Campo: 'Modello', Valore: params.metadata.model || 'gpt-4o-mini' },
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
  const outputPath = path.resolve(
    input.output_excel_path || path.join(process.cwd(), 'outputs', `wirelist-${Date.now()}.xlsx`)
  );

  const startPage = Math.max(1, input.start_page ?? 1);
  const maxPages = input.max_pages ?? Number(process.env.DEFAULT_MAX_PAGES || 3);
  const boundedMaxPages = Math.min(maxPages, 1000);
  const requestedEnd = input.end_page ? Math.max(input.end_page, startPage) : undefined;
  const endPage = requestedEnd
    ? Math.min(requestedEnd, startPage + boundedMaxPages - 1)
    : startPage + boundedMaxPages - 1;
  const useVision = input.use_vision ?? true;

  let rawText = '';
  let pageTexts: string[] = [];
  let images: string[] = [];
  const ext = path.extname(resolvedPath).toLowerCase();

  try {
    if (ext === '.pdf') {
      const pdfText = await extractPdfText(resolvedPath);
      const startIdx = Math.max(0, startPage - 1);
      const endIdx = Math.min(pdfText.pageTexts.length, endPage);
      pageTexts = pdfText.pageTexts.slice(startIdx, endIdx);
      rawText = pageTexts.length ? pageTexts.join('\n') : pdfText.fullText;
      if (startIdx >= pdfText.pageTexts.length && pdfText.pageTexts.length) {
        warnings.push(`start_page=${startPage} oltre il numero di pagine (${pdfText.pageTexts.length}).`);
      }

      if (useVision) {
        images = await convertPdfToImages(resolvedPath, startPage, endPage);
        if (!images.length) {
          warnings.push('Impossibile convertire il PDF in immagini: assicurati che poppler-utils/pdftoppm sia installato.');
        }
      } else if (!rawText || rawText.trim().length < 30) {
        warnings.push('PDF con poco testo e visione disattivata: l’estrazione potrebbe essere incompleta.');
      }
    } else if (['.png', '.jpg', '.jpeg', '.tiff', '.bmp'].includes(ext)) {
      images = [await loadImageAsBase64(resolvedPath)];
      warnings.push('File immagine: uso visione/LLM per estrazione.');
    } else {
      rawText = await fs.readFile(resolvedPath, 'utf-8');
    }
  } catch (error: any) {
    throw new Error(`Impossibile leggere il file: ${error.message}`);
  }

  const { text: textForModel, truncated } = truncateForModel(rawText);
  if (truncated) {
    warnings.push('Testo schemi troncato per il modello (limite 12k caratteri).');
  }

  let wires: WireRecord[] = [];
  let components: ComponentRecord[] = [];

  if (process.env.OPENAI_API_KEY) {
    try {
      const textualPages = pageTexts.length ? pageTexts : [textForModel];
      const pageItems = images.length
        ? images.map((img, i) => ({
            pageImage: img,
            pageText: textualPages[i] ?? textForModel,
            pageIndex: i,
            totalPages: images.length,
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

      const processBatch = async (batch: typeof pageItems, batchIndex: number, totalBatches: number) => {
        const preparedPages = batch.map(p => {
          const textToUse = p.pageText || textForModel;
          const { text: truncatedText, truncated } = truncateForModel(textToUse);
          if (truncated) {
            const label = p.pageNumber ?? (p.pageIndex + 1);
            warnings.push(`Pagina ${label}: testo troncato per il modello (limite 12k caratteri).`);
          }
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
  wires = normalizeWires(wires);
  components = normalizeComponents(components);

  if (!wires.length && rawText) {
    const heuristic = heuristicWireParse(rawText);
    if (heuristic.length) {
      warnings.push('Usata estrazione euristica di base perché il modello non ha restituito fili.');
      wires = heuristic;
    }
  }

  const pagesCount = images.length || pageTexts.length || (rawText ? Math.max(1, endPage - startPage + 1) : undefined);

  const metadata: ExtractionMetadata = {
    source_file: resolvedPath,
    pages_used: pagesCount,
    text_chars: rawText.length,
    truncated_text: truncated,
    project: input.project,
    note: input.note,
    model: input.model || process.env.OPENAI_MODEL || 'gpt-4.1',
    extracted_at: new Date().toISOString()
  };

  await buildWorkbook({
    wires,
    components,
    metadata,
    rawText,
    addRawTextSheet: input.add_raw_text_sheet ?? true,
    outputPath
  });

  return {
    output_excel_path: outputPath,
    wires: wires.length,
    components: components.length,
    warnings,
    metadata
  };
}
