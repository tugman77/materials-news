"""macOS NFD 파일명 import 호환 — sitecustomize.py

macOS HFS+/APFS는 파일명을 NFD(유니코드 분해형)로 저장한다.
Python 3.9의 import는 NFC를 기대하므로 한글 .py 모듈을 찾지 못한다.
PYTHONPATH에 이 파일이 있는 디렉터리를 넣으면 자동 로드된다.
"""
from __future__ import annotations
import sys, os, unicodedata, importlib.abc, importlib.util


class _NFDFinder(importlib.abc.MetaPathFinder):

    def find_module(self, fullname, path=None):
        for d in (path or sys.path):
            if not isinstance(d, str) or not os.path.isdir(d):
                continue
            nfd_name = unicodedata.normalize('NFD', fullname) + '.py'
            if os.path.isfile(os.path.join(d, nfd_name)):
                return self
        return None

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        for d in sys.path:
            if not isinstance(d, str) or not os.path.isdir(d):
                continue
            nfd_name = unicodedata.normalize('NFD', fullname) + '.py'
            candidate = os.path.join(d, nfd_name)
            if os.path.isfile(candidate):
                spec = importlib.util.spec_from_file_location(fullname, candidate)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[fullname] = mod
                spec.loader.exec_module(mod)
                return mod
        raise ImportError(fullname)


sys.meta_path.insert(0, _NFDFinder())
