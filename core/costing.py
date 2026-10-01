"""The sole source of order costing formulas. All inputs must be Decimal."""
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext

ZERO = Decimal("0")
CENT = Decimal("0.01")
CONTEXT = Context(prec=28, rounding=ROUND_HALF_UP)


def calculate_costing(*, gross_wt, dia_ct, other_wt, purity, gold_rate, lab_rate,
                      diamond_value, inr_sold, ship_charges=ZERO, platform_fees_inr=ZERO):
    inputs = locals().copy()
    for name, value in inputs.items():
        if not isinstance(value, Decimal):
            raise TypeError(f"{name} must be a Decimal.")
        if not value.is_finite() or value < ZERO:
            raise ValueError(f"{name} must be a finite, nonnegative number.")
    if not Decimal("0.0001") <= purity <= Decimal("1"):
        raise ValueError("Purity must be between 0.0001 and 1.")
    with localcontext(CONTEXT):
        net_wt = gross_wt - dia_ct / Decimal("5") - other_wt
        if net_wt <= ZERO:
            raise ValueError("Net weight must be greater than zero. Check the weights.")
        pure_full = net_wt * purity / Decimal("0.995")
        gold = (pure_full * gold_rate).quantize(CENT)
        labour = (net_wt * lab_rate).quantize(CENT)
        diamond = diamond_value.quantize(CENT)
        total = gold + diamond + labour
        return dict(net_wt=net_wt, pure_995_6dp=pure_full.quantize(Decimal("0.000001")),
                    gold_amount=gold, labour_amount=labour, diamond_value=diamond,
                    total_bill=total, net_earnings=inr_sold - total - ship_charges - platform_fees_inr)


COMPONENT_FIELDS = {'Gold': 'gold_amount', 'Diamond': 'diamond_value', 'Labour': 'labour_amount'}


def payment_balances(bills, posted_allocations):
    """Compute from rounded component bills and Posted allocation pairs only."""
    with localcontext(CONTEXT):
        received = {name: ZERO for name in COMPONENT_FIELDS}
        for component, amount in posted_allocations:
            received[component] += amount
        outstanding = {name: bills[name] - received[name] for name in COMPONENT_FIELDS}
        total_bill = sum(bills.values(), ZERO)
        total_received = sum(received.values(), ZERO)
        total_outstanding = total_bill - total_received
        status = 'Unpaid' if total_received == ZERO else 'Paid' if total_outstanding == ZERO and total_bill > ZERO else 'Partially Paid'
        if total_outstanding < ZERO:
            status = f'Paid (credit {-total_outstanding:,.2f})'
        return {'components': [{'name': name, 'bill': bills[name], 'received': received[name], 'outstanding': outstanding[name]} for name in COMPONENT_FIELDS],
                'received': received, 'outstanding': outstanding, 'total_bill': total_bill,
                'total_received': total_received, 'total_outstanding': total_outstanding, 'status': status}


def split_automatically(amount, outstanding):
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < ZERO:
        raise ValueError('Enter a nonnegative payment amount.')
    with localcontext(CONTEXT):
        remaining = amount
        allocation = {}
        for component in COMPONENT_FIELDS:
            allocation[component] = min(remaining, max(ZERO, outstanding[component]))
            remaining -= allocation[component]
        return allocation


def gst_amount(total_bill, rate_percent):
    with localcontext(CONTEXT):
        return (total_bill * rate_percent / Decimal('100')).quantize(CENT)


def suggested_inr(usd_sold, fx_rate):
    if any(not isinstance(value, Decimal) or not value.is_finite() or value < ZERO for value in (usd_sold, fx_rate)):
        raise ValueError('Enter a finite nonnegative USD amount and exchange rate.')
    with localcontext(CONTEXT):
        return (usd_sold * fx_rate).quantize(CENT)
