import type {
  CompareCodiciInput,
  ComparisonReport,
  ComparisonEntry,
  ComparisonSettings,
  ComparisonSummary,
  DiagnosticInfo,
  FieldComparisonResult,
  FieldMapping,
  SourceField,
} from './schema.js';
import { ComparisonSettingsSchema } from './schema.js';
import {
  queryFolderMetadata,
  queryExtractedTable,
  extractColumnNames,
  listAvailableFields,
  listTables,
  type FolderMetadataRow,
  type TableRow,
} from './metadataClient.js';

// ============================================================================
// Value Composition and Normalization
// ============================================================================

/**
 * Composes a single value from one or more columns in a row.
 *
 * @param row - The data row
 * @param columns - Single column name or array of column names
 * @param separator - Separator to use when joining multiple columns
 * @returns Composed string value
 */
export function composeValue(
  row: Record<string, string | undefined>,
  columns: string | string[],
  separator: string
): string {
  if (typeof columns === 'string') {
    return row[columns] ?? '';
  }

  // Join multiple columns, filtering out empty values
  return columns
    .map(col => row[col] ?? '')
    .filter(val => val.trim() !== '')
    .join(separator);
}

/**
 * Normalizes a value according to comparison settings.
 *
 * @param value - The value to normalize
 * @param settings - Comparison settings
 * @returns Normalized string
 */
export function normalizeValue(value: string, settings: ComparisonSettings): string {
  let result = value;

  // Trim and normalize whitespace
  if (settings.ignore_whitespace) {
    result = result.trim().replace(/\s+/g, ' ');
  }

  // Normalize case
  if (!settings.case_sensitive) {
    result = result.toLowerCase();
  }

  // Normalize dashes and underscores
  if (settings.normalize_dashes) {
    result = result.replace(/[-_]/g, '-');
  }

  return result;
}

/**
 * Compares two values according to settings.
 *
 * @param value1 - First value
 * @param value2 - Second value
 * @param settings - Comparison settings
 * @returns True if values match
 */
export function valuesMatch(
  value1: string,
  value2: string,
  settings: ComparisonSettings
): boolean {
  const normalized1 = normalizeValue(value1, settings);
  const normalized2 = normalizeValue(value2, settings);

  // Skip empty comparison if configured
  if (settings.skip_empty && (!normalized1 || !normalized2)) {
    return true; // Consider empty vs empty or empty vs value as "match" (skip)
  }

  if (settings.partial_match) {
    // Either value contains the other
    return normalized1.includes(normalized2) || normalized2.includes(normalized1);
  }

  return normalized1 === normalized2;
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Resolves comparison settings from input.
 */
function resolveSettings(input: CompareCodiciInput): ComparisonSettings {
  // Start with defaults
  let settings = ComparisonSettingsSchema.parse({});

  // Override with inline settings if provided
  if (input.settings) {
    settings = ComparisonSettingsSchema.parse({ ...settings, ...input.settings });
  }

  return settings;
}

/**
 * Gets the primary field mapping (first required field, or first field).
 */
function getPrimaryMapping(mappings: FieldMapping[]): FieldMapping {
  return mappings.find(m => m.required) || mappings[0];
}

/**
 * Finds a source field by name.
 */
function findSourceField(fields: SourceField[], name: string): SourceField | undefined {
  return fields.find(f => f.name === name);
}

/**
 * Composes a value for a field mapping from folder metadata.
 */
function composeFolderValue(
  row: FolderMetadataRow,
  fieldName: string,
  folderFields: SourceField[]
): string {
  const sourceField = findSourceField(folderFields, fieldName);
  if (!sourceField) return '';
  return composeValue(row, sourceField.column, sourceField.separator);
}

/**
 * Composes a value for a field mapping from table data.
 */
function composeTableValue(
  row: TableRow,
  fieldName: string,
  tableColumns: SourceField[]
): string {
  const sourceField = findSourceField(tableColumns, fieldName);
  if (!sourceField) return '';
  return composeValue(row, sourceField.column, sourceField.separator);
}

// ============================================================================
// Main Comparison Logic
// ============================================================================

/**
 * Performs the comparison between extracted table data and folder metadata.
 *
 * @param input - The compare_codici tool input
 * @returns Comparison report
 */
export async function compareCodici(input: CompareCodiciInput): Promise<ComparisonReport> {
  const startTime = Date.now();

  // 1. Resolve settings
  const settings = resolveSettings(input);
  process.stderr.write(`[compareCodici] Settings: ${JSON.stringify(settings)}\n`);

  // 2. Extract column/field names from source configurations
  const folderFieldNames = extractColumnNames(input.folder_metadata.fields);
  const tableColumnNames = extractColumnNames(input.table_source.columns);

  process.stderr.write(`[compareCodici] Folder fields: ${folderFieldNames.join(', ')}\n`);
  process.stderr.write(`[compareCodici] Table columns: ${tableColumnNames.join(', ')}\n`);

  // 3. Load data from both sources
  process.stderr.write(`[compareCodici] Querying folder metadata for documentsVectorId: ${input.documentsVectorId}\n`);
  const folderRows = await queryFolderMetadata(input.documentsVectorId, folderFieldNames);

  process.stderr.write(`[compareCodici] Querying extracted table from listaVectorId: ${input.listaVectorId}, table: ${input.table_source.table_name || 'default'}\n`);
  const tableRows = await queryExtractedTable(
    input.listaVectorId,
    input.table_source.table_name,
    tableColumnNames
  );

  process.stderr.write(`[compareCodici] Loaded ${folderRows.length} folder documents and ${tableRows.length} table rows\n`);

  // 3b. Collect diagnostics if either query returned 0 rows
  const diagnostics: DiagnosticInfo = {};
  const warnings: string[] = [];
  const suggestions: string[] = [];

  if (folderRows.length === 0) {
    warnings.push(`La cartella documenti (${input.documentsVectorId}) non ha restituito righe per i campi richiesti: ${folderFieldNames.join(', ')}`);

    // Fetch available fields for diagnostic
    const availableFields = await listAvailableFields(input.documentsVectorId);
    if (availableFields.length > 0) {
      diagnostics.availableFolderFields = availableFields;
      suggestions.push(`Campi metadata disponibili nella cartella documenti: ${availableFields.join(', ')}`);
      suggestions.push('Verifica che il campo "codice" esista nei documenti o usa uno dei campi disponibili');
    } else {
      suggestions.push('Nessun campo metadata trovato. Esegui prima l\'estrazione metadata sui documenti.');
    }
  }

  if (tableRows.length === 0) {
    warnings.push(`La tabella lista codici (${input.listaVectorId}) non ha restituito righe`);

    // Fetch available tables for diagnostic
    const availableTables = await listTables(input.listaVectorId);
    if (availableTables.length > 0) {
      diagnostics.availableTables = availableTables.map(t => t.name);
      suggestions.push(`Tabelle disponibili: ${availableTables.map(t => `"${t.name}" (${t.rowCount} righe)`).join(', ')}`);
      suggestions.push('Specifica il nome corretto della tabella in table_source.table_name');
    } else {
      suggestions.push('Nessuna tabella trovata. Esegui prima l\'estrazione tabelle sul PDF lista codici.');
    }
  }

  if (warnings.length > 0) diagnostics.warnings = warnings;
  if (suggestions.length > 0) diagnostics.suggestions = suggestions;

  // 4. Get primary mapping for key generation
  const primaryMapping = getPrimaryMapping(input.field_mappings);

  // 5. Build lookup maps by primary key
  const tableByKey = new Map<string, { row: TableRow; index: number }>();
  const folderByKey = new Map<string, FolderMetadataRow>();

  // Build table lookup
  for (const row of tableRows) {
    const key = normalizeValue(
      composeTableValue(row, primaryMapping.name, input.table_source.columns),
      settings
    );
    if (key) {
      tableByKey.set(key, { row, index: tableByKey.size });
    }
  }

  // Build folder metadata lookup
  for (const row of folderRows) {
    const key = normalizeValue(
      composeFolderValue(row, primaryMapping.name, input.folder_metadata.fields),
      settings
    );
    if (key) {
      folderByKey.set(key, row);
    }
  }

  process.stderr.write(`[compareCodici] Table entries by key: ${tableByKey.size}, Folder entries by key: ${folderByKey.size}\n`);

  // 6. Compare entries: for each table row, find matching folder metadata
  const entries: ComparisonEntry[] = [];
  const processedKeys = new Set<string>();

  // Check table entries against folder metadata
  for (const [key, { row: tableRow }] of tableByKey) {
    processedKeys.add(key);
    const folderRow = folderByKey.get(key);

    if (!folderRow) {
      // Missing from folder - table entry has no matching document
      entries.push({
        primaryKey: key,
        status: 'missing_from_folder',
        fields: buildFieldResults(
          input.field_mappings,
          tableRow,
          undefined,
          input.table_source.columns,
          input.folder_metadata.fields,
          settings
        ),
        tableRow: { ...tableRow },
      });
    } else {
      // Found in both - compare all fields
      const fieldResults = buildFieldResults(
        input.field_mappings,
        tableRow,
        folderRow,
        input.table_source.columns,
        input.folder_metadata.fields,
        settings
      );

      const allRequiredMatch = input.field_mappings
        .filter(m => m.required)
        .every(m => fieldResults[m.name].match);
      const anyMismatch = Object.values(fieldResults).some(r => !r.match);

      entries.push({
        primaryKey: key,
        status: allRequiredMatch
          ? (anyMismatch ? 'partial' : 'matched')
          : 'partial',
        fields: fieldResults,
        tableRow: { ...tableRow },
        folderMetadata: {
          documentId: folderRow.documentId,
          documentName: folderRow.documentName,
          ...Object.fromEntries(
            input.folder_metadata.fields.map(f => [
              f.name,
              composeFolderValue(folderRow, f.name, input.folder_metadata.fields)
            ])
          ),
        },
      });
    }
  }

  // Check folder entries not in table (documents not in lista codici)
  for (const [key, folderRow] of folderByKey) {
    if (!processedKeys.has(key)) {
      entries.push({
        primaryKey: key,
        status: 'missing_from_table',
        fields: buildFieldResults(
          input.field_mappings,
          undefined,
          folderRow,
          input.table_source.columns,
          input.folder_metadata.fields,
          settings
        ),
        folderMetadata: {
          documentId: folderRow.documentId,
          documentName: folderRow.documentName,
          ...Object.fromEntries(
            input.folder_metadata.fields.map(f => [
              f.name,
              composeFolderValue(folderRow, f.name, input.folder_metadata.fields)
            ])
          ),
        },
      });
    }
  }

  // 7. Build summary
  const summary: ComparisonSummary = {
    totalTableEntries: tableRows.length,
    totalFolderDocuments: folderRows.length,
    matched: entries.filter(e => e.status === 'matched').length,
    partialMatch: entries.filter(e => e.status === 'partial').length,
    missingFromFolder: entries.filter(e => e.status === 'missing_from_folder').length,
    missingFromTable: entries.filter(e => e.status === 'missing_from_table').length,
  };

  const elapsed = Date.now() - startTime;
  process.stderr.write(`[compareCodici] Comparison completed in ${elapsed}ms\n`);

  // 8. Return report
  const report: ComparisonReport = {
    summary,
    entries,
    timestamp: new Date().toISOString(),
    parameters: {
      documentsVectorId: input.documentsVectorId,
      listaVectorId: input.listaVectorId,
      tableName: input.table_source.table_name,
      fieldMappings: input.field_mappings,
    },
    settings,
  };

  // Add diagnostics if any issues found
  if (Object.keys(diagnostics).length > 0) {
    report.diagnostics = diagnostics;
  }

  return report;
}

/**
 * Builds field comparison results for all mappings.
 */
function buildFieldResults(
  mappings: FieldMapping[],
  tableRow: TableRow | undefined,
  folderRow: FolderMetadataRow | undefined,
  tableColumns: SourceField[],
  folderFields: SourceField[],
  settings: ComparisonSettings
): Record<string, FieldComparisonResult> {
  const results: Record<string, FieldComparisonResult> = {};

  for (const mapping of mappings) {
    const tableValue = tableRow
      ? composeTableValue(tableRow, mapping.name, tableColumns)
      : '';
    const folderValue = folderRow
      ? composeFolderValue(folderRow, mapping.name, folderFields)
      : '';

    const match = tableRow && folderRow
      ? valuesMatch(tableValue, folderValue, settings)
      : false;

    results[mapping.name] = {
      tableValue,
      folderValue,
      match,
    };
  }

  return results;
}
