# Native builds only. Data inclusion is an allowlist, not a checkout copy.
import os
import sys
from pathlib import Path
root = Path(SPECPATH).parents[1]
public = Path(os.environ['BIDMASTER_BUILD_PUBLIC_KEY'])
backend = {'win32':'keyring.backends.Windows','darwin':'keyring.backends.macOS'}.get(sys.platform,'keyring.backends.SecretService')
a = Analysis([str(root/'desktop/entrypoint.py')],pathex=[str(root),str(root/'python_service'),str(root/'scripts/manual_pipeline')],
    binaries=[],datas=[(str(root/'desktop/ui'),'desktop/ui'),(str(public),'desktop/assets'),(os.environ['BIDMASTER_BUILD_NOTICES'],'desktop/assets')],
    hiddenimports=['scheduler','common',backend,'sqlalchemy.dialects.sqlite','sqlalchemy.ext.baked','cryptography.hazmat.primitives.asymmetric.ed25519'],
    hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['pytest','tkinter'],noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='BidMaster',debug=False,bootloader_ignore_signals=False,
    strip=False,upx=False,console=sys.platform not in ('win32','darwin'),
    codesign_identity=os.environ.get('BIDMASTER_MAC_SIGN_IDENTITY'),entitlements_file=None)
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='BidMaster')
if sys.platform == 'darwin':
    app = BUNDLE(coll,name='BidMaster.app',bundle_identifier='com.bidmaster.local',
        codesign_identity=os.environ.get('BIDMASTER_MAC_SIGN_IDENTITY'),
        info_plist={'CFBundleShortVersionString':'0.1.0','NSHighResolutionCapable':True})
