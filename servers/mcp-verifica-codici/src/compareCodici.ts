import type {
  CompareCodiciInput,
  ComparisonReport,
  ComparisonEntry,
  ComparisonSettings,
  ComparisonSummary,
  DiagnosticInfo,
  FieldComparisonResult,
  FieldMapping,
  MatchDetail,
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

  // Trim whitespace from ends
  result = result.trim();

  // Normalize case
  if (!settings.case_sensitive) {
    result = result.toLowerCase();
  }

  // Normalize separators: convert spaces, dashes, underscores to a common separator
  if (settings.normalize_dashes) {
    // Replace all separator-like characters (space, dash, underscore) with a single dash
    result = result.replace(/[\s\-_]+/g, '-');
    // Remove trailing dashes
    result = result.replace(/-+$/, '');
    // Remove leading dashes
    result = result.replace(/^-+/, '');
  } else if (settings.ignore_whitespace) {
    // Just normalize multiple spaces to single space
    result = result.replace(/\s+/g, ' ');
  }

  return result;
}

// ============================================================================
// Fuzzy Matching Functions
// ============================================================================

/**
 * Tokenizes a string into a set of lowercase tokens.
 * Splits on spaces, dashes, underscores, and other separators.
 */
export function tokenize(value: string): Set<string> {
  return new Set(
    value.toLowerCase()
      .split(/[\s\-_:.,;/\\]+/)
      .filter(t => t.length > 0)
  );
}

/**
 * Calculates Jaccard similarity between two token sets.
 * Returns a value between 0 (no overlap) and 1 (identical).
 */
export function jaccardSimilarity(tokens1: Set<string>, tokens2: Set<string>): number {
  if (tokens1.size === 0 && tokens2.size === 0) return 1;
  if (tokens1.size === 0 || tokens2.size === 0) return 0;

  const intersection = new Set([...tokens1].filter(t => tokens2.has(t)));
  const union = new Set([...tokens1, ...tokens2]);

  return intersection.size / union.size;
}

/**
 * Calculates similarity score between two code strings using token-based matching.
 */
export function calculateSimilarity(value1: string, value2: string): number {
  const tokens1 = tokenize(value1);
  const tokens2 = tokenize(value2);
  return jaccardSimilarity(tokens1, tokens2);
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
 * Finds a source field by name (case-insensitive).
 */
function findSourceField(fields: SourceField[], name: string): SourceField | undefined {
  // First try exact match
  const exact = fields.find(f => f.name === name);
  if (exact) return exact;
  // Fallback to case-insensitive match
  const lower = name.toLowerCase();
  return fields.find(f => f.name.toLowerCase() === lower);
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

/**
 * Checks if a value is a valid document code based on optional prefix.
 * @param value - The code value to check
 * @param prefix - Optional prefix that valid codes must start with
 * @returns true if the code is valid
 */
export function isValidCode(value: string, prefix?: string): boolean {
  const trimmed = value.trim();

  // Empty values are not valid
  if (!trimmed) return false;

  // If prefix is specified, code must start with it (case-insensitive)
  if (prefix) {
    return trimmed.toLowerCase().startsWith(prefix.toLowerCase());
  }

  // No prefix specified - accept all non-empty values
  return true;
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
  if (input.code_prefix) {
    process.stderr.write(`[compareCodici] Code prefix filter: "${input.code_prefix}"\n`);
  }

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

  // 3b. Collect diagnostics if either query returned 0 rows or all values are empty
  const diagnostics: DiagnosticInfo = {};
  const warnings: string[] = [];
  const suggestions: string[] = [];

  // Check if all folder field values are empty (even if rows returned)
  const folderHasEmptyValues = folderRows.length > 0 && folderRows.every(row => {
    return folderFieldNames.every(field => {
      const value = row[field];
      return !value || value.trim() === '';
    });
  });

  if (folderRows.length === 0 || folderHasEmptyValues) {
    if (folderHasEmptyValues) {
      warnings.push(`La cartella documenti ha ${folderRows.length} documenti ma tutti i valori per i campi richiesti (${folderFieldNames.join(', ')}) sono vuoti o nulli`);
      warnings.push('Questo potrebbe indicare che il nome del campo è diverso (es: "Codice" invece di "codice")');
    } else {
      warnings.push(`La cartella documenti (${input.documentsVectorId}) non ha restituito righe per i campi richiesti: ${folderFieldNames.join(', ')}`);
    }

    // Fetch available fields for diagnostic
    const availableFields = await listAvailableFields(input.documentsVectorId);
    if (availableFields.length > 0) {
      diagnostics.availableFolderFields = availableFields;
      suggestions.push(`Campi metadata disponibili nella cartella documenti: ${availableFields.join(', ')}`);

      // Check if any available field is similar to requested fields (case-insensitive match)
      const similarFields = availableFields.filter(available =>
        folderFieldNames.some(requested =>
          available.toLowerCase() === requested.toLowerCase() && available !== requested
        )
      );
      if (similarFields.length > 0) {
        suggestions.push(`ATTENZIONE: Trovati campi simili ma con case diverso: ${similarFields.join(', ')}. Usa esattamente questi nomi in folder_metadata.fields[].column`);
      } else {
        suggestions.push('Verifica che il campo "codice" esista nei documenti o usa uno dei campi disponibili');
      }
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

  // Build table lookup - filter out invalid codes (section headers) if code_prefix is specified
  let filteredTableEntries = 0;
  for (const row of tableRows) {
    const rawKey = composeTableValue(row, primaryMapping.name, input.table_source.columns);

    // Filter by code_prefix if specified
    if (!isValidCode(rawKey, input.code_prefix)) {
      filteredTableEntries++;
      continue;  // Skip entries not matching prefix
    }

    const key = normalizeValue(rawKey, settings);
    if (key) {
      tableByKey.set(key, { row, index: tableByKey.size });
    }
  }

  // Add filtered count to diagnostics if any were filtered
  if (filteredTableEntries > 0) {
    diagnostics.filteredTableEntries = filteredTableEntries;
    suggestions.push(`Filtrate ${filteredTableEntries} voci che non iniziano con "${input.code_prefix}"`);
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

  // 6. Compare entries: for each table row, find best matching folder metadata using fuzzy matching
  const entries: ComparisonEntry[] = [];
  const matchDetails: MatchDetail[] = [];
  const processedFolderKeys = new Set<string>();

  process.stderr.write(`[compareCodici] Using similarity threshold: ${settings.similarity_threshold}\n`);

  // Check table entries against folder metadata using fuzzy token matching
  for (const [tableKey, { row: tableRow }] of tableByKey) {
    // Get original (non-normalized) table code for match details
    const originalTableCode = composeTableValue(tableRow, primaryMapping.name, input.table_source.columns);

    // Find BEST matching folder entry by similarity score
    let bestMatch: { row: FolderMetadataRow; key: string; score: number } | null = null;

    for (const [folderKey, folderRow] of folderByKey) {
      const score = calculateSimilarity(tableKey, folderKey);

      // Update best match if this score is above threshold and better than previous
      if (score >= settings.similarity_threshold && (!bestMatch || score > bestMatch.score)) {
        bestMatch = { row: folderRow, key: folderKey, score };
      }
    }

    if (!bestMatch) {
      // Missing from folder - table entry has no matching document
      entries.push({
        primaryKey: tableKey,
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
      // Found match - mark folder key as processed
      processedFolderKeys.add(bestMatch.key);
      const matchedFolderRow = bestMatch.row;

      // Get original (non-normalized) folder code for match details
      const originalFolderCode = composeFolderValue(matchedFolderRow, primaryMapping.name, input.folder_metadata.fields);

      // Add to matchDetails for verification
      matchDetails.push({
        tableCode: originalTableCode,
        folderCode: originalFolderCode,
        score: bestMatch.score,
        documentName: matchedFolderRow.documentName,
      });

      // Compare all fields
      const fieldResults = buildFieldResults(
        input.field_mappings,
        tableRow,
        matchedFolderRow,
        input.table_source.columns,
        input.folder_metadata.fields,
        settings
      );

      const allRequiredMatch = input.field_mappings
        .filter(m => m.required)
        .every(m => fieldResults[m.name].match);
      const anyMismatch = Object.values(fieldResults).some(r => !r.match);

      entries.push({
        primaryKey: tableKey,
        status: allRequiredMatch
          ? (anyMismatch ? 'partial' : 'matched')
          : 'partial',
        matchScore: bestMatch.score,  // Include similarity score
        fields: fieldResults,
        tableRow: { ...tableRow },
        folderMetadata: {
          documentId: matchedFolderRow.documentId,
          documentName: matchedFolderRow.documentName,
          ...Object.fromEntries(
            input.folder_metadata.fields.map(f => [
              f.name,
              composeFolderValue(matchedFolderRow, f.name, input.folder_metadata.fields)
            ])
          ),
        },
      });
    }
  }

  // Check folder entries not in table (documents not in lista codici)
  for (const [key, folderRow] of folderByKey) {
    if (!processedFolderKeys.has(key)) {
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

  // 7. Build summary with score distribution
  const matchedEntries = entries.filter(e => e.matchScore !== undefined);

  // Calculate score distribution
  const scoreDistribution = {
    exact: matchedEntries.filter(e => e.matchScore === 1).length,
    high: matchedEntries.filter(e => e.matchScore! >= 0.9 && e.matchScore! < 1).length,
    medium: matchedEntries.filter(e => e.matchScore! >= 0.7 && e.matchScore! < 0.9).length,
    low: matchedEntries.filter(e => e.matchScore! < 0.7).length,
  };

  const summary: ComparisonSummary = {
    totalTableEntries: tableRows.length,
    totalFolderDocuments: folderRows.length,
    matched: entries.filter(e => e.status === 'matched').length,
    partialMatch: entries.filter(e => e.status === 'partial').length,
    missingFromFolder: entries.filter(e => e.status === 'missing_from_folder').length,
    missingFromTable: entries.filter(e => e.status === 'missing_from_table').length,
    scoreDistribution,
    matchDetails: matchDetails.length > 0 ? matchDetails : undefined,
  };

  // 7b. Additional diagnostics if ALL entries are missing_from_folder (likely field mismatch)
  const allMissingFromFolder = summary.matched === 0 &&
    summary.partialMatch === 0 &&
    summary.missingFromFolder > 0 &&
    summary.missingFromTable === 0;

  if (allMissingFromFolder && folderRows.length > 0) {
    warnings.push(`ATTENZIONE: Tutti i ${summary.missingFromFolder} codici della tabella risultano "missing from folder" nonostante ci siano ${folderRows.length} documenti nella cartella.`);
    warnings.push('Questo indica che i valori dei codici nei documenti non corrispondono a quelli della tabella.');

    // Fetch available fields if not already done
    if (!diagnostics.availableFolderFields) {
      const availableFields = await listAvailableFields(input.documentsVectorId);
      if (availableFields.length > 0) {
        diagnostics.availableFolderFields = availableFields;
        suggestions.push(`Campi metadata disponibili: ${availableFields.join(', ')}`);
      }
    }

    // Show sample of folder keys vs table keys for debugging
    const sampleFolderKeys = Array.from(folderByKey.keys()).slice(0, 5);
    const sampleTableKeys = Array.from(tableByKey.keys()).slice(0, 5);
    if (sampleFolderKeys.length > 0) {
      diagnostics.sampleFolderKeys = sampleFolderKeys;
      suggestions.push(`Esempio di chiavi nei documenti: ${sampleFolderKeys.join(', ')}`);
    }
    if (sampleTableKeys.length > 0) {
      diagnostics.sampleTableKeys = sampleTableKeys;
      suggestions.push(`Esempio di chiavi nella tabella: ${sampleTableKeys.join(', ')}`);
    }

  }

  // Always update diagnostics arrays if there are any warnings or suggestions
  if (warnings.length > 0) diagnostics.warnings = warnings;
  if (suggestions.length > 0) diagnostics.suggestions = suggestions;

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
