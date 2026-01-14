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

⚠️ IMPORTANTE: NON CHIEDERE GLI ID ALL'UTENTE!
Tu conosci già i vectorId delle collezioni collegate alla chat.
Usa direttamente gli ID che hai a disposizione nel contesto.

USA QUESTO TOOL PER:
- Scoprire quali campi metadata esistono nei documenti
- Trovare il nome ESATTO del campo da usare in compare_codici

PARAMETRO:
- vectorId: l'ID della cartella DOCUMENTI (usa l'ID che conosci dal contesto)

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

⚠️ IMPORTANTE: NON CHIEDERE GLI ID ALL'UTENTE!
Tu conosci già i vectorId delle collezioni collegate alla chat.
Usa direttamente gli ID che hai a disposizione nel contesto.

USA QUESTO TOOL PER:
- Scoprire quali tabelle sono state estratte dal PDF
- Trovare il nome ESATTO della tabella e le sue colonne

PARAMETRO:
- vectorId: l'ID della cartella LISTA CODICI (usa l'ID che conosci dal contesto)

ESEMPIO RISPOSTA:
[
  { "name": "elenco_elaborati_p1_t0", "rowCount": 109, "columns": ["codice_elaborato", "descrizione"] }
]

🚨 CRITICO - USA ESATTAMENTE I NOMI RESTITUITI:
- table_name = "elenco_elaborati_p1_t0"  ✅ CORRETTO
- table_name = "Table 1"                  ❌ SBAGLIATO!
- table_name = "Tabella 1"                ❌ SBAGLIATO!

NON INVENTARE NOMI! Copia-incolla esattamente il valore "name" dalla risposta.
I nomi delle colonne vanno copiati esattamente dalla lista "columns".`,
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

⚠️ IMPORTANTE: NON CHIEDERE GLI ID ALL'UTENTE!
Tu conosci già i vectorId delle collezioni collegate alla chat.
Usa direttamente gli ID che hai a disposizione nel contesto.

⚠️ WORKFLOW OBBLIGATORIO:
1. PRIMA chiama list_document_fields(documentsVectorId) → ottieni nomi campi ESATTI
2. POI chiama list_tables(listaVectorId) → ottieni nome tabella e colonne ESATTE
3. INFINE chiama compare_codici con i valori corretti

🚨🚨🚨 ERRORE COMUNE - LEGGI ATTENTAMENTE! 🚨🚨🚨
I nomi delle tabelle NON sono "Table 1", "Table 2", "Tabella 1", ecc.!
I nomi sono come: "elenco_elaborati_p1_t0", "elenco_elaborati_p2_t0", ecc.
DEVI COPIARE ESATTAMENTE i nomi restituiti da list_tables!

COSA FA: Confronta i codici E le descrizioni estratti dai documenti con una o più tabelle "lista codici".

═══════════════════════════════════════════════════════════════════════════════
📋 FUNZIONALITÀ PRINCIPALI
═══════════════════════════════════════════════════════════════════════════════

1️⃣ CONFRONTO CODICI (obbligatorio):
   Verifica che ogni codice nella lista sia presente nei documenti.

2️⃣ CONFRONTO DESCRIZIONE (opzionale ma consigliato):
   Verifica che la descrizione/titolo del documento corrisponda a quella nella lista.
   Usa fuzzy matching con similarity score (0-1).

3️⃣ SUPPORTO MULTI-TABELLA:
   Confronta i documenti con TUTTE le tabelle in una sola chiamata.
   Usa "table_sources" (array) invece di "table_source" (singolo).

═══════════════════════════════════════════════════════════════════════════════
⚠️ FILTRO INTESTAZIONI DI SEZIONE (code_prefix)
═══════════════════════════════════════════════════════════════════════════════

Le tabelle spesso contengono righe di intestazione/categoria come:
- DOCUMENTAZIONE TECNICA, STRUTTURALE, ENERGETICA, ANTINCENDIO, ecc.
Queste NON sono codici documento e creano falsi "missing_from_folder".

SOLUZIONE: Usa "code_prefix" con il prefisso dei codici validi.
Esempio: code_prefix: "PES" filtra tutto ciò che non inizia con "PES".

═══════════════════════════════════════════════════════════════════════════════
📝 TEMPLATE BASE (solo codici)
═══════════════════════════════════════════════════════════════════════════════

ATTENZIONE: "elenco_elaborati_p1_t0" è un ESEMPIO!
Usa i nomi REALI restituiti da list_tables!

{
  "documentsVectorId": "<id dal contesto>",
  "listaVectorId": "<id dal contesto>",
  "folder_metadata": {
    "fields": [
      { "name": "codice", "column": "<nome da list_document_fields>" }
    ]
  },
  "table_sources": [
    { "table_name": "<nome da list_tables>", "columns": [{ "name": "codice", "column": "<colonna da list_tables>" }] }
  ],
  "field_mappings": [
    { "name": "codice", "required": true }
  ]
}

═══════════════════════════════════════════════════════════════════════════════
📝 TEMPLATE CON VALIDAZIONE DESCRIZIONE (consigliato)
═══════════════════════════════════════════════════════════════════════════════

RICORDA: Tutti i nomi (tabelle e colonne) devono venire da list_tables!

{
  "documentsVectorId": "<id dal contesto>",
  "listaVectorId": "<id dal contesto>",
  "folder_metadata": {
    "fields": [
      { "name": "codice", "column": "<campo codice da list_document_fields>" },
      { "name": "descrizione", "column": "<campo descrizione da list_document_fields>" }
    ]
  },
  "table_sources": [
    {
      "table_name": "<NOME ESATTO da list_tables, es: elenco_elaborati_p1_t0>",
      "columns": [
        { "name": "codice", "column": "<colonna codice da list_tables>" },
        { "name": "descrizione", "column": "<colonna descrizione da list_tables>" }
      ]
    }
  ],
  "field_mappings": [
    { "name": "codice", "required": true },
    { "name": "descrizione", "required": false }
  ]
}

⚠️ NOTA IMPORTANTE:
- Ogni tabella può avere colonne con nomi DIVERSI
- La colonna "descrizione" spesso ha nomi lunghi tipo "elaborati_generali_e_relazioni_specialistiche"
- NON inventare i nomi! Copiali ESATTAMENTE da list_tables

═══════════════════════════════════════════════════════════════════════════════
📊 OUTPUT DEL REPORT
═══════════════════════════════════════════════════════════════════════════════

Il report include:
- summary.matched: codici trovati
- summary.missingFromFolder: codici nella lista ma documenti non esistono
- summary.missingFromTable: documenti non nella lista
- summary.descriptionMismatch: codici OK ma descrizione NON corrisponde
- summary.descriptionScoreDistribution: distribuzione similarity descrizioni
- matchDetails[]: dettaglio di ogni match con:
  - tableCode, folderCode, score
  - tableDescription, folderDescription, descriptionScore, descriptionMatch`,
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
