# Windows 설치 프로그램

## 방식: PyInstaller 대신 "휴대용 파이썬 배포"

이 앱은 정밀해석마다 자기 자신을 서브프로세스로 재실행하고
(`infrastructure/opensees/runner.py`/`model_importer.py`가
`[sys.executable, "-m", "openframe.infrastructure.opensees.worker", ...]`를 씀),
2D 자유 모델링의 정정성 판별은 메인 GUI 프로세스 안에서 openseespy를 직접 호출한다
(`features/analysis/statics/solver.py`). 둘 다 `sys.executable`이 진짜 파이썬
인터프리터여야 동작하므로, PyInstaller로 얼리는 대신 **python.org 공식 임베드 배포판 +
`pip install --target`으로 이 프로젝트와 모든 의존성을 설치해 둔 폴더**를 그대로
설치 파일에 담는다. 자세한 배경은 `scripts/build_windows_payload.py`의 모듈 docstring 참고.

## 빌드 순서

1. **페이로드 생성**: `.venv\Scripts\python.exe scripts\build_windows_payload.py`
   → `build/payload/`에 `python.exe`/`pythonw.exe` + 모든 의존성 + 이 프로젝트 설치됨
   (`build/`는 git에 안 올라감). 재실행해도 안전 — 매번 site-packages를 새로 만듦.
2. **로컬 검증**: `build/payload/pythonw.exe -m openframe`로 직접 실행해서 확인 —
   최소한 2D 캔버스에서 정정해석 한 번, 정밀해석 템플릿(좌굴 또는 시간이력) SETUP까지 열어서
   RUN 한 번은 꼭 눌러볼 것 (이 둘이 각각 인프로세스 openseespy·서브프로세스 워커 재실행
   경로를 대표함).
3. **Inno Setup으로 포장**: `installer/openframe.iss`(아직 미작성)가 `build/payload/` 전체를
   설치 폴더로 복사하고, 시작 메뉴 바로가기를 `pythonw.exe -m openframe`로 연결한다.
   생성된 설치 파일은 `installer/output/`에 두며 Git에는 포함하지 않는다.
4. **클린 환경 검증**: 만든 설치 파일을 이 개발 PC의 기존 파이썬/`.venv`와 무관한 환경(이상적으론
   파이썬이 한 번도 깔린 적 없는 PC/VM)에서 설치→실행→정정해석→정밀해석 RUN까지 확인 —
   "내 PC에서는 됐는데" 실패를 잡아내는 유일한 단계.

## 현재 상태

1번(페이로드 빌드)까지 완료·검증됨(2026-08-21) — 좌굴·시간이력 정밀해석 둘 다 실제
서브프로세스 재실행을 통해 RUN까지 성공, 3D 뷰포트(QtQuick3D, 시작 시 즉시 생성됨)도 정상
기동 확인. 3번(Inno Setup 스크립트)은 Inno Setup이 개발 PC에 설치돼 있어야 진행 가능.
