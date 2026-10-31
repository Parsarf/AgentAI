import type { Block, BlockType } from '../schemas';
export type B<T extends BlockType> = Extract<Block, { type: T }>;
export interface P<T extends BlockType> { block: B<T> }
export const cx = (...c: Array<string | false | undefined | null>) => c.filter(Boolean).join(' ');
