#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, Tool } from '@modelcontextprotocol/sdk/types.js';
import { ZodError } from 'zod';
import dotenv from 'dotenv';
import { CompareCodiciSchema, zodToJsonSchema } from './schema.js';
import { compareCodici } from './compareCodici.js';
import { listAvailableFields, listTables } from './metadataClient.js';

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
    name: 'list_document_fields',
    description: `STEP 1 - CHIAMA SEMPRE PRIMA DI compare_codici!

Elenca i campi metadata disponibili nei documenti di una collezione.
I nomi dei campi sono CASE-SENSITIVE ("Codice" ≠ "codice").

USA QUESTO TOOL PER:
- Scoprire quali campi metadata esistono nei documenti
- Trovare il nome ESATTO del campo da usare in compare_codici

PARAMETRO:
- vectorId: l'ID della cartella DOCUMENTI (quella con tanti file)

ESEMPIO RISPOSTA:
["Codice", "Descrizione", "Data", "Revisione"]

POI USA IL NOME ESATTO in compare_codici:
folder_metadata.fields[].column = "Codice"  // NON "codice"`,
    inputSchema: {
      type: 'object',
      properties: {
        vectorId: {
          type: 'string',
          description: 'VectorId della collezione documenti'
        }
      },
      required: ['vectorId']
    }
  },
  {
    name: 'list_tables',
    description: `STEP 2 - CHIAMA PRIMA DI compare_codici PER TROVARE IL NOME TABELLA!

Elenca le tabelle estratte da un PDF (lista codici / elenco elaborati).
I nomi delle tabelle sono SEMPRE DIVERSI e vanno specificati in compare_codici.

USA QUESTO TOOL PER:
- Scoprire quali tabelle sono state estratte dal PDF
- Trovare il nome ESATTO della tabella e le sue colonne

PARAMETRO:
- vectorId: l'ID della cartella LISTA CODICI (quella con il PDF)

ESEMPIO RISPOSTA:
[
  { "name": "elenco_elaborati_p1_t0", "rowCount": 109, "columns": ["codice_elaborato", "descrizione"] }
]

POI USA IL NOME ESATTO in compare_codici:
table_source.table_name = "elenco_elaborati_p1_t0"
table_source.columns[].column = "codice_elaborato"`,
    inputSchema: {
      type: 'object',
      properties: {
        vectorId: {
          type: 'string',
          description: 'VectorId della collezione lista codici'
        }
      },
      required: ['vectorId']
    }
  },
  {
    name: 'compare_codici',
    description: `STEP 3 - USA DOPO list_document_fields E list_tables!

⚠️ WORKFLOW OBBLIGATORIO:
1. PRIMA chiama list_document_fields(documentsVectorId) → ottieni nomi campi ESATTI
2. POI chiama list_tables(listaVectorId) → ottieni nome tabella e colonne ESATTE
3. INFINE chiama compare_codici con i valori corretti

COSA FA: Confronta i codici estratti dai documenti con una tabella "lista codici".

⚠️ IMPORTANTE - USA code_prefix PER FILTRARE INTESTAZIONI DI SEZIONE:
Le tabelle spesso contengono righe di intestazione/categoria come:
- DOCUMENTAZIONE TECNICA, STRUTTURALE, ENERGETICA, ANTINCENDIO, ecc.
Queste NON sono codici documento e creano falsi "missing_from_folder".

SOLUZIONE: Usa il parametro "code_prefix" con il prefisso dei codici validi.
Esempio: se i codici iniziano con "DSA" o "ABC123", usa code_prefix: "DSA" o "ABC123".
Tutte le voci che non iniziano con quel prefisso verranno filtrate automaticamente.

STRUTTURA DEI PARAMETRI:
- "name" = identificativo INTERNO (usa sempre "codice", stesso valore ovunque)
- "column" = nome REALE del campo/colonna nel database
- "code_prefix" = prefisso che i codici validi devono avere (es: "DSA", "ABC123")

TEMPLATE DA COPIARE (sostituisci i valori):
{
  "documentsVectorId": "<id documenti>",
  "listaVectorId": "<id lista>",
  "code_prefix": "<PREFISSO_CODICI_VALIDI>",
  "folder_metadata": {
    "fields": [{ "name": "codice", "column": "<CAMPO_DA_LIST_DOCUMENT_FIELDS>" }]
  },
  "table_source": {
    "table_name": "<TABELLA_DA_LIST_TABLES>",
    "columns": [{ "name": "codice", "column": "<COLONNA_DA_LIST_TABLES>" }]
  },
  "field_mappings": [{ "name": "codice", "required": true }]
}

ESEMPIO CONCRETO:
- list_document_fields restituisce: ["Codice", "Descrizione"]
- list_tables restituisce: "elenco_elaborati_2" con colonna "codice_elaborato"
- I codici validi iniziano con "DSA" (es: DSA01004-000-F-344...)
- Risultato:
{
  "documentsVectorId": "e725...",
  "listaVectorId": "454e...",
  "code_prefix": "DSA",
  "folder_metadata": { "fields": [{ "name": "codice", "column": "Codice" }] },
  "table_source": { "table_name": "elenco_elaborati_2", "columns": [{ "name": "codice", "column": "codice_elaborato" }] },
  "field_mappings": [{ "name": "codice", "required": true }]
}`,
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

  try {
    // -------------------------------------------------------------------------
    // Tool: list_document_fields
    // -------------------------------------------------------------------------
    if (name === 'list_document_fields') {
      const vectorId = (args as { vectorId: string }).vectorId;
      if (!vectorId) {
        return {
          content: [{ type: 'text', text: 'Errore: vectorId è obbligatorio' }]
        };
      }

      process.stderr.write(`[verifica-codici] Listing fields for vectorId: ${vectorId}\n`);
      const fields = await listAvailableFields(vectorId);

      if (fields.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `Nessun campo metadata trovato per vectorId: ${vectorId}\n\nPossibili cause:\n- I documenti non hanno metadata estratta\n- Il vectorId è errato\n- Esegui prima l'estrazione metadata sui documenti`
          }]
        };
      }

      return {
        content: [{
          type: 'text',
          text: `Campi metadata disponibili (${fields.length}):\n\n${fields.map(f => `- "${f}"`).join('\n')}\n\n⚠️ USA QUESTI NOMI ESATTI in compare_codici → folder_metadata.fields[].column`
        }]
      };
    }

    // -------------------------------------------------------------------------
    // Tool: list_tables
    // -------------------------------------------------------------------------
    if (name === 'list_tables') {
      const vectorId = (args as { vectorId: string }).vectorId;
      if (!vectorId) {
        return {
          content: [{ type: 'text', text: 'Errore: vectorId è obbligatorio' }]
        };
      }

      process.stderr.write(`[verifica-codici] Listing tables for vectorId: ${vectorId}\n`);
      const tables = await listTables(vectorId);

      if (tables.length === 0) {
        return {
          content: [{
            type: 'text',
            text: `Nessuna tabella trovata per vectorId: ${vectorId}\n\nPossibili cause:\n- Il PDF non ha tabelle estratte\n- Il vectorId è errato\n- Esegui prima l'estrazione tabelle sul PDF`
          }]
        };
      }

      const tableInfo = tables.map(t => {
        const cols = t.columns?.map(c => `"${c.name}"`).join(', ') || 'N/A';
        return `📋 "${t.name}" (${t.rowCount} righe)\n   Colonne: ${cols}`;
      }).join('\n\n');

      return {
        content: [{
          type: 'text',
          text: `Tabelle disponibili (${tables.length}):\n\n${tableInfo}\n\n⚠️ USA QUESTI NOMI ESATTI in compare_codici:\n- table_source.table_name = "nome_tabella"\n- table_source.columns[].column = "nome_colonna"`
        }]
      };
    }

    // -------------------------------------------------------------------------
    // Tool: compare_codici
    // -------------------------------------------------------------------------
    if (name === 'compare_codici') {
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
    }

    // Unknown tool
    throw new Error(`Unknown tool: ${name}`);

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
          text: `Error executing ${name}: ${message}`
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
