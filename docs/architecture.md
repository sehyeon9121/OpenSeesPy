# 프로그램 구조와 의존 규칙

## 기능 중심 패키지

프로그램의 네 가지 작업영역과 소스 패키지를 동일하게 구성합니다.

| 화면 | 기능 패키지 | 책임 |
|---|---|---|
| MODEL | `features/model` | 파일 검사, 모델 변환·검증, 모델 정보 표시 |
| ANALYSIS | `features/analysis` | 해석 방법, 설정, 실행 유스케이스 |
| RESULTS | `features/results` | 변형, 반력, N·V·M 계산과 표시 |
| VIEWPORT | `features/viewport` | 구조 장면, 그래픽 항목, 확대·선택·필터 |

`app/shell`은 이 네 기능의 화면을 배치하고 신호를 연결할 뿐, 구조해석이나 결과 계산을
직접 수행하지 않습니다.

## 데이터 흐름

```text
OpenSeesPy 파일
    ↓
features.model.importers
    ↓
infrastructure.opensees.worker
    ↓
core.domain.StructuralModel
    ↓
features.analysis → core.domain.AnalysisResult
    ↓
features.results + features.viewport
    ↓
app.shell
```

## 의존 방향

```text
app.shell ───────────────→ features.* ─────→ core
                               ↑              ↑
infrastructure.opensees ───────┴──────────────┘
```

- `core`는 PySide6와 OpenSeesPy를 참조하지 않습니다.
- `features`끼리는 공통 데이터를 직접 복제하지 않고 `core.domain`을 사용합니다.
- `infrastructure`는 `core.contracts`를 구현합니다.
- GUI가 OpenSeesPy를 직접 호출하는 구조는 금지합니다.
- 다이어그램 계산 코드가 Qt 그래픽 객체를 생성하는 구조는 금지합니다.

## 해석 확장 규칙

- `features/analysis/linear_static`: 선형 정적해석
- `features/analysis/nonlinear_static`: 재료·기하 비선형 정적해석
- `features/analysis/time_history`: 시간이력해석

새로운 해석 종류를 추가할 때는
`features/analysis/common/module.py`의 `AnalysisModule`을 구현합니다. 공통 모델과 결과
형식은 유지하고 해석 종류별 검증·설정·실행만 해당 패키지에 둡니다.

## 실행 프로세스

사용자가 업로드한 Python 파일은 GUI 프로세스에서 실행하지 않습니다.
`infrastructure/opensees/runner.py`가 worker를 시작하고, worker가 구조모델과 결과를
직렬화 가능한 공통 데이터로 반환합니다.
