export interface TaskRequest {
  patent_number: string;
  options?: Record<string, unknown>;
}

export interface TaskResponse {
  id: number;
  patent_number: string;
  status: string;
  input_data?: Record<string, unknown>;
  result?: Record<string, unknown>;
}
