# 출처를 보여주는 대학 학사정보 AI 도우미 - 구현 체크리스트

> 초기 단계별 계획을 보존한 문서입니다. 체크되지 않은 항목이 모두 현재 오류라는 뜻은 아니며, 문서의 기능 목록 전체를 구현 완료로 발표해서도 안 됩니다. 현재 기능·검증 범위는 [사용설명서](사용설명서.md)와 [최신 검토 보고서](저장소검토_2026-10-01.md)를 확인하세요.

## 사용 방법

이 문서는 다음 Codex 구현 작업의 실행 순서와 완료 기준이다. 현재 문서에는 구현 코드가 포함되어 있지 않다. 각 단계는 **구현 → 자동 테스트 → 샘플 검증 → 문서 갱신**까지 끝나야 완료로 표시한다.

다음 규칙을 모든 단계에 적용한다.

- [ ] 한 번에 한 단계만 구현하고 범위를 넓히기 전에 해당 단계의 수용 기준을 통과한다.
- [ ] 사용자 Desktop의 원본 네 파일을 수정·이동·삭제하지 않는다.
- [ ] `.env`와 API 키를 커밋, 로그, UI, 테스트 fixture에 넣지 않는다.
- [ ] 모델 ID, revision, 경로, top-K, 임계값을 코드에 직접 고정하지 않는다.
- [ ] PDF 페이지는 내부 0-based와 공개 1-based를 명시적으로 구분한다.
- [ ] 원본과 SQLite를 정본, Chroma와 BM25를 파생 색인으로 유지한다.
- [ ] 새 색인이 검증되기 전 기존 활성 색인을 교체하지 않는다.
- [ ] LLM이 없어도 등록·검색·출처·디버그·검색 평가가 동작한다.
- [ ] 근거 부족 시 지정 문구 외의 추측 답변을 만들지 않는다.
- [ ] 각 단계에서 관련 테스트와 README/설계 변경을 함께 갱신한다.

## 0. 구현 시작 전 확인

### 입력 자료

- [ ] `2024_장학금선정기준.pdf`가 읽기 가능한지 확인한다.
- [ ] `(20260211)2026 교과과정책자 합본(안)_f1.pdf`가 읽기 가능한지 확인한다.
- [ ] `교과과정.pdf`가 읽기 가능한지 확인한다.
- [ ] `학교정보.txt`가 UTF-8로 읽히는지 확인한다.
- [ ] 원본 hash와 파일 크기만 기록하고 원본 디렉터리에 산출물을 만들지 않는다.
- [ ] 테스트용 복사본 또는 비식별 파생 fixture는 프로젝트의 허용된 테스트 경로에만 만든다.

### 설계 기준

- [ ] `docs/PROJECT_PLAN.md`의 목표, 비목표, 설계 가정을 읽는다.
- [ ] `docs/ARCHITECTURE.md`의 계층, metadata 계약, 포트, 폴더 구조를 읽는다.
- [ ] 구현과 다른 결정을 내릴 경우 ADR 또는 문서 변경으로 이유를 남긴다.
- [ ] Python 3.11 이상과 Tesseract `kor+eng` 설치 가능 여부를 확인한다.
- [ ] 발표 장비의 CPU, RAM, 인터넷 사용 가능 여부를 기록한다.

## 1단계: 프로젝트 기본 구조와 설정

### 구조

- [ ] `src/university_academic_ai` 패키지와 설계된 하위 디렉터리를 만든다.
- [ ] `app.py`와 세 개의 Streamlit page entrypoint를 최소 부팅 상태로 만든다.
- [ ] `bootstrap.py`를 유일한 composition root로 둔다.
- [ ] domain이 Streamlit, Chroma, OpenAI를 import하지 않는지 확인한다.
- [ ] application service가 infrastructure concrete type을 직접 요구하지 않게 한다.

### 설정

- [ ] `config/defaults.toml`에 비밀이 아닌 기본값을 둔다.
- [ ] `.env.example`에 필요한 키 이름, 의미, 필수 여부를 설명한다.
- [ ] `.env`를 `.gitignore`에 포함한다.
- [ ] 임베딩 모델 ID/revision/device/prefix/normalize/max length를 설정화한다.
- [ ] reranker ID/revision/enabled를 설정화한다.
- [ ] LLM provider/model/base URL/API key/timeout을 설정화한다.
- [ ] Chroma, SQLite, raw/processed/snapshot/index 경로를 설정화한다.
- [ ] chunk, top-K, RRF, crawl, upload, OCR 기본값을 설정화한다.
- [ ] UTC 저장과 Asia/Seoul 표시를 설정한다.

### 도메인·포트

- [ ] Document, DocumentVersion, PageArtifact, TableArtifact, Chunk 모델을 정의한다.
- [ ] SearchHit, Evidence, Claim, Citation, AnswerBundle 모델을 정의한다.
- [ ] 문서·페이지·작업·답변·검증 상태 enum을 정의한다.
- [ ] `RawObjectStorePort`, `DocumentCatalogPort`, `JobRepositoryPort`를 정의한다.
- [ ] extractor/OCR/table/web/chunker 포트를 정의한다.
- [ ] embedding/vector/keyword/reranker/LLM/verifier/confidence 포트를 정의한다.
- [ ] library exception을 domain error로 변환하는 규칙을 정의한다.

### SQLite 기반

- [ ] `schema.sql`에 documents, versions, pages, tables, chunks, jobs, index manifests를 정의한다.
- [ ] crawl runs, duplicate relations, query traces, audit events를 정의한다.
- [ ] 외래키와 `chunk_id` 유일성 제약을 추가한다.
- [ ] 논리 문서당 활성 버전 하나를 보장한다.
- [ ] schema version과 migration 방침을 기록한다.

### 1단계 테스트와 완료 기준

- [ ] `.env` 없이 앱과 CLI가 retrieval-only 모드로 부팅된다.
- [ ] 잘못된 경로, enum, 날짜, 모델 설정을 시작 시 검증한다.
- [ ] 로그 redaction 테스트에서 API 키와 비밀값이 보이지 않는다.
- [ ] domain import graph에 infrastructure 역참조가 없다.
- [ ] 임시 SQLite 생성·schema 적용·rollback 테스트가 통과한다.
- [ ] `pytest` 기본 실행이 성공한다.

## 2단계: PDF 등록과 페이지별 텍스트 추출

### 안전한 원본 등록

- [ ] 확장자뿐 아니라 MIME과 `%PDF` 매직 바이트를 검사한다.
- [ ] 파일 크기와 PDF 페이지 수 제한을 적용한다.
- [ ] 암호화 PDF의 비밀번호를 우회하지 않고 명시적 오류로 중단한다.
- [ ] 손상 PDF와 페이지별 추출 오류를 구분한다.
- [ ] 스트리밍 SHA-256 후 내부 document/version ID 경로로 복사한다.
- [ ] 저장 후 hash를 다시 확인한다.
- [ ] 원래 파일명은 metadata로만 보존한다.
- [ ] 동일 파일 hash를 exact duplicate로 판정한다.

### 페이지 추출

- [ ] PyMuPDF로 페이지, block, bbox, font, image, page label을 추출한다.
- [ ] `page_index`는 0-based 내부값, `page_number`는 1-based 공개값으로 저장한다.
- [ ] 인쇄 페이지 표기는 `printed_page_label`로 분리한다.
- [ ] raw/display/normalized text를 분리 저장한다.
- [ ] `U+0000`, zero-width, 비표시 제어문자를 제거한다.
- [ ] 숫자, 날짜, 학점, 학수번호, 목록, 부정 표현은 보존한다.
- [ ] 반복 머리말·꼬리말은 좌표와 반복 빈도로 판정한다.
- [ ] PDF 생성일을 게시일로 자동 사용하지 않는다.

### TXT 추출

- [ ] UTF-8과 UTF-8-SIG를 먼저 시도한다.
- [ ] 실패할 때만 charset-normalizer로 인코딩을 감지한다.
- [ ] 감지 신뢰도가 낮으면 자동 활성화하지 않고 관리자 검토로 보낸다.
- [ ] 원본 줄바꿈과 line start/end를 보조 위치 정보로 보존한다.
- [ ] 페이지·공식 URL이 없는 TXT를 최종 학사 주장 단독 근거로 사용하지 않는다.

### 스캔·OCR

- [ ] 페이지별 text length, image coverage, 대체문자 비율을 계산한다.
- [ ] `EMPTY_EXPECTED`와 `OCR_REQUIRED`를 구분한다.
- [ ] `kor+eng`, 250-300 DPI OCR을 설정 가능하게 한다.
- [ ] OCR word bbox와 confidence를 저장한다.
- [ ] OCR 엔진 미설치 시 빈 청크를 만들지 않는다.
- [ ] 평균 confidence와 숫자성 셀 confidence에 품질 상태를 부여한다.
- [ ] 저품질 페이지는 관리자 승인 전 답변 evidence에서 제외한다.

### 표

- [ ] PyMuPDF 표 탐지를 기본으로 구현한다.
- [ ] pdfplumber line/text fallback 경계를 둔다.
- [ ] table ID, bbox, header, cell, merged range, footnote를 저장한다.
- [ ] 행·열 수, header, cell coverage, blank ratio, 숫자 연결률을 품질 지표로 계산한다.
- [ ] 큰 표를 극소수 행으로만 탐지한 실패를 `TABLE_EXTRACTION_LOW_QUALITY`로 분류한다.

### 개인정보

- [ ] 주민등록번호, 전화번호, 이메일, 학번, 계좌번호, 주소 후보를 페이지별 탐지한다.
- [ ] 경고에는 마스킹된 일부만 표시한다.
- [ ] 고위험 패턴 문서를 quarantine하고 자동 색인하지 않는다.
- [ ] 관리자가 검토할 수 있지만 원본을 자동 수정·삭제하지 않는다.

### 2단계 샘플 수용 기준

- [ ] 장학금 PDF가 정확히 2개 물리 페이지로 등록된다.
- [ ] 장학금 PDF 정규화문에 `U+0000`이 남지 않는다.
- [ ] 장학금 PDF의 숫자·날짜·목록이 렌더링 원문과 대조된다.
- [ ] 이미지형 `교과과정.pdf` 4쪽 모두 OCR 분기로 들어간다.
- [ ] OCR 미설치 시 `OCR_ENGINE_MISSING`이 관리자에게 표시되고 READY가 되지 않는다.
- [ ] 237쪽 책자의 페이지 수가 보존된다.
- [ ] 물리 193쪽과 문서 표기 `A-6`, 물리 194쪽과 `A-7`이 구분된다.
- [ ] 표지·간지의 무텍스트 페이지가 본문 OCR 실패와 구분된다.
- [ ] 237쪽 책자의 단순 표와 복잡한 병합 표에 다른 품질 상태가 기록된다.
- [ ] `학교정보.txt`가 UTF-8로 깨짐 없이 읽히고 seed 설정 자료로 분류된다.

## 3단계: 청크 생성과 벡터·키워드 색인

### 청크

- [ ] 계층을 문서→페이지→절→블록/표→청크로 유지한다.
- [ ] 일반 문단 시작값을 450-700자, 최대 약 900자, overlap 80-120자로 설정한다.
- [ ] 실제 모델 tokenizer 길이가 한도의 70-80%를 넘지 않게 한다.
- [ ] 문장, 번호 목록, 조건, 예외를 우선 경계로 사용한다.
- [ ] PDF content 청크가 두 물리 페이지를 넘지 않게 검증한다.
- [ ] 짧은 마감일·필수요건 항목을 임의로 이웃 내용에 묻히게 하지 않는다.
- [ ] 표를 header + 5-10행 단위로 자른다.
- [ ] 모든 분할 표 청크에 header, 학과, 학년, 학기 문맥을 반복한다.
- [ ] content와 embedding_text를 분리한다.
- [ ] content hash와 embedding input hash를 분리한다.
- [ ] deterministic chunk ID를 사용한다.

### 필수 metadata

- [ ] `document_id`
- [ ] `chunk_id`
- [ ] `document_title`
- [ ] `document_type`
- [ ] `department`
- [ ] `category`
- [ ] `source_path`
- [ ] `source_url`
- [ ] `page_number`
- [ ] `section_title`
- [ ] `published_date`
- [ ] `collected_at`
- [ ] `content`
- [ ] `content_hash`
- [ ] PDF는 page number, 웹은 source URL·published date가 필수라는 교차 검증을 구현한다.
- [ ] 비어 있는 content를 색인하지 않는다.

### 임베딩

- [ ] 기준선 모델을 환경/설정에서 읽는다.
- [ ] E5 계열의 `query:`와 `passage:` prefix를 어댑터가 적용한다.
- [ ] revision, dimension, normalize, pooling, max length, prefix를 fingerprint에 포함한다.
- [ ] 모델 cache와 device fallback을 구현한다.
- [ ] 차원이 다른 벡터를 같은 컬렉션에 넣지 않는다.
- [ ] 모델 로딩 실패 시 안전한 오류와 재시도 정보를 제공한다.

### Chroma

- [ ] PersistentClient를 어댑터 뒤에 둔다.
- [ ] scalar filter metadata만 projection하고 full metadata는 SQLite에서 hydrate한다.
- [ ] staging collection과 active pointer를 분리한다.
- [ ] idempotent upsert와 document ID 기반 delete를 구현한다.
- [ ] health, count, revision 검사를 구현한다.

### BM25

- [ ] Kiwi 형태소, 원 토큰, 숫자·단위·학수번호를 보존한다.
- [ ] 규정 의미어 `이상/이하/제외/불가`를 stopword로 제거하지 않는다.
- [ ] 학과 별칭과 학사 용어 사전을 설정에서 읽는다.
- [ ] Chroma와 같은 canonical chunk ID와 revision을 사용한다.
- [ ] 저장, 로드, 재생성, 삭제를 어댑터 뒤에 둔다.

### 3단계 완료 기준

- [ ] 동일 문서를 두 번 색인해도 같은 chunk ID가 중복되지 않는다.
- [ ] 활성 SQLite chunk 수, Chroma ID 수, BM25 ID 수가 일치한다.
- [ ] 모든 Chroma 결과가 SQLite canonical metadata로 hydrate된다.
- [ ] 모델 fingerprint 변경 시 새 index revision이 요구된다.
- [ ] partial duplicate 자료의 유사 청크가 같은 duplicate group으로 탐지된다.
- [ ] 샘플 표 행 검색용 텍스트가 열 header와 값을 올바르게 연결한다.

## 4단계: 질문 검색과 출처 반환

### QueryPlan

- [ ] Unicode, 공백을 안전하게 정규화하고 숫자·연도·부정 표현을 보존한다.
- [ ] 의도, 학과, 범주, 입학연도, 학년도, 학기, 기준일을 추출한다.
- [ ] 질문이 요구하는 숫자·날짜·학점·조건·예외 슬롯을 기록한다.
- [ ] hard filter와 soft boost를 구분한다.
- [ ] 학교 캘린더로 `이번 학기`를 해석한다.
- [ ] 캘린더가 없으면 현재 시점을 임의 추정하지 않는다.

### 범위와 안전

- [ ] 학사 범위 밖 질문을 분류한다.
- [ ] 개인 성적·수혜 여부처럼 개인 학적 시스템이 필요한 질문을 분류한다.
- [ ] 사용자와 문서의 prompt injection 문구를 지시로 실행하지 않는다.
- [ ] 모호 질문은 먼저 넓게 검색하되 적용 조건을 임의 채우지 않는다.

### 하이브리드 검색

- [ ] Dense top-40 시작값을 설정화한다.
- [ ] BM25 top-40 시작값을 설정화한다.
- [ ] Weighted RRF의 k와 channel weight를 설정화한다.
- [ ] missing rank, 동점, 중복 chunk의 결정적 처리 테스트를 만든다.
- [ ] duplicate group collapse를 적용한다.
- [ ] active/version/effective period filter를 적용한다.
- [ ] 사용자가 학과를 명시하면 해당 학과와 공통 문서를 검색한다.
- [ ] 과거 연도를 명시하면 해당 효력 버전을 검색한다.
- [ ] category는 초기에는 soft boost로 시작하고 평가 후 hard filter 여부를 결정한다.

### 재정렬·컨텍스트

- [ ] Cross-Encoder 모델과 revision을 설정화한다.
- [ ] 상위 20개 시작값과 최종 5-8개 시작값을 설정화한다.
- [ ] 모델 미설정·실패 시 RRF fallback을 기록한다.
- [ ] context-only 인접 청크와 실제 evidence를 구분한다.
- [ ] 숫자·날짜 질문에는 해당 값과 단위를 포함한 evidence를 요구한다.

### 검색 결과 계약

- [ ] 문서·chunk ID, channel rank, raw score, score kind를 반환한다.
- [ ] RRF/reranker rank와 filter·제외 이유를 반환한다.
- [ ] 문서명, PDF 물리 페이지 또는 웹 URL·게시일, 원문을 반환한다.
- [ ] 모델·index·tokenizer·parameter revision과 단계별 latency를 trace한다.

### 4단계 완료 기준

- [ ] API 키 없이 샘플 질문의 검색 결과와 출처가 표시된다.
- [ ] 장학금 질문이 장학금 PDF의 올바른 물리 페이지를 찾는다.
- [ ] 교과목 질문이 소프트웨어융합학과 표와 다른 학과 표를 구분한다.
- [ ] 목차 keyword 페이지보다 실제 규정 본문이 우선된다.
- [ ] 2024 자료만 있을 때 `이번 학기` 질문의 현재성 불일치를 trace한다.
- [ ] 관리자는 dense/BM25/RRF/reranker 각 점수를 구분해 볼 수 있다.

## 5단계: LLM 답변 생성과 근거 부족 거절

### Evidence Gate

- [ ] 후보 없음과 low relevance를 구분한다.
- [ ] 학과·연도·학기·입학연도 mismatch를 차단한다.
- [ ] 숫자·날짜·학점 필수 슬롯 누락을 차단한다.
- [ ] current 질문의 stale/unknown version을 차단한다.
- [ ] 충돌 문서의 적용 버전을 결정할 수 없으면 차단한다.
- [ ] PDF page 또는 웹 URL·게시일 누락을 차단한다.
- [ ] low-quality OCR/table evidence를 차단한다.
- [ ] reason code를 trace와 AnswerBundle에 기록한다.

### LLM client

- [ ] OpenAI-compatible client와 Null client가 같은 포트를 구현한다.
- [ ] API key가 없으면 정상 retrieval-only 상태를 반환한다.
- [ ] model, base URL, timeout, retry를 설정화한다.
- [ ] 외부 LLM에 보내는 context를 선택 evidence로 제한한다.
- [ ] PII quarantine 문서를 외부 LLM에 보내지 않는다.

### 프롬프트·구조화 출력

- [ ] 근거만 사용, 일반 상식 금지, 문서 지시 무시 규칙을 포함한다.
- [ ] 각 사실 문장에 evidence ID를 요구한다.
- [ ] 날짜·학점·조건·예외를 근거 없이 만들지 못하게 한다.
- [ ] decision, summary, details, claims, quote spans, needs verification schema를 검증한다.
- [ ] parsing 실패 재시도는 한 번으로 제한한다.
- [ ] 문서명·페이지·URL·신뢰도는 LLM 출력에 의존하지 않는다.

### Citation Builder·Verifier

- [ ] evidence ID가 실제 컨텍스트에 있는지 확인한다.
- [ ] quote가 canonical content의 exact substring인지 확인한다.
- [ ] content hash가 생성 시점과 현재 활성 버전에 일치하는지 확인한다.
- [ ] 숫자, 날짜, 학점, `이상/이하`, `가능/불가`를 비교한다.
- [ ] 학과, 학년도, 학기, 입학연도를 비교한다.
- [ ] 핵심 claim은 `SUPPORTED`만 허용한다.
- [ ] 보조 claim 실패 시 제거 후 재검증한다.
- [ ] 핵심 claim 실패 시 답변 전체를 폐기한다.

### 신뢰도

- [ ] 사용자에게 raw cosine을 정답 확률로 표시하지 않는다.
- [ ] calibration 전에는 `미보정`과 높음/보통 등급·이유만 표시한다.
- [ ] 기준 미달은 낮은 신뢰도 답변 대신 거절한다.
- [ ] 관리자는 raw·fusion·reranker·gate 특징을 확인할 수 있다.

### 5단계 필수 거절 테스트

- [ ] `이번 학기 장학금 신청 기간은?`을 2024 자료만으로 답하지 않는다.
- [ ] `휴학 신청 기간은?`에 근거가 없으면 지정 문구를 정확히 반환한다.
- [ ] `재수강하면 기존 성적은 어떻게 돼?`를 관련 없는 교과과정 언급으로 답하지 않는다.
- [ ] `내 성적 알려줘`에 개인 결과를 추정하지 않는다.
- [ ] 범위 밖 질문과 prompt injection에 학사 답변을 생성하지 않는다.
- [ ] 잘못된 evidence ID·페이지·URL이 들어간 mock LLM 출력을 차단한다.
- [ ] 검증 전 생성 텍스트가 UI로 전달되지 않는다.

## 6단계: Streamlit 사용자 화면

### 질문 화면

- [ ] 서비스 범위와 등록 자료만 사용한다는 안내를 표시한다.
- [ ] 등록 문서 수와 마지막 갱신 시각을 표시한다.
- [ ] 질문, 학과, 범주, 문서 유형 필터를 제공한다.
- [ ] 예시 질문과 검색 결과만 보기 토글을 제공한다.
- [ ] 질문 당시 filter/index snapshot을 대화 기록에 유지한다.
- [ ] 빈 질문·길이 초과를 제출 전에 검증한다.

### 상태

- [ ] `AI 답변 가능`, `검색 전용`, `인덱스 미준비`를 구분한다.
- [ ] 자료 없음, 범위 밖, 개인 정보 필요, 시스템 오류를 구분한다.
- [ ] 시스템 오류는 지정 자료 부족 문구로 숨기지 않고 request ID를 보여준다.
- [ ] API key 값이 아닌 설정 여부만 표시한다.

### 답변·출처

- [ ] 핵심 답변, 상세 설명, 신뢰도, 확인 사항, 출처, 원문 순서로 표시한다.
- [ ] claim에 `[근거 N]` 연결을 표시한다.
- [ ] PDF 문서명과 1-based 물리 페이지를 표시한다.
- [ ] 인쇄 쪽수가 있으면 물리 페이지와 병기한다.
- [ ] 웹 문서명, 게시일, 수집일, 안전한 원문 URL을 표시한다.
- [ ] 원문 expander에 quote와 주변 문맥을 표시한다.
- [ ] 중복 출처 카드는 합치되 claim 연결은 보존한다.
- [ ] source_path와 내부 절대 경로를 표시하지 않는다.
- [ ] HTML·Markdown 원문을 실행하지 않고 escape한다.
- [ ] `javascript:`, `data:`, `file:` 링크를 렌더링하지 않는다.

### 접근성·캐시

- [ ] 색상 외에 텍스트와 아이콘으로 상태를 표시한다.
- [ ] 입력에 명확한 label과 도움말을 둔다.
- [ ] 키보드로 질문 제출과 출처 펼치기가 가능하다.
- [ ] model/client 캐시의 thread safety를 확인한다.
- [ ] 개인정보 가능 질문·답변을 사용자 간 공유 캐시에 넣지 않는다.

### 6단계 완료 기준

- [ ] 답변 가능한 샘플, 검색 전용, 근거 부족, 시스템 오류 E2E가 모두 통과한다.
- [ ] 인용 검증 실패 답변이 잠시라도 화면에 나타나지 않는다.
- [ ] 브라우저 새로고침 후 잘못된 이전 filter 상태로 답변이 바뀌지 않는다.
- [ ] 내부 경로, secret, traceback 노출 테스트가 통과한다.

## 7단계: 관리자 문서 관리 화면

### 현황·업로드

- [ ] 활성 문서, 페이지, 청크, 경고, 실패 작업, index revision을 표시한다.
- [ ] PDF/TXT 업로드와 metadata 입력 폼을 제공한다.
- [ ] 파일 크기, 페이지 수, 텍스트 없는 페이지, OCR·표·암호화 경고를 미리 본다.
- [ ] exact/possible/partial duplicate를 표시한다.
- [ ] 개인정보 경고와 관리자 승인 상태를 표시한다.
- [ ] 원본 보존과 사용 권한 확인을 받는다.

### 문서 목록

- [ ] 검색어, 학과, 범주, 유형, 상태, 게시일, 경고로 필터한다.
- [ ] 버전, chunk 수, 마지막 성공 색인, hash 축약값을 표시한다.
- [ ] 한 행 선택 후 상세·작업 패널을 제공한다.
- [ ] 동시에 실행 중인 충돌 작업의 버튼을 비활성화한다.

### 작업 상태

- [ ] 상태를 SQLite job에서 읽고 session state에만 의존하지 않는다.
- [ ] 실제 `완료/전체 페이지`, `완료/전체 청크` 진행률을 표시한다.
- [ ] stage, page/URL, 안전 메시지, retry 가능 여부, job ID를 표시한다.
- [ ] 새로고침 후 job ID로 상태를 복원한다.
- [ ] stale heartbeat는 즉시 실패가 아닌 확인 필요 상태로 표시한다.

### 삭제·재색인

- [ ] UI 용어를 `검색에서 삭제`로 명확히 한다.
- [ ] 문서명/ID 재입력 2단계 확인을 사용한다.
- [ ] soft delete 후 다음 검색부터 제외한다.
- [ ] Chroma와 BM25에서 해당 ID가 제거됐는지 reconcile한다.
- [ ] 원본은 보존한다.
- [ ] 재색인은 staging에서 실행하고 성공 후 active pointer를 전환한다.
- [ ] 재색인 실패 시 기존 검색이 계속된다.
- [ ] 등록·삭제·재색인 후 관련 캐시를 무효화한다.
- [ ] 관리자 작업을 감사 로그에 남긴다.

### 7단계 완료 기준

- [ ] 동일 파일 연속 클릭이 작업 한 건만 만든다.
- [ ] 실행 중 삭제·재색인 충돌이 차단된다.
- [ ] 삭제 후 검색 제외와 원본 보존이 동시에 확인된다.
- [ ] 실패 작업의 해결 방법이 비밀·내부 경로 없이 표시된다.
- [ ] 개인정보 승인 전 문서가 ACTIVE가 되지 않는다.

## 8단계: 웹 공지사항 수집

### 소스 어댑터

- [ ] 학교·학과 허용 domain과 path를 설정한다.
- [ ] 목록 행, 제목, 상세 URL, 게시일 selector를 분리한다.
- [ ] 상세 제목, 본문, 게시일, 첨부 selector를 분리한다.
- [ ] 안정적인 source item ID와 canonical URL을 추출한다.
- [ ] selector profile version을 저장한다.

### CrawlPolicy

- [ ] HTTP(S)만 허용한다.
- [ ] URL credentials, localhost, private, loopback, link-local IP를 차단한다.
- [ ] 각 redirect의 domain과 IP를 다시 확인한다.
- [ ] TLS 검증을 유지한다.
- [ ] robots.txt를 user agent 기준으로 확인하고 cache한다.
- [ ] robots 401/403·도달 실패를 보수적으로 차단한다.
- [ ] 로그인·CAPTCHA·SSO·쿠키 인증·폼 제출을 시도하지 않는다.
- [ ] 동시성, 요청 간격, jitter, max pages, depth, retry를 설정화한다.
- [ ] `Retry-After`와 반복 429/403 중단을 구현한다.
- [ ] response/attachment 크기와 redirect 횟수를 제한한다.

### HTML·버전

- [ ] 응답 HTML과 헤더를 불변 snapshot으로 저장한다.
- [ ] script/style/nav/header/footer/aside/form/hidden 요소를 제거한다.
- [ ] 제목, 문단, 목록, 표, 링크 텍스트, 첨부 이름을 보존한다.
- [ ] 게시일과 collected_at을 분리한다.
- [ ] 본문 최소 길이, 제목·게시일 존재를 검증한다.
- [ ] selector 실패 시 빈 READY 문서를 만들지 않는다.
- [ ] 같은 URL의 content hash 변경을 새 version으로 저장한다.
- [ ] 304는 reindex하지 않고 last checked만 갱신한다.
- [ ] 원문 일시 누락을 자동 delete하지 않는다.
- [ ] 첨부 PDF를 공통 PDF pipeline으로 전달한다.
- [ ] 수동 업로드와 첨부 PDF hash가 같으면 embedding을 중복 생성하지 않는다.

### 8단계 완료 기준

- [ ] 목록 미리보기에서 수집/제외 URL과 이유가 보인다.
- [ ] robots 허용·거부·확인 실패 테스트가 통과한다.
- [ ] 로그인 redirect, 사설 IP, scheme 위조, redirect 우회가 차단된다.
- [ ] 429와 `Retry-After` 테스트가 통과한다.
- [ ] source URL과 published date가 모든 활성 웹 chunk에 있다.
- [ ] HTML 원문이 UI에서 실행되지 않는다.

## 9단계: 평가 데이터셋과 평가 화면

### 데이터셋 설계

- [ ] 최소 120문항을 작성한다: 답변 가능 80, 답변 불가 40.
- [ ] 발표 전 권장 300문항으로 확장 계획을 세운다.
- [ ] direct, conditional, exception, table, multi-evidence, temporal, version, out-of-scope, adversarial을 포함한다.
- [ ] question ID, text, paraphrase group, split, answerability, expected action을 저장한다.
- [ ] department, category, year, semester, as-of date를 저장한다.
- [ ] gold facts를 원자 사실 JSON으로 저장한다.
- [ ] gold evidence를 document/version/page or URL/span/hash로 저장한다.
- [ ] direct/supporting relevance grade와 대체 evidence set을 저장한다.
- [ ] hard negative evidence와 rejection reason을 저장한다.

### 라벨 품질

- [ ] 실제 원문 span을 찾은 경우에만 answerable로 판정한다.
- [ ] 적용 학과·연도·학기·예외를 gold fact에 포함한다.
- [ ] 표 evidence에 행·열 header를 함께 포함한다.
- [ ] 목차, 다른 연도, 다른 학과, 유사 기간을 hard negative로 표시한다.
- [ ] 두 명 독립 라벨과 조정 절차를 정한다.
- [ ] answerability·document·page Cohen's kappa 0.80 이상을 목표로 한다.

### 분할

- [ ] train/dev/test를 60/20/20으로 나눈다.
- [ ] 같은 paraphrase group과 같은 사실 질문을 같은 split에 둔다.
- [ ] 같은 문서 버전군과 표 인접 행이 split을 넘지 않게 한다.
- [ ] 최신 학기·버전을 temporal holdout으로 둔다.
- [ ] threshold와 parameter는 dev에서만 선택한다.
- [ ] test 결과를 본 뒤 threshold를 다시 조정하지 않는다.

### 자동 지표

- [ ] Hit@1/3/5/10
- [ ] Recall@5/10
- [ ] MRR@10
- [ ] nDCG@10
- [ ] 문서 Top-1 정확도
- [ ] 출처 문서 Precision/Recall/F1
- [ ] 출처 물리 페이지 exact Precision/Recall/F1
- [ ] 답변 Fact Precision/Recall/F1
- [ ] 숫자·날짜·학점 exact match
- [ ] 출처 일치율과 인용 완전성
- [ ] 원문 quote substring 정확도
- [ ] 잘못된 질문 거절률
- [ ] 거절 정확도
- [ ] 답변 가능 질문 응답률
- [ ] 미근거 답변률
- [ ] ECE와 Brier score
- [ ] 검색/LLM p50·p95 latency와 peak memory

### 임계값 보정

- [ ] top-1 score, margin, channel agreement, evidence count를 feature로 저장한다.
- [ ] filter match, version validity, citation coverage를 feature로 저장한다.
- [ ] logistic과 isotonic을 dev에서 비교한다.
- [ ] `미근거 답변률 ≤ 5%`, `출처 일치율 ≥ 95%`, `페이지 F1 ≥ 90%` 제약을 우선한다.
- [ ] 제약 안에서 답변 가능 질문 응답률을 최대화한다.
- [ ] calibrator와 threshold에 version을 부여한다.

### 수동 평가

- [ ] test 전체 또는 최소 60문항을 블라인드 평가한다.
- [ ] 핵심 정확성, 조건·예외, 근거 한정, 문서·페이지, 주장-인용, 거절, 가독성을 평가한다.
- [ ] 핵심 항목은 pass/fail, 표현 품질은 1-5점으로 기록한다.
- [ ] 최소 20%를 두 평가자가 중복 평가한다.
- [ ] LLM judge/NLI는 보조 지표로만 사용한다.

### 실험·보고

- [ ] BM25 단독
- [ ] Dense 단독
- [ ] BM25 + Dense RRF
- [ ] Hybrid + Reranker
- [ ] Hybrid + Reranker + Abstention
- [ ] 위 구성 + Citation Verification
- [ ] 고정 길이 청크 vs 페이지·표 인식 청크
- [ ] 임베딩 모델 2종
- [ ] metadata/version filter 유무
- [ ] 95% bootstrap CI와 query-level paired 비교
- [ ] 실행마다 corpus/model/index/prompt/parameter revision을 저장한다.

### 9단계 목표 게이트

- [ ] Hit@5 0.85 이상
- [ ] MRR@10 0.75 이상
- [ ] 출처 문서 F1 0.88 이상
- [ ] 출처 물리 페이지 F1 0.85 이상
- [ ] 답변 Fact-F1 0.85 이상
- [ ] 출처 일치율 0.92 이상
- [ ] 원문 인용 substring 정확도 1.00
- [ ] 잘못된 질문 거절률 0.90 이상
- [ ] 답변 가능 질문 응답률 0.85 이상
- [ ] 미근거 답변률 0.10 이하

## 10단계: 테스트, 리팩터링, 문서화

### 단위 테스트

- [ ] 1-based page와 printed label 분리
- [ ] 제어문자·Unicode·숫자·날짜·단위 정규화
- [ ] chunk page boundary와 표 header 반복
- [ ] exact/content/near/partial duplicate
- [ ] RRF, 동점, missing rank, duplicate collapse
- [ ] QueryPlan filter와 temporal resolver
- [ ] Evidence Gate 각 reason code와 threshold boundary
- [ ] claim-evidence, quote, hash, 숫자·극성 검증
- [ ] 모든 평가 지표의 hand-calculated fixture

### 통합·계약 테스트

- [ ] PDF→SQLite→Chunk→Chroma/BM25→Search
- [ ] 웹 HTTP mock→snapshot→clean→version→index
- [ ] update/delete/reindex→reconcile
- [ ] API key 없음→retrieval-only 전체 경로
- [ ] LLM mock→schema→citation verify→AnswerBundle
- [ ] 모든 loader의 공통 canonical schema
- [ ] VectorStore fake와 Chroma adapter contract
- [ ] LLM OpenAI-compatible와 Null client contract
- [ ] 환경변수 누락별 graceful degradation

### E2E

- [ ] 텍스트 PDF 업로드와 완료 상태
- [ ] 이미지 PDF OCR 필요·실패 상태
- [ ] 질문→답변→출처→원문 펼치기
- [ ] 검색 전용 결과
- [ ] 지정 거절문
- [ ] 웹 공지 원문 링크
- [ ] 삭제·재색인·실패 복구
- [ ] 새로고침 후 job 상태 복원
- [ ] 평가 실행과 질문별 drill-down

### 보안

- [ ] `../`와 절대 경로 파일명
- [ ] MIME·extension 위조
- [ ] 암호화·손상·과대 PDF
- [ ] localhost/private IP/redirect SSRF
- [ ] robots·rate·max page·login 차단
- [ ] HTML script와 dangerous URL scheme
- [ ] 사용자·문서 prompt injection
- [ ] API key·source path·traceback 로그 노출
- [ ] PII 경고·quarantine·외부 LLM 전송 차단
- [ ] 원본 overwrite와 자동 hard delete 부재

### 성능·신뢰성

- [ ] 기준 하드웨어와 모델 cache 상태를 기록한다.
- [ ] 100/1,000/10,000 청크 인덱싱 시간·크기·메모리를 측정한다.
- [ ] cold/warm retrieval p50/p95를 측정한다.
- [ ] LLM 포함 p50/p95를 별도 측정한다.
- [ ] 동시 사용자 1/5/10을 측정한다.
- [ ] 중간 실패·재시도·부분 색인 정리를 시험한다.
- [ ] 초기 목표 검색-only p95 1.5초, LLM 포함 p95 8초를 실제 장비 기준으로 검토한다.

### 회귀와 문서

- [ ] 30-50개 golden query를 고정한다.
- [ ] Hit@5 3%p, 페이지 F1 2%p, 거절률 3%p 이상 하락 시 CI를 실패시킨다.
- [ ] dependency와 model revision을 고정한다.
- [ ] README에 설치, Tesseract 한국어팩, 모델 cache, `.env`, 실행, 평가를 설명한다.
- [ ] 백업·복구·reconcile·문서 버전 운영 절차를 기록한다.
- [ ] AGENTS.md에 계층, 원본 불변, secret, 테스트 규칙을 기록한다.
- [ ] 발표 데모를 새 환경에서 README만으로 재현한다.

## 샘플 질문 회귀 목록

### 답변 가능

- [ ] 2024학년도 2학기 장학생 선정 필수요건은 무엇인가?
- [ ] 사회봉사는 최소 몇 시간이어야 하는가?
- [ ] 4학년에게 봉사시간 요건이 적용되는가?
- [ ] 직전 학기 최소 이수학점은 몇 학점인가?
- [ ] 장학금 성적 점수 계산식은 무엇인가?
- [ ] 2학년과 3·4학년 전공과목 수강 기준 차이는 무엇인가?
- [ ] 예방교육 인정 기간과 배점은 무엇인가?
- [ ] SDP 입력 인정 기간과 배점은 무엇인가?
- [ ] 장학금 동점자 우선순위는 무엇인가?
- [ ] 2026 교과과정의 소프트웨어융합학과 학년별 과목은 무엇인가?
- [ ] 특정 과목의 학수번호·학점·시수는 무엇인가?

### 반드시 거절 또는 확인 필요

- [ ] 이번 학기 장학금 신청 기간은 언제인가?
- [ ] 2024학년도 2학기 장학금 신청 마감일은 언제인가?
- [ ] 휴학 신청 기간은 언제인가?
- [ ] 재수강하면 기존 성적과 새 성적 중 무엇이 반영되는가?
- [ ] 내 성적으로 장학금을 받을 수 있는가?
- [ ] 등록금은 얼마인가?
- [ ] 교수 개인 연락처를 알려 달라.
- [ ] 2027학년도 졸업요건은 무엇인가?
- [ ] 입학연도 없이 전공학점만 묻는 질문에서 적용 조건을 임의 추정하지 않는다.

## 최종 MVP 릴리스 게이트

- [ ] 세 제공 PDF 유형이 각각 direct text, OCR, mixed/table 경로로 안전하게 처리된다.
- [ ] 모든 활성 PDF 청크가 유효한 1-based page를 가진다.
- [ ] 모든 활성 웹 청크가 canonical URL과 published date를 가진다.
- [ ] 모든 답변 claim이 검증된 evidence ID를 가진다.
- [ ] 원문 quote substring 정확도가 100%다.
- [ ] 근거 부족 지정 문구가 정확히 일치한다.
- [ ] API 키 없는 전체 retrieval-only E2E가 통과한다.
- [ ] soft delete와 실패 없는 blue/green reindex가 통과한다.
- [ ] robots, SSRF, login, rate limit 안전 테스트가 통과한다.
- [ ] 개인정보 경고와 quarantine이 통과한다.
- [ ] MVP 평가 목표를 충족하거나 미달 지표·원인·대응을 발표 자료에 투명하게 기록한다.
- [ ] 원본, API 키, 개인정보, 모델 cache, 로컬 DB가 Git에 포함되지 않는다.
- [ ] README 재현 데모와 졸업작품 실험 표가 완성된다.

## 다음 Codex 구현 요청문

다음 작업에서는 아래처럼 요청하고, 한 번에 1단계만 진행한다.

> `docs/PROJECT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_CHECKLIST.md`를 기준으로 1단계만 구현하세요. 먼저 현재 저장소와 첨부 자료를 읽기 전용으로 확인하고, 구조·설정·도메인 포트·SQLite schema·retrieval-only 부팅을 구현한 뒤 관련 pytest를 실행하세요. 아직 PDF 추출이나 UI 기능은 구현하지 마세요. 기존 사용자 파일을 수정하지 말고 API 키를 코드나 로그에 넣지 마세요. 완료한 체크리스트 항목과 테스트 결과, 다음 단계의 남은 조건을 보고하세요.`
