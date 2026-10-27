"""The website-requirements form (a template). Nothing here guesses what a message means: the assistant reads every message itself, and Plan mode is chosen by the customer
(or offered to them by the assistant when a request is a big build)."""
from __future__ import annotations


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

