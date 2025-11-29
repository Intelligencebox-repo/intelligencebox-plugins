import { z } from 'zod';

export const ExtractWirelistSchema = z.object({
  file_path: z.string().min(1, 'file_path is required'),
  output_excel_path: z.string().optional(),
  project: z.string().optional(),
  note: z.string().optional(),
  start_page: z.number().int().positive().default(1).optional(),
  end_page: z.number().int().positive().optional(),
  max_pages: z.number().int().positive().max(1000).default(3).optional(),
  use_vision: z.boolean().default(true).optional(),
  add_raw_text_sheet: z.boolean().default(true).optional(),
  model: z.string().optional()
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
