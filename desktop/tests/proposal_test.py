from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from desktop.tests.local_test import local,configure,project,wait


def test_real_draft_pipeline_uses_local_background_and_preserves_quality(local,monkeypatch):
    configure(local);pid=project(local)
    from services.scoring_policy import DIMENSIONS
    import services.llm_scoring_service as llm
    import services.proposal_service as proposals
    class Provider:
        async def score(self,*_):
            return {'dimension_scores':{k:9 for k in DIMENSIONS},'estimated_hours':10,'suggested_bid':250,
                'reason':'Clear full scope and strong Python fit.','clarification_questions':[],
                'scope_assumptions':['Repository access before work begins.'],'provider_model':'fixture'}
        async def close(self,*_):pass
    monkeypatch.setattr(llm.LLMScoringService,'_create_provider_client',lambda *_:(Provider(),object()))
    text=('I will implement the Python REST API integration around your documented endpoint and expected response format. '
        'The approach includes explicit error handling, a configuration guide and a README for repeatable setup. '
        'I will test acceptance with sample responses after repository access and credentials are supplied. '
        'The full quote is 250 USD and delivery is two days after access is confirmed. Which sample response should define the acceptance test?')
    client=SimpleNamespace(generate_proposal=AsyncMock(return_value=text))
    monkeypatch.setattr(proposals.ProposalService,'_build_default_llm_client',lambda _:client)
    local.queue.start()
    assert wait(local,local.queue.enqueue('analyze',pid))['state']=='succeeded'
    result=wait(local,local.queue.enqueue('proposal',pid))
    assert result['state']=='succeeded',result
    assert result['result']['proposal']==text
    prompt=client.generate_proposal.call_args.kwargs['system_prompt']
    assert 'I build Python integrations.' in prompt and 'Only the user-supplied' in prompt
    saved=local.client.get('/api/projects').json()[0]
    assert saved['proposal']==text
    assert local.client.get(f'/api/projects/{pid}/proposal').text==text
