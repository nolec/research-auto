import copy

import pytest

from src.extraction.broad_discovery import build


def snapshot():
    arms={k:{'cap':2,'queries':['test']} for k in ('time_burden','recurring_purchase','struggle','alternative_dissatisfaction')}
    row={'arm':'recurring_purchase','url':'https://www.airtasker.com/tasks/a-task-xabc123/','published_date':None,'date_precision':'RELATIVE','access':'DIRECT_OPEN','role':'buyer','domain':'household','problem_key':'recurring-cleaning','problem':'Recurring household work','summary':'Test observation','recurrence':'RECURRING_TASK','budget':{'low':100,'high':100,'currency':'AUD','unit':'fixed'}}
    return {'as_of':'2026-11-22','arms':arms,'records':[row]}


def test_empty_arms_and_non_tech_candidates_are_preserved():
    result=build(snapshot()); c=result['candidates'][0]
    assert result['arms']['alternative_dissatisfaction']['selected']==0
    assert result['domains']=={'household':1}
    assert c['recurring_requests']==c['budget_requests']==1 and c['recent_day_only']==0
    assert c['decision']=='HOLD' and c['payment']=='UNKNOWN' and result['official_top20'] is None


def test_duplicates_and_arm_limit():
    s=snapshot(); s['records'].append(copy.deepcopy(s['records'][0]))
    with pytest.raises(ValueError,match='Duplicate'): build(s)
    s['arms']['recurring_purchase']['cap']=1
    with pytest.raises(ValueError,match='cap'): build(s)


def test_stale_and_due_date_not_publication():
    s=snapshot(); s['records'][0].update(date_precision='DAY',published_date='2026-08-01')
    assert build(s)['candidates']==[]
    s['records'][0].update(date_precision='RELATIVE',published_date='2026-11-21')
    with pytest.raises(ValueError): build(s)
