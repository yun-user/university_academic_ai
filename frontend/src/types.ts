export interface Attempt {
  code: string;
  name: string;
  credits: number;
  category: string;
  area: number;
  design_credits: number;
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
  general_approval: string;
  design_sequence: string;
  recognized_course_scope: string;
  specialized_course: string;
  basic_english_course: string;
  substitutions: Substitution[];
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
  checks: Check[];
  warnings: string[];
  pending_credits: number;
  excluded_liberal_credits: number;
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
  equivalent_code: string;
  prerequisites: string[];
  concurrent: string[];
  alternatives: string[];
}
export interface Bootstrap {
  profile: Profile;
  options: Options;
  categories: string[];
  grades: string[];
  statuses: string[];
  catalog: Candidate[];
  llm: { configured: boolean; model: string };
}
export interface SavedSummary {
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
}
export interface History {
  id: string;
  revision: number;
  created_at: string;
  rules_fingerprint: string;
  result: Analysis;
}
