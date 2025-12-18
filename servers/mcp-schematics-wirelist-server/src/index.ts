#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, Tool } from '@modelcontextprotocol/sdk/types.js';
import dotenv from 'dotenv';
import { ExtractWirelistSchema, zodToJsonSchema } from './schema.js';
import { extractWirelistToExcel } from './extraction.js';
import { ZodError } from 'zod';

dotenv.config();

const server = new Server({
  name: 'schematics-wirelist-mcp',
  version: '0.1.0'
}, {
  capabilities: {
    tools: {}
  }
});

const tools: Tool[] = [
  {
    name: 'extract_wirelist',
    description: 'Estrae lista fili e distinta componenti da schemi elettrici (PDF/immagini) e genera un Excel multi-foglio.',
    inputSchema: zodToJsonSchema(ExtractWirelistSchema)
  }
];

server.setRequestHandler(ListToolsRequestSchema, async () => {
  process.stderr.write('Wirelist MCP: tool list requested\n');
  return { tools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  // Extract invocation ID from MCP request for progress tracking
  const invocationId = (request.params as any)._meta?.progressToken ||
                       (request as any).id ||
                       `call_${Date.now()}`;

  if (name !== 'extract_wirelist') {
    throw new Error(`Unknown tool: ${name}`);
  }

  try {
    const validated = ExtractWirelistSchema.parse({
      ...args,
      invocation_id: (args as any)?.invocation_id || invocationId
    });
    const result = await extractWirelistToExcel(validated);

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }
      ]
    };
  } catch (error: any) {
    if (error instanceof ZodError) {
      return {
        content: [
          {
            type: 'text',
            text: `Validation error:\n${error.errors.map(e => `- ${e.path.join('.')}: ${e.message}`).join('\n')}`
          }
        ]
      };
    }

    const message = `Errore eseguendo ${name}: ${error.message}`;
    process.stderr.write(message + '\n');
    return {
      content: [
        {
          type: 'text',
          text: message
        }
      ]
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write('Schematics Wirelist MCP server in ascolto su stdio\n');
}

main().catch(err => {
  process.stderr.write(`Fatal error: ${err.message}\n`);
  process.exit(1);
});
