import { apiClient } from "./client";
import type { TaskRequest, TaskResponse } from "../types/api";

export async function startParsing(payload: TaskRequest) {
  const { data } = await apiClient.post<TaskResponse>("/tasks/", payload);
  return data;
}

export async function getTaskStatus(taskId: number) {
  const { data } = await apiClient.get<TaskResponse>(`/tasks/${taskId}`);
  return data;
}
