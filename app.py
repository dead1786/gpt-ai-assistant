export interface Employee {
  name: string;
  startDate: string;
  title: string;
  tenure: number;
  grade: string; // '未定' or number string
  isAdmin: boolean;
  canAssess: boolean; // 是否開放填寫問卷
  customQuestion?: string; // 管理者自訂考題
}

export interface Submission {
  employeeName: string;
  challenge: string;
  sopSuggestion: string;
  customAnswer?: string; // 回答自訂考題
  selfRating: number;
  submittedAt: string;
  aiEvaluation?: AiEvaluation;
}

export interface AiEvaluation {
  isPassed: boolean;
  pros: string[];
  cons: string[];
  followUpQuestions: string[];
  score: number;
  summary: string;
}

export interface LoginRequest {
  employeeName: string;
  otp: string;
  requestedAt: number;
}

export enum AppView {
  LOGIN = 'LOGIN',
  USER_DASHBOARD = 'USER_DASHBOARD',
  ADMIN_DASHBOARD = 'ADMIN_DASHBOARD',
}
