import { createContext } from 'react';

/** What a card inside a chat may ask the chat to do. Outside a chat there is no provider, so a card stays read-only. */
export interface ChatActions { send: (message: string) => Promise<void> }
export const ChatActionsContext = createContext<ChatActions | null>(null);
