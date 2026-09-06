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

## 면요소 (전단벽·슬래브) — 자리만 정해 둠

전단벽과 슬래브는 **새 해석 종류가 아니다.** 보·기둥과 같이 모델에 들어가는
면요소이고, 이미 있는 Linear Static / Nonlinear Static / Time History가
같은 `StructuralModel`을 풀어 낸다. `features/analysis/shear_wall/` 같은
`AnalysisModule` 패키지를 만들지 않는다.

2D 캔버스는 선부재(보·기둥·트러스) 도면이고, 면요소 모델링·표시는 3D 쪽에
둔다. 역할이 다르다.

요구가 정해지기 전에는 절점 수, OpenSees 요소명, 두께·재료 필드를 추측해서
도메인 타입을 만들지 않는다. 코드가 들어갈 패키지와, 절대 재사용하면 안 되는
기존 개념만 고정한다.

### 소유 지도

| 책임 | 경로 | 이유 |
|---|---|---|
| 면요소 도메인 타입 | `core/domain/surfaces.py` | Qt·OpenSees 없는 공통 데이터. `Element`는 `node_i`/`node_j` 두 절점만 갖는다. |
| 외곽선→메시, 연결 | `features/model/surfaces/` | `features/model/drawing/`과 같이 순수 기하. 그리기 위젯은 `presentation/`에 남긴다. |
| OpenSees 요소 명령 | `features/analysis/statics/surfaces.py` | `solver.py`와 `opensees_script_export.py`가 호출. GUI는 OpenSees를 부르지 않는다. |
| 면 응력·결과 표 데이터 | `features/results/surfaces/` | 부재 `stress.py`와 같은 순수 계산. 위젯은 `results/presentation/`. |
| 3D 면 표시 | `features/viewport/.../quick3d_scene_bridge.py` | 부재 큐브와 같은 브릿지 페이로드. viewport가 results를 역수입하지 않는다. |

해석 종류 패키지(`linear_static`, `nonlinear_static`, `time_history`, …)는
면요소가 생겨도 그대로 두고, 요소 생성만 `statics/surfaces.py`로 모은다.

### 면요소가 아닌 것

- **`FloorLoadEntry` / `floor_tributary.py`** — 바닥 하중을 주변 보의
  `UniformElementLoad`로 바꾸는 하중 경로다. 슬래브 강성이 아니다.
- **`RigidDiaphragm`** — 층 평면의 강체 구속이다. 슬래브 요소가 아니다.
- **`ElementResult.local_forces`** — 지금 형식은 보 단부력(6 또는 12)이다.
  셸 결과는 여기 길이를 늘려 끼워 넣지 말고, 면요소용 결과 필드를 따로 둔다.

### 의존 규칙 (면요소에도 동일)

- `core`는 PySide6·OpenSeesPy를 참조하지 않는다.
- 캔버스·QML은 OpenSees를 직접 호출하지 않는다.
- 응력·메시 계산 모듈은 Qt 그래픽 객체를 만들지 않는다.

## 실행 프로세스

사용자가 업로드한 Python 파일은 GUI 프로세스에서 실행하지 않습니다.
`infrastructure/opensees/runner.py`가 worker를 시작하고, worker가 구조모델과 결과를
직렬화 가능한 공통 데이터로 반환합니다.
