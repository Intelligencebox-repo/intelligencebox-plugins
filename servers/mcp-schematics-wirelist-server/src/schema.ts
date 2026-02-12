import { z } from 'zod';

export const ExtractWirelistSchema = z.object({
  file_path: z.string().min(1, 'file_path is required')
    .describe('Percorso assoluto del file PDF dello schema elettrico da analizzare. Usa il path del file allegato o caricato dall\'utente.'),
  panel_id: z.string().min(1, 'panel_id è obbligatorio (es. "+A1")')
    .describe('Identificativo del quadro elettrico (es. "+A1", "+QE1"). Se non specificato dall\'utente, usa "+A1" come default.'),
  output_excel_path: z.string().optional()
    .describe('Percorso dove salvare il file Excel risultante. Se omesso viene generato automaticamente nella stessa cartella del PDF.'),
  project: z.string().optional()
    .describe('Nome del progetto (opzionale, inserito nell\'intestazione Excel).'),
  note: z.string().optional()
    .describe('Note aggiuntive da includere nel file Excel.'),
  start_page: z.number().int().positive().default(1).optional()
    .describe('Pagina iniziale da cui partire l\'estrazione (default: 1).'),
  end_page: z.number().int().positive().optional()
    .describe('Ultima pagina da analizzare. Se omesso, analizza fino alla fine del PDF.'),
  max_pages: z.number().int().positive().max(1000).optional()
    .describe('Numero massimo di pagine da elaborare (default: 300).'),
  use_vision: z.boolean().default(true).optional()
    .describe('Usa il modello vision per analizzare le immagini delle pagine (default: true).'),
  add_raw_text_sheet: z.boolean().default(true).optional()
    .describe('Aggiunge un foglio con il testo grezzo estratto da ogni pagina (default: true).'),
  model: z.string().optional()
    .describe('Override del modello vision da usare (default da env OPENROUTER_MODEL).'),
  invocation_id: z.string().optional()
    .describe('ID univoco della chiamata per il tracking del progresso (generato automaticamente).'),
  generate_graph: z.boolean().default(false).optional()
    .describe('Genera un grafo visuale delle connessioni tra componenti (default: false).'),
  graph_format: z.enum(['dot', 'json', 'html', 'all']).default('html').optional()
    .describe('Formato del grafo: dot, json, html o all (default: html).'),
  debug_output_folder: z.string().optional()
    .describe('Cartella dove salvare immagini e JSON di debug per ogni pagina.')
});

export type ExtractWirelistInput = z.infer<typeof ExtractWirelistSchema>;

export function zodToJsonSchema(schema: z.ZodSchema): any {
  const def = (schema as any)._def;

  switch (def.typeName) {
    case 'ZodString':
      return { type: 'string', description: def.description };
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
        description: def.description
      };
    case 'ZodEnum':
      return {
        type: 'string',
        enum: def.values,
        description: def.description
      };
    case 'ZodObject': {
      const properties: Record<string, unknown> = {};
      const required: string[] = [];

      for (const [key, value] of Object.entries(def.shape())) {
        const propSchema = zodToJsonSchema(value as z.ZodSchema);
        properties[key] = propSchema;
        if (propSchema.required !== false) {
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
