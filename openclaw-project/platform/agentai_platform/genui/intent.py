"""Deterministic intent detection and requirement templates. No model call: cheap, predictable and testable.

Returns what kind of response a message deserves: plain text, a compact requirements form, or a generated plan.
JEV could later choose among these templates; it is not needed for the decision rules below and is not used.
"""
from __future__ import annotations
import re

BUILD = re.compile(r'\b(build|create|make|develop|design|set up|setup|launch)\b', re.I)
THING = re.compile(r'\b(website|web site|landing page|web ?app|application|app|saas|platform|store|e-?commerce|portal|dashboard|system)\b', re.I)
WEBSITE = re.compile(r'\b(website|web site|landing page|web ?app|saas|store|e-?commerce|portal)\b', re.I)
HEAVY = re.compile(r'\b(complete|full|end[- ]to[- ]end|from scratch|migrat\w+|roll ?out|strategy|roadmap|launch plan|pipeline)\b', re.I)
QUESTION = re.compile(r'^\s*(what|who|when|where|why|how|is|are|can|does|do|explain|define|tell me)\b', re.I)


def detect(message: str, *, mode: str = 'auto') -> str:
    """'text' | 'requirements' | 'plan'. mode 'text' forces plain text; 'plan' forces a plan."""
    if mode == 'text':
        return 'text'
    if mode == 'plan':
        return 'plan'
    text = message.strip()
    if len(text) < 12 or (QUESTION.search(text) and not BUILD.search(text)):
        return 'text'
    if BUILD.search(text) and WEBSITE.search(text):
        return 'requirements'
    if (BUILD.search(text) and THING.search(text)) or (HEAVY.search(text) and len(text) > 40):
        return 'plan'
    return 'text'


def website_form() -> dict:
    opt = lambda *pairs: [{'label': a, 'value': b} for a, b in pairs]
    return {
        'schemaVersion': '1.0', 'type': 'form', 'title': 'Shape your website',
        'description': 'A few choices that change the plan. Everything else gets a sensible default.',
        'fields': [
            {'id': 'kind', 'type': 'segmented', 'label': 'What kind of website?', 'required': True, 'default': 'business',
             'options': opt(('Business', 'business'), ('E-commerce', 'ecommerce'), ('Portfolio', 'portfolio'), ('SaaS', 'saas'))},
            {'id': 'style', 'type': 'segmented', 'label': 'Visual style', 'default': 'minimal',
             'options': opt(('Minimal', 'minimal'), ('Modern', 'modern'), ('Futuristic', 'futuristic'))},
            {'id': 'accounts', 'type': 'toggle', 'label': 'Include user accounts and sign-in', 'default': False},
            {'id': 'payments', 'type': 'select', 'label': 'Payment provider', 'default': 'stripe', 'showIf': {'field': 'kind', 'equals': 'ecommerce'},
             'options': opt(('Stripe', 'stripe'), ('PayPal', 'paypal'), ('Decide later', 'later'))},
            {'id': 'catalog', 'type': 'slider', 'label': 'Products in the first catalog', 'min': 1, 'max': 500, 'step': 1, 'default': 20,
             'unit': 'items', 'showIf': {'field': 'kind', 'equals': 'ecommerce'}},
            {'id': 'pricing', 'type': 'toggle', 'label': 'Include a pricing page with plans', 'default': True, 'showIf': {'field': 'kind', 'equals': 'saas'}},
            {'id': 'gallery', 'type': 'toggle', 'label': 'Include a project gallery', 'default': True, 'showIf': {'field': 'kind', 'equals': 'portfolio'}},
            {'id': 'budget', 'type': 'radio', 'label': 'Effort level', 'default': 'balanced', 'help': 'Higher effort means more checking and polish, and more model usage.',
             'options': opt(('Lean', 'lean'), ('Balanced', 'balanced'), ('Thorough', 'thorough'))},
            {'id': 'notes', 'type': 'textarea', 'label': 'Anything else Lumina should know? (optional)'},
        ],
        'submit': {'label': 'Create the plan', 'action': 'submit_requirements'},
    }


def requirements_template(message: str) -> dict | None:
    return website_form() if WEBSITE.search(message) else None
