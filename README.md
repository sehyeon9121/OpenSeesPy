# OpenFrame Studio

OpenSeesPy 코드에서 2D 구조모델을 읽어 시각화하고, 해석 결과를 변형 형상과
축력도·전단력도·휨모멘트도로 보여주는 데스크톱 프로그램입니다.

## 개발 원칙

- 화면, 구조모델, 해석 엔진, 시각화와 다이어그램 계산을 서로 분리합니다.
- `core/domain`의 데이터 모델은 PySide6와 OpenSeesPy를 직접 참조하지 않습니다.
- 업로드한 Python 코드는 GUI 프로세스가 아닌 별도 worker 프로세스에서 실행합니다.
- 다이어그램 계산은 Qt 그림 객체가 아닌 좌표와 값으로 결과를 반환합니다.
- 선형정적·비선형정적·시간이력 해석은 각각 독립 모듈로 확장합니다.

## 폴더 안내

| 경로 | 역할 |
|---|---|
| `src/openframe/app/shell` | 메인 창, 상단 헤더, 기능 탭과 전체 화면 조립 |
| `src/openframe/core` | 공통 구조모델, 해석 요청·결과, 외부 기능 계약 |
| `src/openframe/features/model` | 코드 검사, 모델 가져오기·검증과 왼쪽 패널 |
| `src/openframe/features/analysis` | 선형·비선형·시간이력 해석과 설정 패널 |
| `src/openframe/features/results` | 변형·반력·N·V·M 계산과 결과 패널 |
| `src/openframe/features/viewport` | 2D 구조 장면, 그래픽 항목과 표시 제어 |
| `src/openframe/infrastructure/opensees` | 실제 OpenSeesPy 실행과 worker 통신 |
| `src/openframe/infrastructure/persistence` | 프로젝트와 설정 저장 구현 |
| `tests` | 각 모듈의 독립 테스트 |
| `examples` | 개발 및 검증용 OpenSeesPy 예제 |
| `installer` | 최종 Windows 설치 파일 설정 |

자세한 의존 방향은 [`docs/architecture.md`](docs/architecture.md)를 참고합니다.

## 개발 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m openframe
```

VS Code에서는 `.vscode/launch.json`의 **OpenFrame Studio 실행** 구성을 선택하고 `F5`를
누르면 프로젝트 가상환경으로 프로그램이 시작됩니다. 테스트는 VS Code 테스트 패널이나
`OpenFrame: 테스트` 작업으로 실행할 수 있습니다.
