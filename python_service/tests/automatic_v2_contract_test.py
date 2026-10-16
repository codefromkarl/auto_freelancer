import asyncio
from unittest.mock import Mock

from services.proposal_service import DefaultProposalValidator
from services.freelancer_client import FreelancerClient
from services.proposal_competition import _mentions


def test_pdf_table_and_xlsx_vocabulary_matches_excel_requirement():
    validator=DefaultProposalValidator()
    assert validator._count_anchor_hits('normalize tabular sections into one xlsx workbook', ['tables','excel'])==2
    assert validator._count_anchor_hits('implement a react authentication api', ['tables','excel'])==0
    features=_mentions('Delivery is three days of source file and column-mapping confirmation, with row counts and subtotals reconciled.')
    assert features['scope'] and features['acceptance']


def test_registered_skill_filter_uses_platform_array_parameter(monkeypatch):
    import services.freelancer_client as module
    sdk=Mock(return_value={'projects':[]})
    monkeypatch.setattr(module,'search_projects',sdk)
    client=FreelancerClient()
    assert asyncio.run(client.search_projects(skills=[13,607],status='active'))==[]
    assert sdk.call_args.kwargs['search_filter']['jobs[]']==[13,607]
    assert 'jobs' not in sdk.call_args.kwargs['search_filter']
