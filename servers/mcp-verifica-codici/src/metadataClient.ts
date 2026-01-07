import type { SourceField } from './schema.js';

// ============================================================================
// Configuration
// ============================================================================

const BOX_SERVER_URL = process.env.BOX_SERVER_URL || 'http://localhost:3001';
const METADATA_QUERY_ENDPOINT = process.env.METADATA_QUERY_ENDPOINT || '/api/metadata/query';
const TABLE_QUERY_ENDPOINT = process.env.TABLE_QUERY_ENDPOINT || '/api/metadata/tables/query';
const TABLE_LIST_ENDPOINT = process.env.TABLE_LIST_ENDPOINT || '/api/metadata/tables';
const DEFAULT_ROW_LIMIT = 500;

// ============================================================================
// Types
// ============================================================================

export interface QueryResult {
  sql: string;
  rows: Array<Record<string, unknown>>;
  rowCount: number;
  columns: string[];
}

export interface FolderMetadataRow {
  documentId: string;
  documentName?: string;
  [fieldName: string]: string | undefined;
}

export interface TableRow {
  [columnName: string]: string;
}

export interface TableInfo {
  name: string;
  tableName: string;
  rowCount: number;
  columns: Array<{ name: string; originalName: string; type: string }>;
  page?: number;
  sourceName?: string;
}

// ============================================================================
// Field Extraction Utilities
// ============================================================================

/**
 * Extracts all unique field/column names from source fields.
 */
export function extractColumnNames(fields: SourceField[]): string[] {
  const columns = new Set<string>();
  for (const field of fields) {
    if (typeof field.column === 'string') {
      columns.add(field.column);
    } else {
      field.column.forEach(col => columns.add(col));
    }
  }
  return Array.from(columns);
}

// ============================================================================
// SQL Query Builder for Folder Metadata
// ============================================================================

/**
 * Escapes a string for safe use in SQL (basic escaping for single quotes).
 */
function escapeSQL(value: string): string {
  return value.replace(/'/g, "''");
}

/**
 * Builds a dynamic SQL query to pivot DocumentFieldValue rows into document-centric records.
 */
export function buildFolderMetadataQuery(vectorId: string, fields: string[]): string {
  // Build CASE statements for each field
  const caseStatements = fields.map(field =>
    `MAX(CASE WHEN "fieldName" = '${escapeSQL(field)}' THEN "valueText" END) as "${escapeSQL(field)}"`
  ).join(',\n    ');

  // Build field list for WHERE clause
  const fieldList = fields.map(f => `'${escapeSQL(f)}'`).join(', ');

  return `
SELECT
    "documentId",
    "documentName",
    ${caseStatements}
FROM "DocumentFieldValue"
WHERE "vectorId" = '${escapeSQL(vectorId)}'
  AND "fieldName" IN (${fieldList})
GROUP BY "documentId", "documentName"
`.trim();
}

// ============================================================================
// Folder Metadata Query Client
// ============================================================================

/**
 * Queries folder metadata from the box-server API (DocumentFieldValue table).
 */
export async function queryFolderMetadata(
  vectorId: string,
  fields: string[],
  rowLimit: number = DEFAULT_ROW_LIMIT
): Promise<FolderMetadataRow[]> {
  if (!fields.length) {
    throw new Error('No metadata fields specified');
  }

  const sql = buildFolderMetadataQuery(vectorId, fields);
  const url = `${BOX_SERVER_URL}${METADATA_QUERY_ENDPOINT}`;

  process.stderr.write(`[metadataClient] Querying folder metadata: ${url}\n`);
  process.stderr.write(`[metadataClient] Fields: ${fields.join(', ')}\n`);

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vectorId, sql, rowLimit }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Folder metadata query failed (${response.status}): ${errorText}`);
  }

  const result = await response.json() as QueryResult;
  process.stderr.write(`[metadataClient] Folder metadata returned ${result.rowCount} rows\n`);

  return result.rows.map(row => ({
    documentId: String(row.documentId || ''),
    documentName: row.documentName ? String(row.documentName) : undefined,
    ...Object.fromEntries(
      fields.map(field => [field, row[field] != null ? String(row[field]) : undefined])
    ),
  }));
}

// ============================================================================
// Extracted Table Query Client
// ============================================================================

/**
 * Lists available metadata field names for a collection.
 * Useful for diagnostics when expected fields are not found.
 */
export async function listAvailableFields(vectorId: string): Promise<string[]> {
  const sql = `
SELECT DISTINCT "fieldName"
FROM "DocumentFieldValue"
WHERE "vectorId" = '${escapeSQL(vectorId)}'
ORDER BY "fieldName"
`.trim();

  const url = `${BOX_SERVER_URL}${METADATA_QUERY_ENDPOINT}`;

  process.stderr.write(`[metadataClient] Listing available fields for vectorId: ${vectorId}\n`);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vectorId, sql, rowLimit: 100 }),
    });

    if (!response.ok) {
      process.stderr.write(`[metadataClient] Failed to list fields: ${response.status}\n`);
      return [];
    }

    const result = await response.json() as QueryResult;
    const fields = result.rows.map(row => String(row.fieldName || '')).filter(Boolean);
    process.stderr.write(`[metadataClient] Available fields: ${fields.join(', ')}\n`);
    return fields;
  } catch (error) {
    process.stderr.write(`[metadataClient] Error listing fields: ${error}\n`);
    return [];
  }
}

/**
 * Lists available tables for a collection.
 */
export async function listTables(vectorId: string): Promise<TableInfo[]> {
  const url = `${BOX_SERVER_URL}${TABLE_LIST_ENDPOINT}/${vectorId}`;

  process.stderr.write(`[metadataClient] Listing tables: ${url}\n`);

  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`List tables failed (${response.status}): ${errorText}`);
  }

  const result = await response.json() as { success: boolean; tables: TableInfo[] };
  process.stderr.write(`[metadataClient] Found ${result.tables?.length || 0} tables\n`);

  return result.tables || [];
}

/**
 * Queries extracted tables from the box-server API (VectorDataset/SQLite).
 */
export async function queryExtractedTable(
  vectorId: string,
  tableName?: string,
  columns?: string[],
  rowLimit: number = DEFAULT_ROW_LIMIT
): Promise<TableRow[]> {
  const url = `${BOX_SERVER_URL}${TABLE_QUERY_ENDPOINT}`;

  // Build SQL query
  let sql: string;
  if (columns && columns.length > 0) {
    const columnList = columns.map(c => `"${escapeSQL(c)}"`).join(', ');
    if (tableName) {
      sql = `SELECT ${columnList} FROM "${escapeSQL(tableName)}" LIMIT ${rowLimit}`;
    } else {
      sql = `SELECT ${columnList} FROM main_table LIMIT ${rowLimit}`;
    }
  } else {
    if (tableName) {
      sql = `SELECT * FROM "${escapeSQL(tableName)}" LIMIT ${rowLimit}`;
    } else {
      sql = `SELECT * FROM main_table LIMIT ${rowLimit}`;
    }
  }

  process.stderr.write(`[metadataClient] Querying table: ${url}\n`);
  process.stderr.write(`[metadataClient] SQL: ${sql}\n`);

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vectorId, sql, rowLimit }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Table query failed (${response.status}): ${errorText}`);
  }

  const result = await response.json() as { success: boolean } & QueryResult;
  process.stderr.write(`[metadataClient] Table query returned ${result.rowCount} rows\n`);

  return result.rows.map(row =>
    Object.fromEntries(
      Object.entries(row).map(([key, value]) => [key, value != null ? String(value) : ''])
    )
  );
}
