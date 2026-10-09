"""Reviewed design-credit allocations: enrollment cohort != course-taking year."""
import hashlib
import json
from pathlib import Path
import re

from src.retrieval.document_models import DocumentSearchResponse, DocumentSearchResult
from src.retrieval.query_intent import QuestionIntent


def design_course_answer(question, root):
    def abstain(text):
        return DocumentSearchResponse(question_intent=QuestionIntent.ACADEMIC_RULE, clarification_message=text)
    root = Path(root)
    try:
        data = json.loads((root / 'design_courses.json').read_text(encoding='utf-8'))
        original = (root / 'sources' / data['source_file']).resolve()
        if not original.is_relative_to((root / 'sources').resolve()):
            raise ValueError('invalid path')
        if hashlib.sha256(original.read_bytes()).hexdigest() != data['sha256']:
            raise ValueError('changed source')
    except (OSError, ValueError, KeyError):
        return abstain('검토된 설계교과목 원문을 확인할 수 없어 답변을 보류합니다. 관리자에게 원문 복구와 재검토를 요청해 주세요.')
    compact = re.sub(r'\s+', '', question)
    # Require course-taking language and do not treat an admission label as it.
    years = set(re.findall(r'((?:19|20)\d{2})(?:년|년도)(?!입학|학번)(?:에|부터|도|[12]학기|[12]학기에|에[12]학기|에[12]학기에)?(?:수강|이수|들었|들은)', compact))
    years.update(re.findall(r'(?:수강|이수)(?:연도|년도|년)[:：]?((?:19|20)\d{2})', compact))
    if any(int(year) < 2019 for year in years):
        return abstain('설계 인정학점은 학번이 아니라 실제 수강연도를 기준으로 적용합니다. 2019년 이전 수강 과목에는 현재 공개표를 확정 적용할 수 없습니다. 학과 설계/대체 교과목 페이지의 해당 수강연도 표를 확인해 주세요. ' + data['source_url'])
    if re.search(r'201[5678]년(?:도)?(?:기준|표)', compact):
        return abstain('요청한 연도의 설계교과목 표는 별도 확인이 필요합니다. 현재 공개표의 시행연도와 개정 이력은 확인되지 않았습니다. ' + data['source_url'])
    rows = data['rows']
    lookup = {row['name']: row['design_credits'] for row in rows}
    core = sum(lookup[name] for name in ('창의적공학설계입문', '종합설계(1)', '종합설계(2)'))
    table = '| 교과목 | 인정 설계학점 | 구분 |\n| --- | --- | --- |\n' + '\n'.join(
        f"| {row['name']} | {row['design_credits']}학점 | {row['kind']} |" for row in rows)
    text = ('소프트웨어융합학과 설계교과목 인정학점 검토 전사본.\n'
        '현재 학과 공개표 참고. 수강 당시의 인정 기준은 별도 확인 필요.\n' + table)
    digest = hashlib.sha256(text.encode()).hexdigest()
    result = DocumentSearchResult(document_id='reviewed:design-courses', chunk_id='reviewed:design-courses:' + digest[:16],
        file_name='design_courses_reviewed.txt', file_type='txt', document_type='검토된 학사규정',
        department='소프트웨어융합학과', title='설계/대체 교과목 · 현재 학과 공개표 (검토 전사본)',
        source_url=data['source_url'], source_year=None, effective_from=None,
        source_path='config/reviewed_rules/design_courses.json', text=text,
        score=1, score_kind='structured_exact', content_hash=digest, is_current=None)
    body = (f'**창의적공학설계입문 2 + 종합설계(1) 3 + 종합설계(2) 3 = 설계 {core}학점**입니다. '
        f'이 세 과목만으로 12학점이 되는 것은 아닙니다. **12학점 기준을 충족하려면 요소설계 과목에서 {12-core}학점 이상을 추가로 인정받아야 합니다.**\n\n'
        '학과 홈페이지에서 현재 공개한 **설계학점 표**는 다음과 같습니다. '
        '아래 숫자는 교과목의 전체 학점이 아니라 **공학인증 설계 인정학점**입니다.\n\n' + table + '\n\n'
        '**계산 예시:** 위 세 과목 8학점 + 디자인패턴프로그래밍 및 실습 2학점 + 알고리즘및실습 1학점 + 소프트웨어공학 1학점 = 설계 12학점입니다. '
        '이 조합만 허용된다는 뜻이 아니며, 예시는 과목별 설계학점의 합산 방법입니다.\n\n'
        '**적용 조건:** 설계학점은 **실제 수강연도**의 인정 기준과 대조해야 합니다. 현재 페이지의 시행연도와 개정 이력은 확인되지 않았습니다. '
        '2019년 이전 수강 과목은 해당 연도 표를 따로 확인해야 합니다. '
        '본인에게 필요한 총 설계학점은 입학연도·일반/심화과정 기준을 함께 확인하고, '
        '과목을 수강한 연도·학기와 후속 변경 여부도 확인하세요.\n\n'
        f"출처: [학과 설계/대체 교과목]({data['source_url']}) · 확인일 {data['reviewed_on']}. 게시·개정일은 별도 확인되지 않았습니다.")
    return DocumentSearchResponse(results=[result], question_intent=QuestionIntent.ACADEMIC_RULE, reviewed_answer=body)
