export interface Attempt {
  code: string;
  name: string;
  credits: number;
  category: string;
  area: number;
  design_credits: number;
  design_override?: boolean;
  sw_data_credits?: number;
  equivalent_code: string;
  year: number;
  term: number;
  grade: string;
  status: string;
}
export interface Profile {
  admission_year: number;
  track: "심화" | "일반";
  required_codes: string[];
  required_list_checked: boolean;
  thesis: string;
  english: string;
  language?: LanguageRecord | null;
  general_approval: string;
  design_sequence: string;
  recognized_course_scope: string;
  specialized_course: string;
  basic_english_course: string;
  sw_data_course: string;
  science_course: string;
  substitutions: Substitution[];
}
export interface LanguageRecord {
  exam: string;
  score: string;
  expires_on: string | null;
  submitted_on: string | null;
  submission_confirmed: boolean;
}
export interface DepartmentGuidance {
  reviewed_on: string;
  scope: string;
  sources: { id: string; title: string; url: string }[];
  exams: { id: string; label: string; requirement: string; maximum?: number; levels?: string[] }[];
  notes: string[];
  tasks: { id: string; title: string; note: string }[];
}
export interface Substitution {
  required_code: string;
  replacement_code: string;
  track: "심화" | "일반";
  start_year: number;
  start_term: number;
  end_year: number | null;
  end_term: number | null;
  source: string;
  confirmed: boolean;
}
export interface TaskItem {
  id: string;
  title: string;
  due: string | null;
  done: boolean;
  note: string;
}
export interface Placement {
  code: string;
  semester: number;
}
export interface Evidence extends Check {
  scope: string;
  sources: string[];
  verification: string;
}
export interface Options {
  start_year: number;
  start_term: number;
  semesters: number;
  credit_limit: number;
  excluded_codes: string[];
  assume_in_progress_passed: boolean;
  semester_limits?: number[];
}
export interface Input {
  attempts: Attempt[];
  profile: Profile;
  options: Options;
  goal: string;
  candidates?: Candidate[] | null;
  placements?: Placement[] | null;
  checklist?: TaskItem[];
  counseling_preferences?: CounselingPreferences;
}
export interface CounselingPreferences {
  interests: string;
  credit_limit: number | null;
  final_credit_limit: number | null;
  graduation_year: number | null;
  graduation_term: number | null;
  notes: string;
}
export interface Check {
  key: string;
  current: number;
  required: number;
  missing: number;
  status: string;
  detail: string;
}
export interface Audit {
  design_allocations?: DesignAllocation[];
  checks: Check[];
  warnings: string[];
  pending_credits: number;
  excluded_liberal_credits: number;
}
export interface DesignAllocation {
  index: number;
  code: string;
  name: string;
  year: number;
  term: number;
  credits: number;
  counted_credits: number;
  mode: "auto" | "manual" | "held" | "unmatched";
  kind: string;
  reason: string;
  source: string;
}
export interface Semester {
  year: number;
  term: number;
  credits: number;
  courses: {
    code: string;
    name: string;
    credits: number;
    reason: string;
    source: string;
  }[];
}
export interface Analysis {
  candidate_reasons?: {
    code: string;
    name: string;
    reason: string;
    source: string;
  }[];
  audit: Audit;
  roadmap: {
    semesters: Semester[];
    projected: Audit;
    unresolved: string[];
    assumptions: string[];
  };
  advice: {
    summary: string;
    priorities: { code: string; reason: string }[];
    next_steps: string[];
  } | null;
  mode: string;
  model: string;
  notice: string;
  rules: { notices: string[]; sources: string[] };
  rules_fingerprint: string;
  evidence?: Evidence[];
}
export interface Candidate {
  code: string;
  name: string;
  credits: number;
  category: string;
  semesters: number[];
  source: string;
  area: number;
  design_credits: number;
  sw_data_credits?: number;
  equivalent_code: string;
  prerequisites: string[];
  concurrent: string[];
  alternatives: string[];
}
export interface Bootstrap {
  department_guidance: DepartmentGuidance;
  admission_years: number[];
  cohort_rules: {
    admission_year: number;
    track: string;
    thresholds: Record<string, number>;
    liberal_cap: number;
    cohort_range: number[];
    science_mode: string;
    msc_detail: string;
    source: string;
  }[];
  profile: Profile;
  options: Options;
  categories: string[];
  grades: string[];
  statuses: string[];
  catalog: Candidate[];
  llm: { configured: boolean; model: string };
}
export interface SavedSummary {
  admission_year: number;
  id: string;
  label: string;
  revision: number;
  track: string;
  updated_at: string;
  course_count: number;
}
export interface Saved extends Input {
  id: string;
  label: string;
  revision: number;
}
export interface ChatReply {
  mode: string;
  answer: string;
  referenced_checks: string[];
  recommended_codes: string[];
  model: string;
  evidence?: Evidence[];
}
export interface Message extends ChatReply {
  question: string;
  id?: string;
  sequence?: number;
  created_at?: string;
  revision?: number;
  status?: string;
  input_fingerprint?: string;
  rules_fingerprint?: string;
  feedback?: ChatFeedback;
  memory_used?: { history_count: number; correction_count: number };
}
export interface ChatFeedback {
  rating: "unrated" | "helpful" | "unhelpful";
  correction: string;
  source: string;
  verified: boolean;
  updated_at?: string;
}
export interface ChatContext {
  input_fingerprint: string;
  rules_fingerprint: string;
  history_count: number;
  correction_count: number;
}
export interface History {
  id: string;
  revision: number;
  created_at: string;
  rules_fingerprint: string;
  result: Analysis;
}
