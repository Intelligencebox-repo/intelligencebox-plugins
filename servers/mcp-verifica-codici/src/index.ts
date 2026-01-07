#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, Tool } from '@modelcontextprotocol/sdk/types.js';
import { ZodError } from 'zod';
import dotenv from 'dotenv';
import { CompareCodiciSchema, zodToJsonSchema } from './schema.js';
import { compareCodici } from './compareCodici.js';

dotenv.config();

// ============================================================================
// MCP Server Setup
// ============================================================================

const server = new Server({
  name: 'verifica-codici',
  version: '2.0.0'
}, {
  capabilities: {
    tools: {}
  }
});

// ============================================================================
// Tool Definitions
// ============================================================================

const tools: Tool[] = [
  {
    name: 'compare_codici',
    description: `QUANDO USARE: Usa questo strumento quando l'utente chiede di verificare, controllare o confrontare codici tra documenti e una lista codici.

COSA FA: Confronta i codici estratti dai documenti (metadata) con una tabella "lista codici" estratta da un PDF.

RICHIEDE DUE COLLEZIONI DIVERSE (guarda le raccolte allegate alla chat):
1. documentsVectorId = la cartella con TANTI FILE (documenti da verificare, con metadata estratta)
2. listaVectorId = la cartella con il PDF "lista codici" o "elenco elaborati" (deve avere tabelle estratte)

IMPORTANTE - table_name: Se la tabella estratta NON si chiama "main_table", DEVI specificare table_name:
{
  "table_source": {
    "table_name": "nome_tabella_esatto",  // <-- OBBLIGATORIO se non c'è main_table
    "columns": [...]
  }
}

PRIMA DI USARE IL TOOL:
1. Verifica che la cartella documenti abbia i campi metadata necessari (es. "codice", "Codice", etc.)
2. Verifica che la cartella lista abbia tabelle estratte - usa tabular_query per vedere le tabelle disponibili

ESEMPIO COMPLETO:
{
  "documentsVectorId": "<vectorId cartella documenti>",
  "listaVectorId": "<vectorId cartella lista>",
  "folder_metadata": { "fields": [{ "name": "codice", "column": "Codice" }] },
  "table_source": {
    "table_name": "nome_tabella_estratta",
    "columns": [{ "name": "codice", "column": "codice_elaborato" }]
  },
  "field_mappings": [{ "name": "codice", "required": true }]
}

ERRORI COMUNI:
- "0 rows returned" dalla cartella documenti = il campo metadata non esiste, verifica i nomi dei campi disponibili
- "Query must reference dataset tables" = manca table_name o è sbagliato, specifica il nome esatto della tabella`,
    inputSchema: zodToJsonSchema(CompareCodiciSchema) as { type: 'object'; properties?: Record<string, object>; required?: string[] }
  }
];

// ============================================================================
// Request Handlers
// ============================================================================

server.setRequestHandler(ListToolsRequestSchema, async () => {
  process.stderr.write('[verifica-codici] Tool list requested\n');
  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name !== 'compare_codici') {
    throw new Error(`Unknown tool: ${name}`);
  }

  try {
    process.stderr.write(`[verifica-codici] Executing compare_codici\n`);

    // Validate input
    const validated = CompareCodiciSchema.parse(args);

    // Execute comparison
    const result = await compareCodici(validated);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }
      ]
    };
  } catch (error: unknown) {
    if (error instanceof ZodError) {
      const errorMessage = error.errors
        .map(e => `- ${e.path.join('.')}: ${e.message}`)
        .join('\n');

      return {
        content: [
          {
            type: 'text',
            text: `Validation error:\n${errorMessage}`
          }
        ]
      };
    }

    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`[verifica-codici] Error: ${message}\n`);

    return {
      content: [
        {
          type: 'text',
          text: `Error executing compare_codici: ${message}`
        }
      ]
    };
  }
});

// ============================================================================
// Main Entry Point
// ============================================================================

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write('[verifica-codici] MCP server listening on stdio\n');
}

main().catch(err => {
  process.stderr.write(`[verifica-codici] Fatal error: ${err.message}\n`);
  process.exit(1);
});
