import asyncio
import base64
from datetime import datetime,timedelta,timezone
import hashlib
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from desktop.licensing import canonical
from desktop.updates import ReleaseManager,ReleaseError


def release(key,**changes):
    now=datetime.now(timezone.utc)
    payload={'kind':'release','version_schema':1,'version':'0.2.0','platform':'windows','architecture':'x64',
        'code_signed':True,'native_verified':True,'issued_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(days=1)).isoformat(),
        'url':'https://downloads.example.invalid/BidMaster.exe','bytes':4,'sha256':hashlib.sha256(b'test').hexdigest(),**changes}
    return {'payload':payload,'signature':base64.b64encode(key.sign(canonical(payload))).decode()}


@pytest.mark.parametrize('changes',[{'platform':'macos'},{'architecture':'arm64'},{'version':'0.0.1'},
    {'code_signed':False},{'expires_at':'2000-01-01T00:00:00+00:00'},{'url':'http://unsafe.invalid/app.exe'},
    {'url':'https://attacker:secret@example.invalid/app.exe'},{'bytes':True}])
def test_untrusted_or_wrong_update_is_never_downloaded(tmp_path,changes):
    key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    manager=ReleaseManager(tmp_path,pub,'windows','x64')
    with pytest.raises(ReleaseError):manager.verify(release(key,**changes))
    assert list(tmp_path.iterdir())==[]


def test_corrupted_installer_is_not_saved_or_installed(tmp_path,monkeypatch):
    key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    class Response:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def aiter_bytes(self):yield b'evil'
    class Client:
        def __init__(self,**kw):assert not kw['follow_redirects'] and not kw['trust_env']
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def stream(self,*a):return Response()
    import desktop.updates as module
    monkeypatch.setattr(module.httpx,'AsyncClient',Client)
    with pytest.raises(ReleaseError,match='integrity'):asyncio.run(ReleaseManager(tmp_path,pub,'windows','x64').download(release(key)))
    assert list((tmp_path/'updates').iterdir())==[]


def test_verified_installer_is_saved_but_never_executed(tmp_path,monkeypatch):
    key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    class Response:
        status_code=200
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def aiter_bytes(self):yield b'test'
    class Client:
        def __init__(self,**kw):assert not kw['follow_redirects']
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def stream(self,*a):return Response()
    import desktop.updates as module
    monkeypatch.setattr(module.httpx,'AsyncClient',Client)
    result=asyncio.run(ReleaseManager(tmp_path,pub,'windows','x64').download(release(key)))
    assert not result['installed']
    assert __import__('pathlib').Path(result['file']).read_bytes()==b'test'


def test_tampered_and_non_native_metadata_cannot_enable_download(tmp_path):
    key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    manager=ReleaseManager(tmp_path,pub,'windows','x64')
    doc=release(key);doc['payload']['url']='https://other.invalid/changed.exe'
    with pytest.raises(ReleaseError):manager.verify(doc)
    with pytest.raises(ReleaseError):manager.verify(release(key,native_verified=False))
