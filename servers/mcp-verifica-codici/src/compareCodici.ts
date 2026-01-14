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
  TableSource,
  TableStats,
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

/** Helper type for table entry with source tracking */
interface TableEntryWithSource {
  row: TableRow;
  tableName: string;
  tableColumns: SourceField[];
}

/**
 * Resolves table sources from input - handles both single table_source and multiple table_sources
 */
function resolveTableSources(input: CompareCodiciInput): TableSource[] {
  if (input.table_sources && input.table_sources.length > 0) {
    return input.table_sources;
  }
  if (input.table_source) {
    return [input.table_source];
  }
  throw new Error('Either table_source or table_sources must be provided');
}

/**
 * Performs the comparison between extracted table data and folder metadata.
 * Supports comparing against multiple tables.
 *
 * @param input - The compare_codici tool input
 * @returns Comparison report
 */
export async function compareCodici(input: CompareCodiciInput): Promise<ComparisonReport> {
  const startTime = Date.now();

  // 1. Resolve settings and table sources
  const settings = resolveSettings(input);
  const tableSources = resolveTableSources(input);
  const isMultiTable = tableSources.length > 1;

  process.stderr.write(`[compareCodici] Settings: ${JSON.stringify(settings)}\n`);
  process.stderr.write(`[compareCodici] Mode: ${isMultiTable ? 'multi-table' : 'single-table'} (${tableSources.length} tables)\n`);
  if (input.code_prefix) {
    process.stderr.write(`[compareCodici] Code prefix filter: "${input.code_prefix}"\n`);
  }

  // 2. Extract column/field names from source configurations
  const folderFieldNames = extractColumnNames(input.folder_metadata.fields);
  process.stderr.write(`[compareCodici] Folder fields: ${folderFieldNames.join(', ')}\n`);

  // 3. Load folder metadata
  process.stderr.write(`[compareCodici] Querying folder metadata for documentsVectorId: ${input.documentsVectorId}\n`);
  const folderRows = await queryFolderMetadata(input.documentsVectorId, folderFieldNames);
  process.stderr.write(`[compareCodici] Loaded ${folderRows.length} folder documents\n`);

  // 3b. Initialize diagnostics
  const diagnostics: DiagnosticInfo = {};
  const warnings: string[] = [];
  const suggestions: string[] = [];

  // Check if all folder field values are empty
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

    const availableFields = await listAvailableFields(input.documentsVectorId);
    if (availableFields.length > 0) {
      diagnostics.availableFolderFields = availableFields;
      suggestions.push(`Campi metadata disponibili nella cartella documenti: ${availableFields.join(', ')}`);

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

  // 4. Load all tables and combine data
  const tableByKey = new Map<string, TableEntryWithSource>();
  const perTableStats: Map<string, TableStats> = new Map();
  let totalTableRows = 0;
  let totalFilteredEntries = 0;

  const primaryMapping = getPrimaryMapping(input.field_mappings);
  const tableNames: string[] = [];

  for (const tableSource of tableSources) {
    const tableName = tableSource.table_name || 'default';
    tableNames.push(tableName);
    const tableColumnNames = extractColumnNames(tableSource.columns);

    process.stderr.write(`[compareCodici] Querying table "${tableName}" with columns: ${tableColumnNames.join(', ')}\n`);

    const tableRows = await queryExtractedTable(
      input.listaVectorId,
      tableSource.table_name,
      tableColumnNames
    );

    process.stderr.write(`[compareCodici] Table "${tableName}": ${tableRows.length} rows\n`);
    totalTableRows += tableRows.length;

    // Initialize per-table stats
    perTableStats.set(tableName, {
      tableName,
      totalEntries: tableRows.length,
      matched: 0,
      partialMatch: 0,
      missingFromFolder: 0,
    });

    // Add rows to combined lookup - filter by code_prefix if specified
    let filteredCount = 0;
    for (const row of tableRows) {
      const rawKey = composeTableValue(row, primaryMapping.name, tableSource.columns);

      if (!isValidCode(rawKey, input.code_prefix)) {
        filteredCount++;
        continue;
      }

      const key = normalizeValue(rawKey, settings);
      if (key) {
        // If key already exists from another table, keep the first one
        if (!tableByKey.has(key)) {
          tableByKey.set(key, {
            row,
            tableName,
            tableColumns: tableSource.columns,
          });
        }
      }
    }

    if (filteredCount > 0) {
      totalFilteredEntries += filteredCount;
      const stats = perTableStats.get(tableName)!;
      stats.totalEntries -= filteredCount;
    }

    if (tableRows.length === 0) {
      warnings.push(`La tabella "${tableName}" non ha restituito righe`);
    }
  }

  if (totalFilteredEntries > 0) {
    diagnostics.filteredTableEntries = totalFilteredEntries;
    suggestions.push(`Filtrate ${totalFilteredEntries} voci totali che non iniziano con "${input.code_prefix}"`);
  }

  // Fetch available tables for diagnostics if all tables are empty
  if (tableByKey.size === 0 && tableSources.length > 0) {
    const availableTables = await listTables(input.listaVectorId);
    if (availableTables.length > 0) {
      diagnostics.availableTables = availableTables.map(t => t.name);
      suggestions.push(`Tabelle disponibili: ${availableTables.map(t => `"${t.name}" (${t.rowCount} righe)`).join(', ')}`);
    } else {
      suggestions.push('Nessuna tabella trovata. Esegui prima l\'estrazione tabelle sul PDF lista codici.');
    }
  }

  // 5. Build folder metadata lookup
  const folderByKey = new Map<string, FolderMetadataRow>();
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

  // 6. Compare entries with fuzzy matching
  const entries: ComparisonEntry[] = [];
  const matchDetails: MatchDetail[] = [];
  const processedFolderKeys = new Set<string>();

  process.stderr.write(`[compareCodici] Using similarity threshold: ${settings.similarity_threshold}\n`);

  for (const [tableKey, tableEntry] of tableByKey) {
    const { row: tableRow, tableName, tableColumns } = tableEntry;
    const originalTableCode = composeTableValue(tableRow, primaryMapping.name, tableColumns);

    // Find best matching folder entry
    let bestMatch: { row: FolderMetadataRow; key: string; score: number } | null = null;

    for (const [folderKey, folderRow] of folderByKey) {
      const score = calculateSimilarity(tableKey, folderKey);
      if (score >= settings.similarity_threshold && (!bestMatch || score > bestMatch.score)) {
        bestMatch = { row: folderRow, key: folderKey, score };
      }
    }

    const stats = perTableStats.get(tableName)!;

    if (!bestMatch) {
      stats.missingFromFolder++;
      entries.push({
        primaryKey: tableKey,
        status: 'missing_from_folder',
        sourceTable: isMultiTable ? tableName : undefined,
        fields: buildFieldResults(
          input.field_mappings,
          tableRow,
          undefined,
          tableColumns,
          input.folder_metadata.fields,
          settings
        ),
        tableRow: { ...tableRow },
      });
    } else {
      processedFolderKeys.add(bestMatch.key);
      const matchedFolderRow = bestMatch.row;
      const originalFolderCode = composeFolderValue(matchedFolderRow, primaryMapping.name, input.folder_metadata.fields);

      // Get description values if "descrizione" field is mapped
      const descriptionMapping = input.field_mappings.find(m => m.name === 'descrizione');
      let tableDescription: string | undefined;
      let folderDescription: string | undefined;
      let descriptionScore: number | undefined;
      let descriptionMatch: boolean | undefined;

      if (descriptionMapping) {
        tableDescription = composeTableValue(tableRow, 'descrizione', tableColumns);
        folderDescription = composeFolderValue(matchedFolderRow, 'descrizione', input.folder_metadata.fields);

        if (tableDescription && folderDescription) {
          descriptionScore = calculateSimilarity(tableDescription, folderDescription);
          descriptionMatch = descriptionScore >= settings.similarity_threshold;
        }
      }

      matchDetails.push({
        tableCode: originalTableCode,
        folderCode: originalFolderCode,
        score: bestMatch.score,
        documentName: matchedFolderRow.documentName,
        sourceTable: isMultiTable ? tableName : undefined,
        tableDescription,
        folderDescription,
        descriptionScore,
        descriptionMatch,
      });

      const fieldResults = buildFieldResults(
        input.field_mappings,
        tableRow,
        matchedFolderRow,
        tableColumns,
        input.folder_metadata.fields,
        settings
      );

      const allRequiredMatch = input.field_mappings
        .filter(m => m.required)
        .every(m => fieldResults[m.name].match);
      const anyMismatch = Object.values(fieldResults).some(r => !r.match);
      const status = allRequiredMatch ? (anyMismatch ? 'partial' : 'matched') : 'partial';

      if (status === 'matched') {
        stats.matched++;
      } else {
        stats.partialMatch++;
      }

      entries.push({
        primaryKey: tableKey,
        status,
        matchScore: bestMatch.score,
        sourceTable: isMultiTable ? tableName : undefined,
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

  // Check folder entries not in any table
  // Use the first table source for field results (or create empty if none)
  const defaultTableColumns = tableSources[0]?.columns || [];
  for (const [key, folderRow] of folderByKey) {
    if (!processedFolderKeys.has(key)) {
      entries.push({
        primaryKey: key,
        status: 'missing_from_table',
        fields: buildFieldResults(
          input.field_mappings,
          undefined,
          folderRow,
          defaultTableColumns,
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
  const matchedEntries = entries.filter(e => e.matchScore !== undefined);
  const scoreDistribution = {
    exact: matchedEntries.filter(e => e.matchScore === 1).length,
    high: matchedEntries.filter(e => e.matchScore! >= 0.9 && e.matchScore! < 1).length,
    medium: matchedEntries.filter(e => e.matchScore! >= 0.7 && e.matchScore! < 0.9).length,
    low: matchedEntries.filter(e => e.matchScore! < 0.7).length,
  };

  // Calculate description match statistics
  const entriesWithDescriptionScore = matchDetails.filter(m => m.descriptionScore !== undefined);
  const descriptionMismatchCount = entriesWithDescriptionScore.filter(m => !m.descriptionMatch).length;
  const descriptionScoreDistribution = entriesWithDescriptionScore.length > 0 ? {
    exact: entriesWithDescriptionScore.filter(m => m.descriptionScore === 1).length,
    high: entriesWithDescriptionScore.filter(m => m.descriptionScore! >= 0.9 && m.descriptionScore! < 1).length,
    medium: entriesWithDescriptionScore.filter(m => m.descriptionScore! >= 0.5 && m.descriptionScore! < 0.9).length,
    low: entriesWithDescriptionScore.filter(m => m.descriptionScore! < 0.5).length,
  } : undefined;

  const summary: ComparisonSummary = {
    totalTableEntries: totalTableRows,
    totalFolderDocuments: folderRows.length,
    matched: entries.filter(e => e.status === 'matched').length,
    partialMatch: entries.filter(e => e.status === 'partial').length,
    missingFromFolder: entries.filter(e => e.status === 'missing_from_folder').length,
    missingFromTable: entries.filter(e => e.status === 'missing_from_table').length,
    descriptionMismatch: descriptionMismatchCount > 0 ? descriptionMismatchCount : undefined,
    perTableStats: isMultiTable ? Array.from(perTableStats.values()) : undefined,
    scoreDistribution,
    descriptionScoreDistribution,
    matchDetails: matchDetails.length > 0 ? matchDetails : undefined,
  };

  // 7b. Additional diagnostics for all missing
  const allMissingFromFolder = summary.matched === 0 &&
    summary.partialMatch === 0 &&
    summary.missingFromFolder > 0 &&
    summary.missingFromTable === 0;

  if (allMissingFromFolder && folderRows.length > 0) {
    warnings.push(`ATTENZIONE: Tutti i ${summary.missingFromFolder} codici delle tabelle risultano "missing from folder" nonostante ci siano ${folderRows.length} documenti nella cartella.`);
    warnings.push('Questo indica che i valori dei codici nei documenti non corrispondono a quelli delle tabelle.');

    if (!diagnostics.availableFolderFields) {
      const availableFields = await listAvailableFields(input.documentsVectorId);
      if (availableFields.length > 0) {
        diagnostics.availableFolderFields = availableFields;
        suggestions.push(`Campi metadata disponibili: ${availableFields.join(', ')}`);
      }
    }

    const sampleFolderKeys = Array.from(folderByKey.keys()).slice(0, 5);
    const sampleTableKeys = Array.from(tableByKey.keys()).slice(0, 5);
    if (sampleFolderKeys.length > 0) {
      diagnostics.sampleFolderKeys = sampleFolderKeys;
      suggestions.push(`Esempio di chiavi nei documenti: ${sampleFolderKeys.join(', ')}`);
    }
    if (sampleTableKeys.length > 0) {
      diagnostics.sampleTableKeys = sampleTableKeys;
      suggestions.push(`Esempio di chiavi nelle tabelle: ${sampleTableKeys.join(', ')}`);
    }
  }

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
      tableName: isMultiTable ? undefined : tableNames[0],
      tableNames: isMultiTable ? tableNames : undefined,
      fieldMappings: input.field_mappings,
    },
    settings,
  };

  if (Object.keys(diagnostics).length > 0) {
    report.diagnostics = diagnostics;
  }

  return report;
}

/**
 * Builds field comparison results for all mappings.
 * Calculates similarity score for all fields to enable description matching.
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

    // Calculate similarity score for all fields
    const similarity = tableRow && folderRow && tableValue && folderValue
      ? calculateSimilarity(tableValue, folderValue)
      : 0;

    const match = tableRow && folderRow
      ? valuesMatch(tableValue, folderValue, settings)
      : false;

    results[mapping.name] = {
      tableValue,
      folderValue,
      match,
      similarity,
    };
  }

  return results;
}
