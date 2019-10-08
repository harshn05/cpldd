# -*- mode: python ; coding: utf-8 -*-
block_cipher = None
a = Analysis(['cpldd.py'],
             pathex=['C:\\Users\\harshn\\Desktop\\cpldd'],
             #binaries=[('cygpath.exe','.'),('ldd.exe','.'),('msys-2.0.dll','.')],
			 binaries=[],
			 #datas=[('cygpath.exe','.'),('ldd.exe','.'),('msys-2.0.dll','.')],
             datas=[],
             #hiddenimports=[('cygpath.exe','.'),('ldd.exe','.'),('msys-2.0.dll','.')],
			 hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
			 
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='cpldd',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=False,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True )
