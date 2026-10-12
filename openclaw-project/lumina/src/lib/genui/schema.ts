// Mirrors platform/agentai_platform/genui/schema.py. The server is authoritative; this lets the UI reject anything unexpected
// before drawing it (unknown keys, unknown field types, oversized trees) and fall back to a read-only summary.
import { z } from 'zod';

const id = z.string().regex(/^[a-z][a-z0-9_-]{0,47}$/);
const text = (max: number, min = 1) => z.string().min(min).max(max);

const option = z.object({ label: text(80), value: id }).strict();
const showIf = z.object({ field: id, equals: z.union([z.string(), z.boolean(), z.number()]) }).strict();
const field = z.object({
  id, type: z.enum(['select', 'radio', 'segmented', 'toggle', 'checkbox', 'slider', 'number', 'text', 'textarea']), label: text(120),
  help: text(240).optional(), options: z.array(option).min(2).max(12).optional(), default: z.union([z.string(), z.boolean(), z.number()]).optional(),
  min: z.number().optional(), max: z.number().optional(), step: z.number().optional(), unit: text(12).optional(), required: z.boolean().optional(), showIf: showIf.optional(),
}).strict();

export const formSpec = z.object({
  schemaVersion: z.literal('1.0'), type: z.literal('form'), title: text(120), description: text(400).optional(),
  fields: z.array(field).min(1).max(30), submit: z.object({ label: text(40), action: z.literal('submit_requirements') }).strict(),
}).strict();

export const phase = z.object({
  id, title: text(80), description: z.string().max(1000), enabled: z.boolean(), optional: z.boolean(), requiresApproval: z.boolean(), dependsOn: z.array(z.string()).max(25),
}).strict();
export const planSpec = z.object({
  schemaVersion: z.literal('1.0'), type: z.literal('task_plan'), title: text(120), summary: text(600).optional(), phases: z.array(phase).min(1).max(25),
}).strict();

export type FormSpec = z.infer<typeof formSpec>;
export type FormField = z.infer<typeof field>;
export type Phase = z.infer<typeof phase>;
export type Plan = z.infer<typeof planSpec>;
export type Answers = Record<string, string | number | boolean>;

export interface Block {
  id: string; conversation_id: string; anchor_message_id: number | null; kind: 'form' | 'task_plan'; schema_version: string;
  spec: unknown; state: any; version: number; status: 'draft' | 'submitted' | 'launched' | 'superseded'; launched_request_id: string | null;
}
