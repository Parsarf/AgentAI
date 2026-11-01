import { describe, expect, it } from 'vitest';
import { foldTrail } from './trail';
import type { Message } from './conversations';

const you = (id: number, request_id: string): Message => ({ id, request_id, provenance: 'customer', content: 'hi', created_at: '' }) as Message;
const bot = (id: number, request_id: string | null, content = `m${id}`): Message => ({ id, request_id, provenance: 'agent', content, created_at: '' }) as Message;
const done = () => true;

describe('folding the steps before a final answer', () => {
  it('hides every earlier assistant message of a finished request and keeps the last', () => {
    const { hidden, skip } = foldTrail([you(1, 'r'), bot(2, 'r'), bot(3, 'r'), bot(4, 'r')], done);
    expect([...skip]).toEqual([2, 3]);
    expect(hidden.get(2)!.map(m => m.id)).toEqual([2, 3]);       // the button goes where the first folded message was
    expect(skip.has(4)).toBe(false);
  });
  it('shows everything while the request is still running', () => {
    expect(foldTrail([you(1, 'r'), bot(2, 'r'), bot(3, 'r')], () => false).skip.size).toBe(0);
  });
  it('leaves a single answer alone', () => {
    expect(foldTrail([you(1, 'r'), bot(2, 'r')], done).skip.size).toBe(0);
  });
  it('keeps requests apart', () => {
    const { hidden } = foldTrail([you(1, 'a'), bot(2, 'a'), bot(3, 'a'), you(4, 'b'), bot(5, 'b'), bot(6, 'b')], done);
    expect([...hidden.keys()]).toEqual([2, 5]);
  });
  it('never folds a message that carries a block or a file', () => {
    const { skip } = foldTrail([bot(2, 'r'), bot(3, 'r'), bot(4, 'r')], done, m => m.id === 3);
    expect([...skip]).toEqual([2]);
  });
  it('ignores messages with no request', () => {
    expect(foldTrail([bot(1, null), bot(2, null)], done).skip.size).toBe(0);
  });
});
