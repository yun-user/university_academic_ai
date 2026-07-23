# 출처를 보여주는 대학 학사정보 AI 도우미

대학의 공개 학사 자료와 관리자가 등록한 문서를 검색하고, 답변 근거의
문서명·페이지 또는 URL·원문을 함께 표시하기 위한 졸업작품 프로젝트입니다.

현재 저장소는 **1단계 프로젝트 기본 구조**까지만 구현되어 있습니다.
PDF 추출, 벡터 검색, 웹 수집, LLM 답변 생성은 아직 구현하지 않았습니다.

## 현재 구현 내용

- Python 패키지와 후속 기능별 폴더 구조
- TOML 기본 설정과 `.env` 환경변수 오버라이드
- API 키가 없어도 시작되는 검색 전용 모드
- 문서 청크·근거·답변 데이터 계약
- 비밀값을 마스킹하는 기본 로깅
- Streamlit 시작 화면

## 요구 환경

- Python 3.11 이상
- Windows PowerShell 5.1 이상 또는 PowerShell 7 이상
- 인터넷 연결: 최초 Python 패키지 설치에만 필요

Python 버전은 다음 명령으로 확인합니다.

```powershell
py --version
```

## 설치

PowerShell에서 프로젝트 폴더로 이동한 뒤 다음 명령을 순서대로 실행합니다.

```powershell
Set-Location <프로젝트 폴더>
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

이미 정상적인 `.venv`가 있다면 가상환경 생성 명령은 건너뛰고 활성화부터
진행합니다.

PowerShell 실행 정책 때문에 가상환경 활성화가 차단되면 현재 터미널에서만
다음 설정을 적용한 후 다시 활성화합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 환경 설정

예제 파일을 복사해 로컬 전용 `.env`를 만듭니다.

```powershell
Copy-Item .env.example .env
```

`.env`의 `LLM_API_KEY`는 기본적으로 비어 있습니다. 그대로 두면 애플리케이션은
정상적으로 **검색 전용 모드**로 시작합니다. 실제 키는 `.env`에만 입력하고
소스 코드, `.env.example`, Git 커밋에는 넣지 마세요.

주요 설정 우선순위는 다음과 같습니다.

1. 현재 프로세스의 환경변수
2. 프로젝트 루트의 `.env`
3. `config/defaults.toml`

모델 ID, revision, 데이터 경로, 검색 수, 수집 제한은 설정 파일이나
환경변수로 변경할 수 있으며 Python 코드 수정이 필요하지 않습니다.

## 실행

```powershell
python -m streamlit run app.py
```

기본 브라우저가 열리지 않으면 터미널에 표시되는 로컬 URL을 브라우저에서
여세요. 종료할 때는 실행 중인 PowerShell에서 `Ctrl+C`를 누릅니다.

## 기본 검증

Python 문법과 핵심 모듈 import를 확인할 수 있습니다.

```powershell
python -m compileall app.py src
python -c "from src.config import get_settings; from src.models import DocumentChunk; print(get_settings().runtime_mode)"
```

정상적인 기본 출력 모드는 `retrieval-only`입니다. 이 검증은 모델 파일을
다운로드하거나 PDF, ChromaDB, LLM API에 연결하지 않습니다.

## 현재 폴더 구조

```text
university_academic_ai/
├── app.py
├── pages/                     # 후속 Streamlit 화면
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── logging_config.py
│   ├── models.py
│   ├── ingestion/             # 후속 PDF·웹 수집
│   ├── retrieval/             # 후속 하이브리드 검색
│   ├── generation/            # 후속 근거 제한 답변 생성
│   ├── evaluation/            # 후속 평가
│   └── utils/
├── config/
│   └── defaults.toml
├── data/
│   ├── raw/
│   ├── processed/
│   ├── snapshots/
│   ├── catalog/
│   ├── vector_db/
│   ├── keyword_index/
│   ├── quarantine/
│   └── sample/
├── evals/
├── tests/
├── docs/
├── .env.example
├── requirements.txt
└── README.md
```

## 안전 원칙

- 실제 학교 정보는 검증된 문서를 등록하기 전까지 코드에 작성하지 않습니다.
- 원본 문서는 자동으로 삭제하거나 덮어쓰지 않습니다.
- API 키와 내부 절대경로를 화면이나 로그에 표시하지 않습니다.
- 로그인 우회나 비공개 페이지 수집은 구현 대상이 아닙니다.
- 검색 근거가 충분하지 않으면 일반 지식으로 답을 보완하지 않습니다.

## 다음 구현 단계

다음 단계는 PDF를 등록하고 물리 페이지 번호를 유지하면서 텍스트를 추출하는
기능입니다. 이 단계에서는 아직 검색 색인이나 LLM 호출을 추가하지 않습니다.
