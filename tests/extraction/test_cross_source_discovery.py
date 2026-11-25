import json
from datetime import date
from pathlib import Path

import pytest

from src.extraction import candidate_assessment, economic_signals_v7


def _with_link_review(call, unsupported_groups=()):
    def reviewed_call(stage, items, prompt, schema):
        if stage != 'source-link-review':
            return call(stage, items, prompt, schema)
        return {'document_id': stage, 'reviews': [
            {'link_index': index, 'group_id': group['id'],
             'state': 'UNSUPPORTED' if group['id'] in unsupported_groups else 'SUPPORTED',
             'reason': 'Source purpose checked.'}
            for index, link in enumerate(items['links']) for group in link['groups']
        ]}

    return reviewed_call


def packet():
    records = [
        {'id': 'brief', 'role': 'buyer', 'url': 'https://jobs.example/brief',
         'published_date': '2026-11-01', 'summary': 'Convert Word to Kindle EPUB with a clickable TOC. Budget $30.'},
        {'id': 'author', 'role': 'user', 'url': 'https://posts.example/book',
         'published_date': '2026-11-02', 'summary': 'My Word TOC was missing from Kindle.',
         'followup': 'Regenerating the EPUB fixed it.'},
        {'id': 'print', 'role': 'buyer', 'url': 'https://jobs.example/print',
         'published_date': '2026-11-03', 'summary': 'Deliver a print-ready PDF for my paperback.'},
    ]
    observations = [
        (records[0], 'problem', 'Convert Word to Kindle EPUB with a clickable TOC.'),
        (records[0], 'willingness_to_pay', 'Budget $30.'),
        (records[1], 'problem', 'My Word TOC was missing from Kindle.'),
        (records[1], 'alternative', 'Regenerating the EPUB fixed it.'),
    ]
    return {
        'as_of': '2026-11-24', 'records': records, 'reviewer': 'source review',
        'evidence': [
            {'evidence_id': f'{record["id"]}:{kind}', 'document_id': record['id'], 'source_url': record['url'],
             'published_at': record['published_date'] + 'T00:00:00Z', 'author_hash': record['id'],
             'community': record['role'], 'evidence_group_id': record['role'], 'kind': kind, 'quote': quote,
             'interpretation': 'Checked on the source.', 'confidence': 1}
            for record, kind, quote in observations
        ],
    }


def model(multitask=False, separate=False, unsupported=False):
    def call(stage, items, prompt, schema):
        if stage == 'tasks':
            assert all('candidate_id' not in row for row in items)
            return {'document_id': stage, 'records': [
                {'source_id': row['id'], 'tasks': [
                    {'description': row['summary'].split('.')[0], 'field': 'summary',
                     'evidence': row['summary'].split('.')[0] + '.'},
                    *([{'description': 'Book cover', 'field': 'summary', 'evidence': 'Budget $30.'}]
                       if multitask and row['id'] == 'brief' else []),
                ]}
                for row in items
            ]}
        if stage == 'groups':
            by_source = {row['source_id']: row['id'] for row in reversed(items)}
            groups = [('EPUB TOC', [by_source['brief'], by_source['author']]), ('Paperback', [by_source['print']])]
            if separate:
                groups = [('EPUB order', [by_source['brief']]), ('Author fix', [by_source['author']]), groups[-1]]
            groups += [('Cover', [row['id']]) for row in items if row['description'] == 'Book cover']
            return {'document_id': stage, 'groups': [
                {'name': name, 'members': members, 'delivery_mode': 'ONLINE_POSSIBLE', 'delivery_reason': 'Digital file'}
                for name, members in groups
            ]}
        if stage == 'economics':
            return {'document_id': stage, 'rows': [
                {'document_id': row['id'], **{
                    key: {'state': 'unknown', 'quote': None, 'reference': None} for key in economic_signals_v7.DIMENSIONS
                }}
                for row in items
            ]}
        if stage == 'gaps':
            return {'document_id': stage, 'rows': [
                {'id': row['id'], 'state': 'RESOLVED',
                 'problem_quote': 'My Word TOC was missing from Kindle.', 'followup_quote': 'Regenerating the EPUB fixed it.'}
                for row in items
            ]}
        if stage == 'families':
            return {'document_id': stage, 'families': [
                {'name': row['name'], 'members': [row['id']], 'reason': 'Separate deliverable'} for row in items
            ]}
        assert stage == 'source-links'
        if not separate:
            return {'document_id': stage, 'links': []}
        return {'document_id': stage, 'links': [{
            'buyer_group_ids': ['group-001'], 'user_group_ids': ['group-002'], 'shared_task': 'Word Kindle EPUB TOC',
            'support': [
                {'source_id': 'brief', 'field': 'summary', 'quote': 'Convert Word to Kindle EPUB with a clickable TOC.'},
                {'source_id': 'author', 'field': 'followup',
                 'quote': 'Unverified payment' if unsupported else 'Regenerating the EPUB fixed it.'},
            ],
        }]}
    return _with_link_review(call)


def test_mixed_sources_reach_v2_and_apply_existing_source_bound_review(tmp_path):
    from src.extraction import cross_source_discovery

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(packet(), root, call=model())
    assert outcome['status'] == 'REVIEW_COMPLETE'
    assert outcome['cross_source_candidates'] == [
        {'id': 'group-001', 'buyer_sources': ['brief'], 'user_sources': ['author']},
    ]
    assessment = candidate_assessment.assess_run(
        root/'intake.json', root/'v2'/'result.json', review_path=root/'source-review.json')
    mixed, print_only = assessment['candidates']
    assert mixed['name'] == 'EPUB TOC' and print_only['name'] == 'Paperback'
    assert mixed['recurrence']['reviewed_recent_case_count'] == 2
    assert mixed['recurrence']['minimum_recent_cases'] == 10
    assert mixed['economics']['verified_money_count'] == 1
    assert mixed['solution']['verified_current_solution_count'] == 1
    assert mixed['solution']['verified_gap_count'] == 0
    assert mixed['decision'] == 'HOLD' and assessment['official_top20'] is None
    assert json.loads((root/'assessment.json').read_text()) == assessment


def test_multi_group_source_does_not_transfer_its_spend_review(tmp_path):
    from src.extraction import cross_source_discovery

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(packet(), root, call=model(multitask=True))
    assert outcome['status'] == 'REVIEW_COMPLETE'
    assert outcome['unassigned_source_reviews'] == {'brief': 'MULTIPLE_CANDIDATES'}
    review = json.loads((root/'source-review.json').read_text())
    assert all(row['document_id'] != 'brief' for c in review['candidates'].values() for row in c['evidence'])


@pytest.mark.parametrize('has_problem_review', [True, False])
def test_single_task_source_review_survives_a_different_model_quote(tmp_path, has_problem_review):
    from src.extraction import cross_source_discovery

    spec = packet()
    quote = 'Readers need to navigate directly to each chapter.'
    spec['records'][0]['summary'] += f' {quote}'
    if has_problem_review:
        spec['evidence'][0]['quote'] = quote
    else:
        spec['evidence'].pop(0)

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(spec, root, call=model(separate=True))
    assert outcome['status'] == 'REVIEW_COMPLETE'
    mixed = json.loads((root / 'assessment.json').read_text())['candidates'][0]
    assert mixed['name'] == 'Word Kindle EPUB TOC'
    assert mixed['recurrence']['reviewed_recent_case_count'] == (2 if has_problem_review else 1)
    assert mixed['economics']['verified_money_count'] == (1 if has_problem_review else 0)
    assert mixed['decision'] == 'HOLD'
    if has_problem_review:
        assert spec['evidence'][0] in mixed['reviewed_evidence']
        assert 'brief' not in outcome['unassigned_source_reviews']
    else:
        assert outcome['unassigned_source_reviews']['brief'] == 'REVIEW_QUOTE_NOT_LINKED'


def test_shared_operation_connects_separate_groups_without_altering_v2(tmp_path):
    from src.extraction import cross_source_discovery

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(packet(), root, call=model(separate=True))
    v2_path = root/'v2'/'result.json'
    original = v2_path.read_bytes()
    assert len(json.loads(original)['candidates']) == 3
    assert outcome['cross_source_candidates'] == [
        {'id': 'group-001', 'buyer_sources': ['brief'], 'user_sources': ['author']},
    ]
    assert outcome['applied_source_links'] == [{'buyer_group_id': 'group-001', 'user_group_id': 'group-002'}]
    assessment = json.loads((root/'assessment.json').read_text())
    assert len(assessment['candidates']) == 2
    assert assessment['candidates'][0]['recurrence']['reviewed_recent_case_count'] == 2
    assert assessment['candidates'][0]['decision'] == 'HOLD'
    replay = cross_source_discovery.run(packet(), tmp_path/'reused', call=model(separate=True), v2_result=v2_path)
    assert replay['cross_source_candidates'] == outcome['cross_source_candidates']
    assert v2_path.read_bytes() == original


def test_unquoted_link_stops_before_assessment(tmp_path):
    from src.extraction import cross_source_discovery

    root = tmp_path/'run'
    outcome = cross_source_discovery.run(packet(), root, call=model(separate=True, unsupported=True))
    assert outcome['status'] == 'INCOMPLETE'
    assert outcome['stage'] == 'source-links'
    assert not (root/'assessment.json').exists()


def _group(group_id, role, source_ids, records):
    references = []
    for source_id in source_ids:
        record = {
            'id': source_id, 'role': role, 'url': f'https://example.org/{source_id}',
            'published_date': '2026-11-01', 'kind': 'archived_summary', 'summary': f'Verified task for {source_id}.',
        }
        records[source_id] = record
        references.append({
            'source_id': source_id, 'role': role, 'url': record['url'], 'kind': record['kind'],
            'published_date': record['published_date'], 'evidence_field': 'summary',
            'task': record['summary'], 'evidence': record['summary'], 'economic_signals': {}, 'gap': 'NOT_ASSESSED',
        })
    return {'id': group_id, 'name': group_id, 'references': references,
            'delivery_hypothesis': {'mode': 'ONLINE_POSSIBLE', 'reason': 'Digital file'}}


def _proposal(buyers, users, records):
    sources = dict.fromkeys(r['source_id'] for group in [*buyers, *users] for r in group['references'])
    return {'buyer_group_ids': [group['id'] for group in buyers], 'user_group_ids': [group['id'] for group in users],
            'shared_task': 'Kindle EPUB with a working TOC', 'support': [
                {'source_id': source_id, 'field': 'summary', 'quote': records[source_id]['summary']}
                for source_id in sources
            ]}


def test_same_operation_buyer_groups_share_user_sources_once(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    first = _group('buyer-001', 'buyer', ['b1'], records)
    second = _group('buyer-002', 'buyer', ['b2'], records)
    recent_users = _group('recent-users', 'user', ['u1', 'u2', 'u3'], records)
    historical_users = _group('historical-users', 'user', ['u3', 'u4'], records)
    records['u4']['published_date'] = historical_users['references'][1]['published_date'] = '2020-05-01'
    users = [recent_users, historical_users]
    proposal = _proposal([second, first], users, records)
    evidence = [
        {'evidence_id': f'{sid}:{kind}', 'document_id': sid, 'source_url': record['url'],
         'published_at': record['published_date'] + 'T00:00:00Z', 'author_hash': sid, 'community': record['role'],
         'evidence_group_id': record['role'], 'kind': kind, 'quote': record['summary'],
         'interpretation': 'Observed source evidence.', 'confidence': 1}
        for sid, record in records.items()
        for kind in (('problem', 'willingness_to_pay') if record['role'] == 'buyer' else ('problem',))
    ]

    candidates, applied = cross_source_discovery._link_candidates(
        [first, second, *users], list(records.values()), tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': [proposal]}),
    )
    candidate, = candidates
    assert candidate['id'] == 'buyer-001'
    assert candidate['v2_group_ids'] == ['buyer-001', 'buyer-002', 'recent-users', 'historical-users']
    assert [row['user_group_id'] for row in applied] == ['recent-users', 'historical-users']
    reviews, unassigned, cross_source = cross_source_discovery._candidate_reviews(candidates, evidence)
    assert not unassigned
    assert cross_source == [{'id': 'buyer-001', 'buyer_sources': ['b1', 'b2'], 'user_sources': ['u1', 'u2', 'u3', 'u4']}]
    assessed = candidate_assessment.assess_candidate(candidate, records, date(2026, 11, 24), reviews['buyer-001'])
    assert assessed['recurrence']['source_count'] == 6
    assert assessed['recurrence']['reviewed_recent_case_count'] == 5
    assert assessed['economics']['verified_money_count'] == 2
    assert assessed['decision'] == 'HOLD'


def test_buyer_merge_without_user_links_reaches_assessment(tmp_path):
    from src.extraction import cross_source_discovery

    spec = packet()
    second_quote = 'Convert my Word manuscript to Kindle EPUB with a clickable TOC.'
    spec['records'][2]['summary'] = second_quote
    extract = model(separate=True)

    def call(stage, items, prompt, schema):
        if stage != 'source-links':
            return extract(stage, items, prompt, schema)
        return {'document_id': stage, 'links': [{
            'buyer_group_ids': ['group-001', 'group-003'], 'user_group_ids': [],
            'shared_task': 'Word Kindle EPUB TOC',
            'support': [
                {'source_id': 'brief', 'field': 'summary', 'quote': spec['evidence'][0]['quote']},
                {'source_id': 'print', 'field': 'summary', 'quote': second_quote},
            ],
        }]}

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(spec, root, call=call)
    assert outcome['status'] == 'REVIEW_COMPLETE'
    assert outcome['applied_source_links'] == []
    combined, separate_user = json.loads((root / 'assessment.json').read_text())['candidates']
    assert {ref['source_id'] for ref in combined['references']} == {'brief', 'print'}
    assert {ref['source_id'] for ref in separate_user['references']} == {'author'}
    assert (root / 'linked-analysis.json').exists()


def test_buyer_group_cannot_be_merged_into_two_operations(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    first = _group('first', 'buyer', ['b1'], records)
    second = _group('second', 'buyer', ['b2'], records)
    user = _group('user', 'user', ['u1'], records)
    proposals = [_proposal([first, second], [], records), _proposal([second], [user], records)]
    with pytest.raises(ValueError, match='duplicate group'):
        cross_source_discovery._link_candidates(
            [first, second, user], list(records.values()), tmp_path,
            lambda stage, *_: {'document_id': stage, 'links': proposals},
        )
    assert not (tmp_path / 'source-links.json').exists()


def test_links_three_plus_one_user_sources_to_same_three_source_buyer_group(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    buyer = _group('buyer', 'buyer', ['b1', 'b2', 'b3'], records)
    earlier = _group('earlier', 'user', ['u1', 'u2', 'u3'], records)
    additional = _group('additional', 'user', ['u4', 'u3'], records)
    word_only = _group('word-only', 'user', ['word'], records)
    proposal = _proposal([buyer], [earlier, additional], records)

    candidates, applied = cross_source_discovery._link_candidates(
        [buyer, earlier, additional, word_only], list(records.values()), tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': [proposal]}),
    )
    linked, separate = candidates
    assert linked['v2_group_ids'] == ['buyer', 'earlier', 'additional']
    assert {r['source_id'] for r in linked['references']} == {'b1', 'b2', 'b3', 'u1', 'u2', 'u3', 'u4'}
    assert separate == word_only
    assert [pair['user_group_id'] for pair in applied] == ['earlier', 'additional']
    assessed = candidate_assessment.assess_candidate(linked, records, date(2026, 11, 24))
    assert assessed['recurrence']['recent_source_count'] == 7
    assert assessed['recurrence']['minimum_recent_cases'] == 10
    assert assessed['decision'] == 'HOLD'


def test_review_with_two_task_references_in_one_linked_candidate_needs_quote_overlap(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    buyer = _group('buyer', 'buyer', ['brief'], records)
    earlier = _group('earlier', 'user', ['author'], records)
    additional = _group('additional', 'user', ['author'], records)
    quote = 'Reading the book requires working chapter links.'
    records['author']['summary'] += f' {quote}'
    additional['references'][0]['evidence'] = 'task for author.'
    proposal = _proposal([buyer], [earlier, additional], records)
    linked, _ = cross_source_discovery._link_candidates(
        [buyer, earlier, additional], list(records.values()), tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': [proposal]}),
    )
    problem_review = [{'document_id': 'author', 'kind': 'problem', 'quote': quote}]
    reviews, unassigned, _ = cross_source_discovery._candidate_reviews(linked, problem_review)
    assert reviews == {}
    assert unassigned == {'author': 'REVIEW_QUOTE_NOT_LINKED'}


def test_ambiguous_user_source_stays_separate_from_both_buyer_groups(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    first = _group('first', 'buyer', ['b1'], records)
    second = _group('second', 'buyer', ['b2'], records)
    common = _group('common', 'user', ['u1'], records)
    shared_source = _group('shared-source', 'user', ['u1'], records)
    exclusive = _group('exclusive', 'user', ['u2'], records)
    proposals = [_proposal([first], [common, exclusive], records), _proposal([second], [shared_source], records)]

    candidates, applied = cross_source_discovery._link_candidates(
        [first, second, common, shared_source, exclusive], list(records.values()), tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': proposals}),
    )
    assert applied == [{'buyer_group_id': 'first', 'user_group_id': 'exclusive'}]
    assert [row['id'] for row in candidates] == ['first', 'second', 'common', 'shared-source']
    assert set(r['source_id'] for r in candidates[0]['references']) == {'b1', 'u2'}


@pytest.fixture
def excel_refresh_link_replay():
    path = Path(__file__).parents[1] / 'fixtures' / 'cross-source-excel-refresh-v2.json'
    return json.loads(path.read_text(encoding='utf-8'))


def test_excel_refresh_does_not_link_monthly_column_extraction(tmp_path, excel_refresh_link_replay):
    from src.extraction import cross_source_discovery

    replay = excel_refresh_link_replay
    proposal = replay['monthly_link_proposal']
    group_ids = set(proposal['buyer_group_ids'] + proposal['user_group_ids'])
    candidates, _ = cross_source_discovery._link_candidates(
        [candidate for candidate in replay['candidates'] if candidate['id'] in group_ids],
        replay['records'], tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': [proposal]}, {'group-007'}),
    )

    monthly_source = 'reddit:1xod1c8'
    memberships = [{ref['source_id'] for ref in candidate['references']} for candidate in candidates]
    assert [sources for sources in memberships if monthly_source in sources] == [{monthly_source}]
    assert {'freelancer:40698089', 'freelancer:40718187'} in memberships


def test_excel_refresh_compares_weekly_buyer_in_a_mixed_group(tmp_path, excel_refresh_link_replay):
    from src.extraction import cross_source_discovery

    replay = excel_refresh_link_replay
    compared_sources = set()
    group_ids = {*replay['monthly_link_proposal']['buyer_group_ids'], 'group-003'}
    groups = [candidate for candidate in replay['candidates'] if candidate['id'] in group_ids]
    proposal = _proposal(groups, [], {record['id']: record for record in replay['records']})
    proposal['shared_task'] = replay['monthly_link_proposal']['shared_task']

    def record_comparison(stage, items, _prompt, _schema):
        compared_sources.update(
            member['source_id'] for groups in items.values() for group in groups for member in group['members']
        )
        return {'document_id': stage, 'links': [proposal] if 'freelancer:40813052' in compared_sources else []}

    candidates, _ = cross_source_discovery._link_candidates(
        groups, replay['records'], tmp_path, _with_link_review(record_comparison),
    )

    assert 'freelancer:40813052' in compared_sources
    candidate, = candidates
    assert sorted(ref['source_id'] for ref in candidate['references']) == [
        'freelancer:40698089', 'freelancer:40718187', 'freelancer:40813052', 'microsoft:1352370',
    ]


def test_unreviewed_source_link_stops_before_assessment(tmp_path):
    from src.extraction import cross_source_discovery

    propose = model(separate=True)

    def call(stage, items, prompt, schema):
        if stage == 'source-link-review':
            return {'document_id': stage, 'reviews': []}
        return propose(stage, items, prompt, schema)

    root = tmp_path / 'run'
    outcome = cross_source_discovery.run(packet(), root, call=call)

    assert outcome['status'] == 'INCOMPLETE'
    assert outcome['stage'] == 'source-links'
    assert 'each proposed group exactly once' in outcome['reason']
    assert not (root / 'assessment.json').exists()


def test_user_in_a_mixed_group_is_not_added_to_a_different_buyer(tmp_path):
    from src.extraction import cross_source_discovery

    records = {}
    mixed = _group('mixed', 'buyer', ['b1'], records)
    other = _group('other', 'buyer', ['b2'], records)
    user = _group('user', 'user', ['u1'], records)
    mixed['references'].extend(user['references'])
    proposal = _proposal([other], [user], records)

    candidates, applied = cross_source_discovery._link_candidates(
        [mixed, other, user], list(records.values()), tmp_path,
        _with_link_review(lambda stage, *_: {'document_id': stage, 'links': [proposal]}),
    )

    assert candidates == [mixed, other, user]
    assert not applied


@pytest.mark.parametrize('invalid', ['duplicate', 'altered_review_quote'])
def test_invalid_packet_stops_before_the_v2_model(tmp_path, invalid):
    from src.extraction import cross_source_discovery

    spec = packet()
    if invalid == 'duplicate':
        spec['records'][1]['url'] = spec['records'][0]['url'] + '?tracking=1'
    else:
        spec['evidence'][0]['quote'] = 'I paid to have somebody make the file.'
    with pytest.raises(ValueError):
        cross_source_discovery.run(spec, tmp_path/'run', call=lambda *args: pytest.fail('Unexpected model call'))
    assert not (tmp_path/'run').exists()
