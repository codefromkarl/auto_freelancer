import asyncio
import base64
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from desktop.configuration import ConfigStore,engine_overrides,Provider
from desktop.licensing import LicenseManager,EntitlementError,canonical
from desktop.paths import data_directory
from desktop.api import create_app
from desktop.database import Job
from desktop.locking import InstanceLock
from desktop.secrets import SecretStore,VaultUnavailable


class MemoryVault:
    def __init__(self):self.values={}
    def set(self,key,value):self.values[key]=value
    def get(self,key):return self.values.get(key,'')
    def status(self):return {'available':True,'provider_key_saved':bool(self.get('model_api_key')),'platform_token_saved':bool(self.get('freelancer_token'))}


def signed(key,installation,kind='license',**changes):
    now=datetime.now(timezone.utc)
    payload={'kind':kind,'version':1,'id':'test-license','installation_id':installation,
        'issued_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(days=1)).isoformat(),
        'capabilities':['assistant'],**changes}
    return {'payload':payload,'signature':base64.b64encode(key.sign(canonical(payload))).decode()}


@pytest.fixture
def local(tmp_path):
    store=ConfigStore(tmp_path);vault=MemoryVault();key=Ed25519PrivateKey.generate()
    manager=LicenseManager(tmp_path,store.load().installation_id,key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    app=create_app(tmp_path,'session-value',vault=vault,licenses=manager,start_worker=False)
    with TestClient(app,base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer session-value'}) as client:
        yield SimpleNamespace(app=app,client=client,store=store,vault=vault,licenses=manager,key=key,directory=tmp_path,queue=app.state.queue)


def configure(f):
    f.licenses.install(signed(f.key,f.store.load().installation_id))
    assert f.client.put('/api/profile',json={'profile':{'skills':['Python','FastAPI'],'background':'I build Python integrations.'}}).status_code==200
    assert f.client.put('/api/provider',json={'provider':{'model':'fixture-model'},'api_key':'private-model-key'}).status_code==200


def project(f):
    r=f.client.post('/api/projects',json={'title':'Python API integration','description':'Deliver a Python REST API integration with acceptance tests and setup documentation.',
        'budget_minimum':100,'budget_maximum':500});assert r.status_code==200;return r.json()['id']


def wait(f,identity):
    for _ in range(100):
        row=next(j for j in f.queue.list() if j['id']==identity)
        if row['state'] not in ['running','queued']:return row
        time.sleep(.05)
    pytest.fail('Local job did not complete')


def test_local_paths_are_outside_installation(monkeypatch,tmp_path):
    assert data_directory('win32',{'LOCALAPPDATA':str(tmp_path)})==tmp_path/'BidMaster'
    assert 'Application Support' in str(data_directory('darwin',{}))
    assert data_directory('linux',{'XDG_DATA_HOME':str(tmp_path)})==tmp_path/'bidmaster'


def test_loopback_auth_origin_and_secret_safe_validation(local):
    c=local.client
    assert c.get('/health').status_code==200
    assert c.get('/api/status',headers={'Authorization':''}).status_code==401
    assert c.get('/api/status',headers={'Origin':'https://attacker.invalid'}).status_code==403
    assert c.get('/api/status',headers={'Host':'attacker.invalid'}).status_code==400
    r=c.put('/api/provider',json={'provider':{'base_url':'http://bad.invalid','model':'x'},'api_key':'never-echo-this-key'})
    assert r.status_code==422 and 'never-echo' not in r.text
    assert 'Content-Security-Policy' in c.get('/').headers
    assert c.post('/api/bids',json={}).status_code==404


def test_credentials_never_enter_json_responses_or_diagnostics(local):
    configure(local)
    assert local.client.put('/api/account',json={'account_id':123,'token':'private-platform-token'}).status_code==200
    assert 'private-model-key' not in (local.directory/'config.json').read_text()
    for path in ['/api/status','/api/diagnostics','/api/projects','/api/jobs']:
        result=local.client.get(path)
        assert result.status_code==200 and 'private-model-key' not in result.text and 'private-platform-token' not in result.text
    assert local.client.put('/api/provider',json={'provider':{'base_url':'https://other.invalid/v1','model':'x'}}).status_code==400


def test_untrusted_plaintext_backend_has_no_fallback(tmp_path):
    backend=SimpleNamespace(get_password=lambda *_:'secret',set_password=lambda *_:None)
    vault=SecretStore(tmp_path,backend)
    assert vault.status()['available'] is False
    with pytest.raises(VaultUnavailable):vault.set('model_api_key','secret')
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('change',[
    {'installation_id':'b'*32},{'expires_at':'2020-01-01T00:00:00+00:00'},
    {'issued_at':'2099-01-01T00:00:00+00:00'},{'kind':'platform_authorization'},
])
def test_license_wrong_installation_expiry_and_kind_rejected(local,change):
    doc=signed(local.key,local.store.load().installation_id,**change)
    if change.get('kind')=='platform_authorization':
        with pytest.raises(EntitlementError):local.licenses.verify(doc,'license')
    else:
        with pytest.raises(EntitlementError):local.licenses.install(doc)


def test_tampered_and_revoked_licenses_fail_closed(local):
    doc=signed(local.key,local.store.load().installation_id);doc['payload']['capabilities'].append('platform_execution')
    with pytest.raises(EntitlementError):local.licenses.install(doc)
    configure(local)
    local.licenses.install(signed(local.key,local.store.load().installation_id,'revocations',id='rev1',revoked_ids=['test-license']))
    assert local.licenses.status()['active'] is False


def test_software_purchase_is_not_platform_permission(local):
    configure(local)
    r=local.client.post('/api/automation/start',json={'mode':'automatic','confirm_model_costs':True})
    assert r.status_code==403 and not local.client.get('/api/status').json()['platform']['running']
    assert local.client.post('/api/projects/'+str(project(local))+'/tasks',json={'action':'analyze'}).status_code==422


def test_first_run_missing_vault_can_still_view_and_import(local):
    assert local.client.get('/api/status').status_code==200
    identity=project(local)
    assert identity<0
    r=local.client.post(f'/api/projects/{identity}/tasks',json={'action':'analyze','confirm_model_costs':True})
    assert r.status_code==403
    assert local.client.get('/api/projects').json()[0]['score'] is None


def test_queue_pause_config_change_limits_and_cancellation(local):
    configure(local);pid=project(local)
    local.queue.set_paused(True)
    identity=local.queue.enqueue('analyze',pid)
    with pytest.raises(ValueError,match='already'):local.queue.enqueue('analyze',pid)
    local.queue.cancel(identity)
    assert local.queue.list()[0]['state']=='cancelled'
    local.queue.enqueue('analyze',pid)
    cfg=local.store.load();cfg.revision+=1;local.store.save(cfg)
    local.queue.start();local.queue.set_paused(False)
    row=wait(local,local.queue.list()[0]['id'])
    assert row['state']=='failed' and 'Configuration changed' in row['error']


def test_daily_limit_and_backup_do_not_change_jobs(local):
    configure(local);pid=project(local)
    cfg=local.store.load();cfg.daily_model_tasks=1;local.store.save(cfg)
    local.queue.enqueue('analyze',pid)
    with pytest.raises(ValueError,match='daily'):local.queue.enqueue('proposal',pid)
    response=local.client.post('/api/backup');assert response.status_code==200
    assert (local.directory/'backups'/response.json()['filename']).exists()
    assert len(local.queue.list())==1


def test_credential_and_database_config_do_not_inherit_personal_env(local,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','should-not-be-read')
    values=engine_overrides(local.store.load(),local.vault,local.directory)
    assert values['OPENAI_API_KEY']=='' and not values['OPENAI_ENABLED']
    assert values['LLM_API_KEY']=='' and values['FREELANCER_OAUTH_TOKEN']==''
    assert values['DATABASE_PATH']==str(local.directory/'projects.db')
    assert not values['BID_SUBMISSION_ENABLED']


def test_running_work_finishes_when_paused(local):
    configure(local);pid=project(local);started=threading.Event();finish=threading.Event()
    async def execute(*_):started.set();finish.wait(5);return {'done':True}
    local.queue.executor=execute
    identity=local.queue.enqueue('analyze',pid);local.queue.start();assert started.wait(2)
    local.queue.set_paused(True)
    assert local.queue.busy.is_set()
    assert local.client.put('/api/profile',json={'profile':{'skills':['Java']}}).status_code==409
    finish.set();assert wait(local,identity)['state']=='succeeded'


def test_restarting_marks_interrupted_tasks_without_auto_resubmission(local):
    configure(local);pid=project(local);local.queue.enqueue('analyze',pid)
    from desktop.database import Database
    other=Database(local.directory)
    try:
        with other.session() as db:assert db.query(Job).one().state=='interrupted'
    finally:other.engine.dispose()


def test_runtime_lock_prevents_duplicate_instances(tmp_path):
    with InstanceLock(tmp_path/'app.lock'):
        with pytest.raises(RuntimeError,match='already running'):
            with InstanceLock(tmp_path/'app.lock'):pass


def test_real_engine_analysis_uses_user_profile_and_never_fetches_platform(local,monkeypatch):
    configure(local);pid=project(local)
    import services.llm_scoring_service as module
    from services.scoring_policy import DIMENSIONS
    calls=[]
    class Provider:
        async def score(self,client,model,payload,prompt):
            calls.append(payload)
            return {'dimension_scores':{k:8 for k in DIMENSIONS},'estimated_hours':10,'suggested_bid':250,
                'reason':'A clear Python integration with a full acceptance plan.','clarification_questions':[],
                'scope_assumptions':['Repository access before work starts.'],'provider_model':'fixture'}
        async def close(self,*_):pass
    monkeypatch.setattr(module.LLMScoringService,'_create_provider_client',lambda *_:(Provider(),object()))
    identity=local.queue.enqueue('analyze',pid);local.queue.start()
    row=wait(local,identity);assert row['state']=='succeeded',row
    assert calls[0]['developer_capabilities']=={1:['Python','FastAPI']}
    assert calls[0]['skills']==[]
    saved=local.client.get('/api/projects').json()[0]
    assert saved['hours']==10 and saved['quote_usd']==250 and saved['explanation'].startswith('A clear Python')


def test_credential_disconnect_preserves_project_history(local):
    configure(local);pid=project(local)
    assert local.client.delete('/api/provider').status_code==200
    assert local.vault.get('model_api_key')==''
    assert local.client.get('/api/projects').json()[0]['id']==pid
    local.client.put('/api/account',json={'account_id':123,'token':'only-this-account'})
    assert local.client.delete('/api/account').json()['records_preserved']
    assert not local.vault.get('freelancer_token')


def test_platform_switch_cannot_overwrite_another_accounts_ledger(local):
    from database.models import Bid,Project
    pid=project(local)
    with local.app.state.database.session() as db:
        p=db.query(Project).filter_by(freelancer_id=pid).one()
        db.add(Bid(freelancer_bid_id=1,project_id=p.id,project_freelancer_id=pid,bidder_id=123,amount=100,period=2,status='active'))
    r=local.client.put('/api/account',json={'account_id':456,'token':'wrong-account'})
    assert r.status_code==409
    assert not local.vault.get('freelancer_token')


def test_local_prompt_factory_never_reads_personal_resume(local,monkeypatch):
    configure(local)
    from config import settings
    from services.proposal_service import create_proposal_service
    from desktop.engine import LocalPromptBuilder,engine_context
    monkeypatch.setenv('BIDMASTER_DATA_DIR',str(local.directory))
    with engine_context(local.store.load(),local.vault,local.directory):
        service=create_proposal_service()
        assert isinstance(service.prompt_builder,LocalPromptBuilder)
        prompt=service.prompt_builder.build_prompt({})
        assert 'I build Python integrations.' in prompt
        assert '15 years' not in prompt
        asyncio.run(service.llm_client.close())


def test_orphaned_worker_is_detected_and_stopped_without_spawning(local):
    from desktop.platform import PlatformWorker
    from desktop.paths import atomic_json
    manager=PlatformWorker(local.store,local.vault,local.licenses)
    atomic_json(local.directory/'platform-session.json',{'pid':12345,'installation_id':local.store.load().installation_id})
    with InstanceLock(local.directory/'platform-worker.lock'):
        assert manager.status()=={'running':True,'pid':12345,'recovered':True}
        manager.stop();assert (local.directory/'stop-platform').exists()
        with pytest.raises(ValueError,match='already running'):manager.start('automatic')
    assert manager.status()['running'] is False  # A stale record is not process ownership.


def test_editing_brief_invalidates_old_assessment_and_blocks_queued_changes(local):
    configure(local);pid=project(local)
    from database.models import Project
    with local.app.state.database.session() as db:
        p=db.query(Project).filter_by(freelancer_id=pid).one();p.ai_score=8;p.ai_proposal_draft='Old draft';p.suggested_bid=200
    body={'title':'Revised Python integration','description':'Updated whole scope with source files and concrete acceptance tests for the complete integration.','budget_minimum':200,'budget_maximum':600}
    assert local.client.put(f'/api/projects/{pid}',json=body).status_code==200
    saved=local.client.get('/api/projects').json()[0]
    assert saved['score'] is None and not saved['proposal'] and saved['quote_usd'] is None
    local.queue.enqueue('analyze',pid)
    r=local.client.put(f'/api/projects/{pid}',json=body)
    assert r.status_code==409
    assert local.client.post('/api/projects',json={**body,'title':' '*10}).status_code==422


def test_logging_redacts_known_keys_without_touching_the_vault(local,monkeypatch):
    import logging
    from desktop.redaction import remember
    from desktop.launcher import CredentialFilter
    remember('sk-secret-key-for-test')
    record=logging.LogRecord('provider',logging.ERROR,__file__,1,'Invalid API key sk-secret-key-for-test',(),None)
    monkeypatch.setattr(SecretStore,'get',lambda *_:pytest.fail('Logging re-entered the OS vault'))
    assert CredentialFilter(local.directory).filter(record)
    assert 'sk-secret' not in record.getMessage() and '[REDACTED]' in record.getMessage()


def test_platform_capability_alone_is_not_a_permission_attestation(local):
    config=local.store.load()
    local.licenses.install(signed(local.key,config.installation_id,capabilities=['assistant','platform_execution']))
    with pytest.raises(EntitlementError):local.licenses.require_platform('platform_read')
    document=signed(local.key,config.installation_id,'platform_authorization',platform='freelancer',
        authorization_reference='TEST-ONLY written-permission reference',capabilities=['platform_read'])
    local.licenses.install(document)
    assert local.licenses.require_platform('platform_read')['platform']=='freelancer'
    with pytest.raises(EntitlementError):local.licenses.require_platform('platform_bid')


def test_installed_build_cannot_override_publisher_identity(monkeypatch,tmp_path):
    from desktop.launcher import main
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    with pytest.raises(SystemExit) as exc:main(['--publisher-public-key',str(tmp_path/'other.pem')])
    assert exc.value.code==2
