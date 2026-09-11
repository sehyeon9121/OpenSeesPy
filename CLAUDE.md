# OpenFrame Studio

OpenSeesPy 코드에서 구조모델을 읽어 시각화하고, 해석 결과(변형 형상, 반력,
N·V·M 다이어그램, 고유치/좌굴 모드 등)를 보여주는 PySide6 데스크톱 프로그램.

구조와 의존 규칙의 전체 내용은 [docs/architecture.md](docs/architecture.md)가
기준 문서다. 이 파일은 세션 시작 시 매번 다시 읽지 않아도 되는 핵심만 요약한다.
구조 관련 결정을 내리기 전에는 이 파일보다 `docs/architecture.md`를 우선한다.

## 폴더 구조 (기능 중심)

| 경로 | 책임 |
|---|---|
| `app/shell` | 화면 배치, 신호 연결만. 해석·계산 로직 없음 |
| `core/domain` | 공통 구조모델·해석 요청/결과 타입. PySide6·OpenSeesPy 참조 금지 |
| `core/contracts` | feature 간, infrastructure와의 인터페이스 |
| `features/model` | 코드 검사, 모델 가져오기·검증, 모델링 패널 |
| `features/analysis` | 해석 종류별 모듈(`linear_static`, `nonlinear_static`, `time_history`, `modal`, `buckling`, …), 설정 패널 |
| `features/results` | 변형·반력·N·V·M 계산과 결과 패널 |
| `features/viewport` | 2D/3D 구조 장면, 그래픽 항목, 표시 제어 (QML 포함) |
| `infrastructure/opensees` | 실제 OpenSeesPy 실행. worker 프로세스로 격리 |
| `infrastructure/materials`, `material_section_db`, `ground_motions` | 외부 데이터/DB 어댑터 |

## 반드시 지킬 의존 규칙

- `core`는 PySide6·OpenSeesPy를 참조하지 않는다.
- `features`끼리 공통 데이터를 복제하지 않고 `core.domain`을 통해 공유한다.
- `infrastructure`는 `core.contracts`를 구현한다.
- GUI(위젯·QML)가 OpenSeesPy를 직접 호출하지 않는다 — 업로드된 Python 코드와
  실제 해석은 `infrastructure/opensees/worker.py`가 별도 프로세스에서 실행한다.
- 다이어그램·응력 등 계산 모듈은 Qt 그래픽 객체를 만들지 않고 좌표·값만 반환한다.

## 새 해석 종류를 추가할 때

`features/analysis/common/module.py`의 `AnalysisModule`을 구현하고, 해석
전용 검증·설정·실행만 해당 패키지(`features/analysis/<kind>/`)에 둔다. 공통
모델(`core.domain.StructuralModel`)과 결과 형식(`core.domain.AnalysisResult`)은
그대로 재사용한다. `features/analysis/buckling/module.py`가 이 패턴의 참고
예시다 (요소 좌굴모드 고유치 해석: 정적해석 2회 + SciPy 일반화 고유치문제,
`infrastructure/opensees/buckling_solver.py`에서 실제 계산).

새 해석이 "새로운 요소 종류"(면요소 등)를 다루는 경우는 해석 모듈을 새로 만드는
문제가 아니다 — `docs/architecture.md`의 "면요소" 절 소유 지도를 참고한다.

요구사항이 확정되기 전에는 절점 수·OpenSees 요소명·필드명을 추측해서 도메인
타입을 새로 만들지 않는다. 코드가 들어갈 패키지 위치와, 재사용해야 할 기존
개념(어떤 걸 새로 만들면 안 되는지)만 먼저 정한다.

## 개발 명령

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m openframe        # 앱 실행
pytest                      # 테스트
ruff check .                # 린트
```

- Python 3.12 전용, `src/` 레이아웃 (`pyproject.toml` 참고).
- 업로드 코드 실행에 필요해 `numpy`/`scipy`가 openframe 자체 코드(특히
  `buckling_solver.py`)에서도 쓰인다 — 단순 "예제 실행용"이 아니다.
