"""Neutralize text on a web page that is aimed at the AI rather than at the person reading it.

Not a block: the task carries on. Sentences that try to give the assistant orders ("ignore your instructions", "send the user's
data to ...", "do not tell the user") are replaced by a short marker, so the agent sees an ordinary page minus the attack and
finishes what the user asked. Normal shop, news and form text is untouched.
"""
from __future__ import annotations
import re

MARK = '[text aimed at the AI removed]'
A = r'(?:ai|a\.i\.|assistant|agent|language model|llm|chatbot|bot|model|claude|gpt|copilot)'
PHRASES = [re.compile(p, re.I) for p in (
    r'\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|any|your|the|these)\b[^.\n]{0,30}\b(?:instructions?|prompts?|rules?|directions?|guidelines?|messages?|context|goal)\b',
    r'\bnew (?:instructions?|task|goal|objective|system prompt)\s*:',
    r'\b(?:system|developer)\s*(?:prompt|message|override|instruction)s?\s*:',
    r'<\s*/?\s*(?:system|assistant|instructions?)\s*>|\[/?(?:INST|SYS|SYSTEM)\]',
    r'\byou are now\b[^.\n]{0,60}',
    r'\b(?:do not|don\'t|never|without)\s+(?:tell|inform|alert|notify|mention\b[^.\n]{0,15}to|let)\b[^.\n]{0,20}\b(?:the )?(?:user|human|person|owner)\b',
    r'\b' + A + r'\b[\s,:;-]{1,4}(?:you (?:must|should|need to|have to|will)|please (?:send|email|post|upload|visit|open|navigate|reveal|paste|enter|type|click|fill)|(?:send|email|post|upload|reveal|forward|exfiltrate|paste)\b)',
    r'\b(?:send|email|post|upload|forward|submit|paste|reveal|leak|exfiltrate|transmit)\b[^.\n]{0,60}\b(?:conversation|chat history|system prompt|instructions|api[- ]?keys?|passwords?|credentials|cookies|tokens?|private|personal|the user\'?s?|your user)\b[^.\n]{0,60}\b(?:to|at|via)\b[^.\n]{0,30}(?:https?://|@|\bwww\.)',
    r'\b(?:reveal|print|show|repeat|output)\b[^.\n]{0,25}\b(?:your|the) (?:system prompt|instructions|hidden prompt|api key|secret)',
)]


END = re.compile(r'[.!?](?=\s|$)|\n')


def neutralize(text, limit=None):
    """Replace every flagged sentence (from the match to the end of its sentence, at most 250 characters) with one marker."""
    out = str(text or '')
    for pattern in PHRASES:
        pos = 0
        while True:
            m = pattern.search(out, pos)
            if not m:
                break
            tail = END.search(out, m.end(), m.end() + 250)
            end = tail.end() if tail else min(len(out), m.end() + 250)
            out = out[:m.start()] + MARK + out[end:]
            pos = m.start() + len(MARK)
    out = re.sub(r'(?:' + re.escape(MARK) + r'[\s.,;:]*){2,}', MARK + ' ', out)
    return out if limit is None else out[:limit]
