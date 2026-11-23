import copy

import pytest

from src.extraction.fresh_buyer_intake import screen


def snapshot():
    row={'arm':'quality','url':'https://www.upwork.com/freelance-jobs/apply/Example_~123/','date_precision':'DAY','published_date':'2026-11-10','access':'DIRECT_BLOCKED','fit':'direct','budget':{'low':10,'high':20,'currency':'USD','unit':'fixed'}}
    return {'as_of':'2026-11-22','arms':{'quality':5},'records':[row]}


def test_recent_budget_is_not_payment_or_independence():
    result=screen(snapshot()); s=result['summary']['quality']; r=result['records'][0]
    assert s['recent_day_only_direct']==1 and s['direct_with_budget']==1
    assert s['verified_payments']==s['direct_with_confirmed_independence']==s['official_recent_cases']==0
    assert r['actual_payment']=='UNKNOWN' and s['decision']=='HOLD'


def test_dedup_ignores_slug_and_tracks_cap():
    s=snapshot(); r=copy.deepcopy(s['records'][0]); r['url']='https://www.upwork.com/freelance-jobs/apply/Changed-Title_~123/?tracking=x'; s['records'].append(r)
    assert screen(s)['records'][1]['disposition']=='DUPLICATE_ID'
    s['arms']['quality']=1
    with pytest.raises(ValueError,match='cap'): screen(s)


def test_relative_date_and_stale_are_not_recent():
    s=snapshot(); s['records'][0].update(published_date='2026-08-01'); assert screen(s)['records'][0]['disposition']=='STALE_OR_FUTURE'
    s['records'][0].update(date_precision='RELATIVE',published_date=None); assert screen(s)['records'][0]['freshness']=='UNKNOWN'
    s['records'][0]['published_date']='2026-11-20'
    with pytest.raises(ValueError,match='exact date'): screen(s)


def test_reject_seller_catalog_or_missing_project_id():
    s=snapshot(); s['records'][0]['url']='https://www.upwork.com/services/product/test'
    with pytest.raises(ValueError): screen(s)


def test_duplicate_description_family_and_recurrence_do_not_establish_independence():
    s=snapshot(); r=s['records'][0]; r.update(possible_duplicate_family='same',recurrence='RECURRING_TASK',contract_signal='AWARDED_DISPLAYED')
    duplicate=copy.deepcopy(r); duplicate['url']='https://www.upwork.com/freelance-jobs/apply/Other_~456/'; s['records'].append(duplicate)
    summary=screen(s)['summary']['quality']
    assert summary['direct']==2 and summary['direct_description_families']==1
    assert summary['direct_recurring_task_families']==summary['direct_contract_signal_families']==1
    assert summary['verified_payments']==summary['direct_with_confirmed_independence']==0


def test_explicit_historical_relative_age_excludes_without_inventing_date():
    s=snapshot(); s['records'][0].update(date_precision='RELATIVE',published_date=None,reported_age_band='CLEARLY_OLDER_THAN_90D')
    row=screen(s)['records'][0]
    assert row['disposition']=='STALE_OR_FUTURE' and row['published_date'] is None
    s['records'][0]['url']='https://www.freelancer.com/projects/test'
    with pytest.raises(ValueError): screen(s)
