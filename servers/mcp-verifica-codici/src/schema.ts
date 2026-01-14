import { z } from 'zod';

// ============================================================================
// Field Specification Schema - supports single column OR multiple columns joined
// ============================================================================

/**
 * Defines how a field should be composed from one or more columns/fields.
 * Supports both single string or array of strings for multi-column composition.
 */
const ColumnSpecSchema = z.union([
  z.string().min(1),           // Single column: "codice"
  z.array(z.string().min(1))   // Multiple columns: ["commessa", "lotto", "fase"]
]);

// ============================================================================
// Source Field Schema - maps a display name to column(s)
// ============================================================================

export const SourceFieldSchema = z.object({
  /** Display name for this field (e.g., "codice", "descrizione") */
  name: z.string().min(1).describe('Display name for this field'),

  /** Column(s) to read. If array, values are joined with separator. */
  column: ColumnSpecSchema.describe('Column name or array of column names to join'),

  /** Separator used when joining multiple columns (default: "-") */
  separator: z.string().default('-').describe('Separator for joining multiple columns'),
});

export type SourceField = z.infer<typeof SourceFieldSchema>;

// ============================================================================
// Comparison Settings Schema
// ============================================================================

export const ComparisonSettingsSchema = z.object({
  /** Whether comparisons should be case-sensitive (default: false) */
  case_sensitive: z.boolean().default(false).describe('Case-sensitive comparison'),

  /** Whether to trim and normalize whitespace (default: true) */
  ignore_whitespace: z.boolean().default(true).describe('Trim and normalize whitespace'),

  /** Whether to treat "-" and "_" as equivalent (default: true) */
  normalize_dashes: z.boolean().default(true).describe('Treat dashes and underscores as equivalent'),

  /** Whether to allow partial string matches (default: true for fuzzy matching) */
  partial_match: z.boolean().default(true).describe('Allow partial string matches (fuzzy search)'),

  /** Skip empty/null values when comparing (default: true) */
  skip_empty: z.boolean().default(true).describe('Skip empty values in comparison'),

  /** Minimum similarity score (0-1) for fuzzy token matching (default: 0.5 = 50%) */
  similarity_threshold: z.number().min(0).max(1).default(0.5).describe('Minimum similarity score for fuzzy matching (0-1)'),
});

export type ComparisonSettings = z.infer<typeof ComparisonSettingsSchema>;

// ============================================================================
// Field Mapping for Comparison
// ============================================================================

export const FieldMappingSchema = z.object({
  /** Display name - must match a name in both folder_metadata.fields and table_source.columns */
  name: z.string().min(1).describe('Field name to compare'),

  /** If true, this field must match for overall "matched" status (default: true) */
  required: z.boolean().default(true).describe('Whether this field must match for overall success'),
});

export type FieldMapping = z.infer<typeof FieldMappingSchema>;

// ============================================================================
// Table Source Schema
// ============================================================================

/** Schema for a single table source configuration */
export const TableSourceSchema = z.object({
  /** Name of the table to query (e.g., "elaborati_generali_e_relazioni_specialistiche") */
  table_name: z.string().optional().describe('Name of the extracted table to query'),

  /** Columns to extract from the table */
  columns: z.array(SourceFieldSchema).min(1).describe('Columns to extract from the table'),
}).describe('Configuration for an extracted table source');

export type TableSource = z.infer<typeof TableSourceSchema>;

// ============================================================================
// Main Tool Input Schema
// ============================================================================

export const CompareCodiciSchema = z.object({
  /** ID of the collection containing documents with extracted metadata */
  documentsVectorId: z.string().min(1).describe('VectorId of the documents collection (folder with files)'),

  /** ID of the collection containing the lista codici PDF with extracted table */
  listaVectorId: z.string().min(1).describe('VectorId of the lista codici collection (folder with lista PDF)'),

  /** Source 1: Folder metadata (from DocumentFieldValue table) */
  folder_metadata: z.object({
    /** Fields to extract from folder metadata */
    fields: z.array(SourceFieldSchema).min(1).describe('Fields to extract from document metadata'),
  }).describe('Configuration for folder metadata source'),

  /** Source 2: Single extracted table (from VectorDataset/SQLite) - use this OR table_sources */
  table_source: TableSourceSchema.optional().describe('Configuration for single table source (use this OR table_sources)'),

  /** Source 2 alternative: Multiple extracted tables - use this OR table_source */
  table_sources: z.array(TableSourceSchema).min(1).optional().describe(
    'Configuration for multiple table sources - all tables will be queried and results aggregated'
  ),

  /** Field mappings - which fields to compare between the two sources */
  field_mappings: z.array(FieldMappingSchema).min(1).describe('Fields to compare'),

  /** Global comparison settings */
  settings: ComparisonSettingsSchema.optional().describe('Comparison settings'),

  /** Optional prefix that valid codes must start with (e.g., "DSA", "ABC123") */
  code_prefix: z.string().optional().describe(
    'Prefix that valid codes must start with. Codes not starting with this prefix will be filtered out (e.g., section headers).'
  ),
}).refine(
  (data) => data.table_source || data.table_sources,
  { message: 'Either table_source or table_sources must be provided' }
);

export type CompareCodiciInput = z.infer<typeof CompareCodiciSchema>;

// ============================================================================
// Output Types
// ============================================================================

/** Status of a single field comparison */
export interface FieldComparisonResult {
  tableValue: string;
  folderValue: string;
  match: boolean;
  /** Similarity score (0-1) for fuzzy text comparison */
  similarity?: number;
}

/** Result for a single entry (row) comparison */
export interface ComparisonEntry {
  /** The primary key value used for matching */
  primaryKey: string;

  /** Overall status of this entry */
  status: 'matched' | 'partial' | 'missing_from_folder' | 'missing_from_table';

  /** Similarity score (0-1) for fuzzy matching. Higher = better match. */
  matchScore?: number;

  /** Name of the source table this entry came from (for multi-table comparisons) */
  sourceTable?: string;

  /** Per-field comparison results */
  fields: Record<string, FieldComparisonResult>;

  /** Data from the extracted table row */
  tableRow?: Record<string, string>;

  /** Data from folder metadata */
  folderMetadata?: {
    documentId: string;
    documentName?: string;
    [field: string]: string | undefined;
  };
}

/** Match detail for verification */
export interface MatchDetail {
  tableCode: string;     // Original code from table
  folderCode: string;    // Original code from document
  score: number;         // Similarity score (0-1)
  documentName?: string; // Document filename for reference
  sourceTable?: string;  // Name of the source table (for multi-table comparisons)
  /** Description from table (lista codici) */
  tableDescription?: string;
  /** Description from document (nome_elaborato) */
  folderDescription?: string;
  /** Similarity score for description comparison (0-1) */
  descriptionScore?: number;
  /** Whether the description matches (above threshold) */
  descriptionMatch?: boolean;
}

/** Per-table statistics for multi-table comparisons */
export interface TableStats {
  tableName: string;
  totalEntries: number;
  matched: number;
  partialMatch: number;
  missingFromFolder: number;
}

/** Summary statistics */
export interface ComparisonSummary {
  totalTableEntries: number;
  totalFolderDocuments: number;
  matched: number;
  partialMatch: number;
  missingFromFolder: number;
  missingFromTable: number;
  /** Number of entries where code matched but description didn't */
  descriptionMismatch?: number;
  /** Per-table breakdown for multi-table comparisons */
  perTableStats?: TableStats[];
  /** Score distribution - count of matches in each score range */
  scoreDistribution?: {
    exact: number;      // score = 1.0
    high: number;       // score 0.9-0.99
    medium: number;     // score 0.7-0.89
    low: number;        // score < 0.7 (above threshold)
  };
  /** Description match distribution */
  descriptionScoreDistribution?: {
    exact: number;      // score = 1.0
    high: number;       // score 0.9-0.99
    medium: number;     // score 0.5-0.89
    low: number;        // score < 0.5
  };
  /** List of all matches with original codes and scores for verification */
  matchDetails?: MatchDetail[];
}

/** Diagnostic information when queries return unexpected results */
export interface DiagnosticInfo {
  /** Available metadata fields in the documents collection */
  availableFolderFields?: string[];
  /** Available tables in the lista collection */
  availableTables?: string[];
  /** Sample of normalized keys from folder metadata (for debugging mismatches) */
  sampleFolderKeys?: string[];
  /** Sample of normalized keys from table data (for debugging mismatches) */
  sampleTableKeys?: string[];
  /** Warnings or suggestions */
  warnings?: string[];
  /** Suggestions for fixing issues */
  suggestions?: string[];
  /** Number of table entries filtered out (didn't match code_prefix) */
  filteredTableEntries?: number;
}

/** Full comparison report */
export interface ComparisonReport {
  summary: ComparisonSummary;
  entries: ComparisonEntry[];
  timestamp: string;
  parameters: {
    documentsVectorId: string;
    listaVectorId: string;
    tableName?: string;        // For single table mode
    tableNames?: string[];     // For multi-table mode
    fieldMappings: FieldMapping[];
  };
  settings: ComparisonSettings;
  /** Diagnostic info when queries return 0 rows or have issues */
  diagnostics?: DiagnosticInfo;
}

// ============================================================================
// Zod to JSON Schema Converter
// ============================================================================

/**
 * Converts a Zod schema to JSON Schema format for MCP tool definitions.
 */
export function zodToJsonSchema(schema: z.ZodSchema): Record<string, unknown> {
  const def = (schema as any)._def;

  switch (def.typeName) {
    case 'ZodString':
      return {
        type: 'string',
        description: def.description,
        ...(def.checks?.find((c: any) => c.kind === 'min') && { minLength: def.checks.find((c: any) => c.kind === 'min').value })
      };

    case 'ZodNumber':
      return { type: 'number', description: def.description };

    case 'ZodBoolean':
      return { type: 'boolean', description: def.description };

    case 'ZodOptional':
      return { ...zodToJsonSchema(def.innerType), required: false };

    case 'ZodDefault':
      return { ...zodToJsonSchema(def.innerType), default: def.defaultValue() };

    case 'ZodArray':
      return {
        type: 'array',
        items: zodToJsonSchema(def.type),
        description: def.description,
        ...(def.minLength && { minItems: def.minLength.value })
      };

    case 'ZodEnum':
      return {
        type: 'string',
        enum: def.values,
        description: def.description
      };

    case 'ZodUnion': {
      // Handle union types (e.g., string | string[])
      const options = def.options.map((opt: z.ZodSchema) => zodToJsonSchema(opt));
      return {
        oneOf: options,
        description: def.description
      };
    }

    case 'ZodEffects': {
      // Handle refinements (.refine(), .transform(), etc.) - process the inner schema
      return zodToJsonSchema(def.schema);
    }

    case 'ZodObject': {
      const properties: Record<string, unknown> = {};
      const required: string[] = [];

      for (const [key, value] of Object.entries(def.shape())) {
        const propSchema = zodToJsonSchema(value as z.ZodSchema);
        properties[key] = propSchema;
        if ((propSchema as any).required !== false) {
          required.push(key);
        }
      }

      return {
        type: 'object',
        properties,
        required: required.length ? required : undefined,
        description: def.description
      };
    }

    default:
      return { type: 'any' };
  }
}
