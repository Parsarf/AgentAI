"""Scenario arithmetic only; never used as the task admission guard."""
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def calculate():
    inputs=json.loads((ROOT/'cost-inputs.json').read_text())
    plan=json.loads((ROOT/'plan.json').read_text());p={k:Decimal(v) for k,v in inputs['prices'].items()}
    scenarios={}
    for name,s in inputs['scenario_tokens'].items():
        cost=(Decimal(s['sonnet_input'])*p['sonnet_input_per_million']+Decimal(s['sonnet_output'])*p['sonnet_output_per_million']+Decimal(s['haiku_input'])*p['haiku_input_per_million']+Decimal(s['haiku_output'])*p['haiku_output_per_million'])/Decimal(1000000)+Decimal(s['searches'])*p['brave_search_per_request']
        scenarios[name]={'known_research_route_usd':str(cost),'illustrative_50pct_reserve_usd':str(cost*Decimal('1.5')),'complete_coding_task_usd':None}
    price=Decimal(plan['monthly_price_usd']);included=Decimal(plan['included_provider_cost_usd'])
    payment=price*(p['stripe_card_fraction']+p['stripe_billing_fraction'])+p['stripe_card_fixed']
    a={k:Decimal(v) for k,v in inputs['hypothetical_monthly_assumptions'].items()}
    variable=included+payment+sum(v for k,v in a.items() if k!='fixed_platform_cost')
    contribution=price-variable
    return {'currency':'USD','actual_complete_task_cost':None,'actual_monthly_service_cost':None,'scenarios':scenarios,'proposed_plan':{'payment_fee_domestic_card_plus_billing':str(payment),'net_after_payment_and_25usd_provider_allowance':str(price-payment-included),'hypothetical_variable_cost_per_customer':str(variable),'hypothetical_contribution_per_customer':str(contribution),'hypothetical_fixed_cost':str(a['fixed_platform_cost']),'hypothetical_break_even_customers':int((a['fixed_platform_cost']/contribution).to_integral_value(rounding=ROUND_CEILING)) if contribution>0 else None},'unknown_actuals':inputs['unknown_actuals'],'browser_comparison_task_runs':30*3*2,'hypothetical_browser_known_route_cost_180_base_runs':str(180*Decimal(scenarios['base']['known_research_route_usd'])),'browser_sample_cost_is_not_an_optimization_quote':True}

if __name__=='__main__': print(json.dumps(calculate(),indent=2))
