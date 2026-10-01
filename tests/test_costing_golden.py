import json
from decimal import Decimal, localcontext, ROUND_DOWN
from pathlib import Path
import pytest
from core.costing import calculate_costing

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / 'oms-pack' / 'golden_cases.json').read_text())


@pytest.mark.parametrize('case', GOLDEN['calc_cases'], ids=lambda case: str(case['sales_no']))
def test_costing_golden(case):
    result = calculate_costing(**{name: Decimal(value) for name, value in case['inputs'].items()})
    assert result == {name: Decimal(value) for name, value in case['expected'].items()}


def inputs(**overrides):
    return {**{name: Decimal(value) for name, value in GOLDEN['calc_cases'][0]['inputs'].items()}, **overrides}


@pytest.mark.parametrize('weight', ['0', '1.512', '1'])
def test_nonpositive_net_weight(weight):
    with pytest.raises(ValueError, match='Net weight'):
        calculate_costing(**inputs(gross_wt=Decimal(weight)))


@pytest.mark.parametrize('value', [Decimal('-1'), Decimal('NaN'), Decimal('Infinity')])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        calculate_costing(**inputs(gold_rate=value))


def test_float_rejected():
    with pytest.raises(TypeError):
        calculate_costing(**inputs(gold_rate=15000.0))


def test_context_isolated_and_half_up():
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.rounding = ROUND_DOWN
        result = calculate_costing(**inputs(diamond_value=Decimal('1.005')))
        assert result['diamond_value'] == Decimal('1.01')
        assert result['gold_amount'] == Decimal('24469.75')
        assert ctx.prec == 6
        assert ctx.rounding == ROUND_DOWN


def test_platform_fees_and_loss():
    result = calculate_costing(**inputs(inr_sold=Decimal('0'), platform_fees_inr=Decimal('12.34')))
    assert result['net_earnings'] == Decimal('-120632.09')
