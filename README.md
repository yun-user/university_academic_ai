# 출처를 보여주는 대학 학사정보 AI 도우미

대학의 공개 학사 자료와 관리자가 등록한 문서를 검색하고, 답변 근거의
문서명·페이지 또는 URL·원문을 함께 표시하기 위한 졸업작품 프로젝트입니다.

현재 저장소에는 PDF 페이지별 텍스트 추출과 **검색 전용 dense retrieval**까지
구현되어 있으며 Streamlit 사용자 화면에서 관련 PDF 원문을 검색할 수 있습니다.
웹 공지 수집과 LLM 답변 생성은 아직 구현하지 않았습니다.

## 현재 구현 내용

- Python 패키지와 후속 기능별 폴더 구조
- TOML 기본 설정과 `.env` 환경변수 오버라이드
- API 키가 없어도 시작되는 검색 전용 모드
- PyMuPDF 기반 PDF 목록 조회와 페이지별 텍스트 추출
- 빈 페이지·실패 페이지 처리와 물리 페이지 번호 보존
- 페이지 경계를 넘지 않는 검색 청크와 출처 메타데이터 생성
- sentence-transformers 기반 한국어 임베딩 어댑터
- 외부 임베딩을 사용하는 ChromaDB 영속 색인과 Top-K 검색
- 최소 점수 필터, 중복 청크 제거, 문서별 삭제·재색인 인터페이스
- 색인 메타데이터 기반 학과·문서 유형 사전 필터
- 비밀값을 마스킹하는 기본 로깅
- 질문·출처·페이지·검색 점수·원문을 표시하는 Streamlit 검색 화면

## 요구 환경

- Python 3.11 이상
- Windows PowerShell 5.1 이상 또는 PowerShell 7 이상
- 인터넷 연결: 최초 패키지 설치와 임베딩 모델 다운로드에 필요
- API 키: PDF 등록·검색에는 필요 없음

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

이번 검색 단계의 핵심 환경변수는 다음과 같습니다.

| 환경변수 | 의미 |
|---|---|
| `EMBEDDING_MODEL_NAME` | sentence-transformers 모델 ID 또는 로컬 경로 |
| `CHUNK_SIZE` | 청크 목표 문자 수 |
| `CHUNK_OVERLAP` | 인접 청크 겹침 문자 수 |
| `TOP_K` | 반환할 최대 검색 결과 수 |
| `MIN_RETRIEVAL_SCORE` | 허용할 최소 cosine 유사도 |
| `VECTOR_DB_PATH` | 프로젝트 내부 ChromaDB 영속 경로 |

`VECTOR_DB_PATH`는 원본 보존 영역인 `RAW_DATA_DIR` 안으로 지정할 수 없습니다.
이전 이름인 `CHUNK_TARGET_CHARS`, `CHUNK_OVERLAP_CHARS`, `EVIDENCE_TOP_K`,
`VECTOR_DB_DIR`도 fallback으로 읽지만 위 표의 이름이 우선합니다.

## 실행

```powershell
python -m streamlit run app.py
```

기본 브라우저가 열리지 않으면 터미널에 표시되는 로컬 URL을 브라우저에서
여세요. 종료할 때는 실행 중인 PowerShell에서 `Ctrl+C`를 누릅니다.

화면에서 질문과 학과·문서 유형을 선택하고 `검색`을 누르면 관련 원문이
문서명, PDF 페이지 번호, cosine 검색 점수와 함께 표시됩니다. 학과와 문서
유형 선택지는 현재 ChromaDB 색인에 실제로 존재하는 메타데이터에서 만듭니다.
이 화면은 LLM 답변을 생성하지 않습니다.

## 통합 corpus 생성

PDF, CSV, TXT 원본과 manifest를 다시 읽어 통합 JSONL을 생성합니다.

```powershell
python -m src.ingestion.build_corpus
```

결과는 `data/processed/documents.jsonl`과
`data/processed/ingestion_report.json`에 UTF-8(BOM 없음)로 저장됩니다.
Windows PowerShell 5.1은 BOM 없는 UTF-8 파일을 기본 CP949로 오해할 수 있으므로
내용을 확인할 때 인코딩을 명시해야 합니다.

```powershell
Get-Content -Encoding UTF8 .\data\processed\documents.jsonl
Get-Content -Encoding UTF8 .\data\processed\ingestion_report.json
```

편집기에서도 파일 인코딩을 UTF-8로 선택하세요. 깨져 보이는 문자열을 다시
저장하면 원래 정상인 UTF-8 데이터가 실제로 손상될 수 있습니다.

## PDF 색인과 검색

검색할 원본 PDF를 `data/raw/pdfs`에 복사합니다. 색인·삭제·재색인 명령은
이 원본 파일을 수정하거나 삭제하지 않습니다.

```powershell
Copy-Item "C:\path\to\document.pdf" .\data\raw\pdfs\
python -m scripts.search_pdfs index
```

한국어 질문으로 관련 청크를 검색합니다. 결과 JSON에는 문서명,
1부터 시작하는 PDF 페이지 번호, 원문, cosine 검색 점수가 포함됩니다.

```powershell
python -m scripts.search_pdfs search "졸업하려면 전공학점을 몇 학점 들어야 해?"
python -m scripts.search_pdfs search "장학금 선발 기준" --top-k 5 --min-score 0.40
```

첫 실제 색인 또는 검색 시 설정된 sentence-transformers 모델을 다운로드할 수
있습니다. 이후에는 로컬 모델 캐시를 사용하며 API 키는 필요하지 않습니다.

문서별 색인 삭제와 재색인은 색인 결과의 `document_id`를 사용합니다.

```powershell
$documentId = "색인 결과에 표시된 document_id"
python -m scripts.search_pdfs delete-index $documentId
python -m scripts.search_pdfs reindex .\data\raw\pdfs\document.pdf $documentId
```

Python 코드에서는 서비스의 context manager를 사용하면 Windows의 ChromaDB
파일 잠금이 명령 종료 시 해제됩니다.

```python
from src.retrieval.search_service import PdfSearchService

with PdfSearchService.from_settings() as service:
    results = service.search("휴학 신청 기간", top_k=5)
    for result in results:
        print(result.document_title, result.page_number, result.score)
```

## 기본 검증

Python 문법과 핵심 모듈 import를 확인할 수 있습니다.

```powershell
python -m compileall app.py src scripts tests
python -c "from src.config import get_settings; from src.models import DocumentChunk; print(get_settings().runtime_mode)"
python -m pytest -q
```

정상적인 기본 출력 모드는 `retrieval-only`입니다. 테스트는 외부 모델 다운로드
대신 fake 임베딩을 사용하고 임시 ChromaDB에서 영속 저장과 재로딩을 검증합니다.
LLM API에는 연결하지 않습니다.

## 현재 폴더 구조

```text
university_academic_ai/
├── app.py
├── pages/                     # 후속 관리자·평가 화면
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── logging_config.py
│   ├── models.py
│   ├── ingestion/
│   │   ├── pdf_extractor.py   # 페이지별 PDF 추출
│   │   ├── pdf_models.py      # 추출 결과 계약
│   │   └── chunker.py         # 페이지 보존 검색 청킹
│   ├── retrieval/
│   │   ├── embeddings.py      # 한국어 임베딩 어댑터
│   │   ├── vector_store.py    # ChromaDB 영속 저장
│   │   └── search_service.py  # 색인·검색·삭제·재색인
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
├── scripts/search_pdfs.py     # PowerShell용 검색 CLI
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

다음 단계 후보는 한국어 키워드 검색(BM25)과 dense 검색을 결합한 하이브리드
검색, 평가 데이터셋 기반 임계값 보정입니다. LLM 답변 생성과 관리자 문서 관리
화면은 별도 단계로 유지합니다.
