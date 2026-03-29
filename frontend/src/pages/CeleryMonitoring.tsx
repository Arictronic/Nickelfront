import { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "../api/client";

type CeleryStatus = {
  status: "online" | "offline" | "unknown";
  workers: {
    total: number;
    active: number;
  };
  tasks: {
    total: number;
    active: number;
    successful: number;
    failed: number;
  };
  flower_available: boolean;
  flower_url: string;
  generated_at: string;
};

type WorkerInfo = {
  name: string;
  status: string;
  active_tasks: number;
  processed_tasks: number;
  queues: string[];
  pool: Record<string, any>;
  timestamp?: string;
};

type QueueInfo = {
  name: string;
  messages: number;
  consumers: number;
  unacked: number;
};

type TaskInfo = {
  task_id: string;
  name: string;
  state: string;
  args: string;
  kwargs: Record<string, any>;
  started?: string;
  received?: string;
  succeeded?: string;
  failed?: string;
  retries: number;
  worker: Record<string, any>;
};

type ScheduledTask = {
  name: string;
  task: string;
  schedule: string;
  description?: string;
  kwargs: Record<string, any>;
  options: Record<string, any>;
};

type PanelKey = "status" | "workers" | "queues" | "tasks" | "scheduled";
type PanelState = Record<PanelKey, boolean>;
type PanelErrors = Partial<Record<PanelKey, string>>;

const STATUS_TIMEOUT = 15000;
const WORKERS_TIMEOUT = 20000;
const LIST_TIMEOUT = 12000;
const SCHEDULE_TIMEOUT = 8000;

const initialLoading: PanelState = {
  status: true,
  workers: true,
  queues: true,
  tasks: true,
  scheduled: true,
};

export default function CeleryMonitoring() {
  const [refreshing, setRefreshing] = useState(false);

  const [status, setStatus] = useState<CeleryStatus | null>(null);
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [queues, setQueues] = useState<QueueInfo[]>([]);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);

  const [loading, setLoading] = useState<PanelState>(initialLoading);
  const [errors, setErrors] = useState<PanelErrors>({});

  const inFlightRef = useRef<PanelState>({
    status: false,
    workers: false,
    queues: false,
    tasks: false,
    scheduled: false,
  });

  const setPanelLoading = (panel: PanelKey, value: boolean) => {
    setLoading((prev) => ({ ...prev, [panel]: value }));
  };

  const setPanelError = (panel: PanelKey, message: string | null) => {
    setErrors((prev) => {
      if (!message) {
        const next = { ...prev };
        delete next[panel];
        return next;
      }
      return { ...prev, [panel]: message };
    });
  };

  const guardedFetch = async (panel: PanelKey, fetcher: () => Promise<void>) => {
    if (inFlightRef.current[panel]) return;
    inFlightRef.current[panel] = true;
    setPanelLoading(panel, true);
    try {
      await fetcher();
      setPanelError(panel, null);
    } catch (e: any) {
      setPanelError(panel, e?.message || "Ошибка загрузки");
    } finally {
      setPanelLoading(panel, false);
      inFlightRef.current[panel] = false;
    }
  };

  const fetchStatus = () =>
    guardedFetch("status", async () => {
      const res = await apiClient.get<CeleryStatus>("/monitoring/celery/status", { timeout: STATUS_TIMEOUT });
      setStatus(res.data);
    });

  const fetchWorkers = () =>
    guardedFetch("workers", async () => {
      const res = await apiClient.get<{ workers: WorkerInfo[] }>("/monitoring/celery/workers", {
        timeout: WORKERS_TIMEOUT,
      });
      setWorkers(res.data.workers || []);
    });

  const fetchQueues = () =>
    guardedFetch("queues", async () => {
      const res = await apiClient.get<{ queues: QueueInfo[] }>("/monitoring/celery/queues", {
        timeout: LIST_TIMEOUT,
      });
      setQueues(res.data.queues || []);
    });

  const fetchTasks = () =>
    guardedFetch("tasks", async () => {
      const res = await apiClient.get<{ tasks: TaskInfo[] }>("/monitoring/celery/tasks?limit=20", {
        timeout: LIST_TIMEOUT,
      });
      setTasks(res.data.tasks || []);
    });

  const fetchScheduled = () =>
    guardedFetch("scheduled", async () => {
      const res = await apiClient.get<{ scheduled_tasks: ScheduledTask[] }>(
        "/monitoring/celery/scheduled-tasks",
        { timeout: SCHEDULE_TIMEOUT }
      );
      setScheduledTasks(res.data.scheduled_tasks || []);
    });

  const refreshAll = async () => {
    setRefreshing(true);
    await Promise.all([fetchStatus(), fetchWorkers(), fetchQueues(), fetchTasks(), fetchScheduled()]);
    setRefreshing(false);
  };

  useEffect(() => {
    void refreshAll();

    const iStatus = setInterval(() => void fetchStatus(), 15000);
    const iWorkers = setInterval(() => void fetchWorkers(), 20000);
    const iQueues = setInterval(() => void fetchQueues(), 30000);
    const iTasks = setInterval(() => void fetchTasks(), 30000);
    const iScheduled = setInterval(() => void fetchScheduled(), 60000);

    return () => {
      clearInterval(iStatus);
      clearInterval(iWorkers);
      clearInterval(iQueues);
      clearInterval(iTasks);
      clearInterval(iScheduled);
    };
  }, []);

  const mergedWorkers = useMemo(() => {
    const isAvailableStatus = (s?: string) => {
      const value = (s || "").toLowerCase();
      return value === "online" || value === "busy";
    };

    if (workers.length > 0) {
      return {
        total: workers.length,
        active: workers.filter((w) => isAvailableStatus(w.status)).length,
      };
    }
    return {
      total: status?.workers.total ?? 0,
      active: status?.workers.active ?? 0,
    };
  }, [workers, status]);

  const taskStats = useMemo(() => {
    if (status?.tasks) {
      return status.tasks;
    }

    const byState = tasks.reduce(
      (acc, task) => {
        const s = (task.state || "").toLowerCase();
        if (s === "started" || s === "running") acc.active += 1;
        if (s === "success") acc.successful += 1;
        if (s === "failure") acc.failed += 1;
        return acc;
      },
      { total: tasks.length, active: 0, successful: 0, failed: 0 }
    );

    return byState;
  }, [status, tasks]);

  const clusterStatus = status?.status ?? (mergedWorkers.total > 0 ? "online" : "unknown");
  const flowerAvailable =
    status?.flower_available ?? (mergedWorkers.total > 0 || workers.length > 0 ? true : false);

  const getStateColor = (state: string) => {
    switch (state.toLowerCase()) {
      case "success":
        return "#22c55e";
      case "failure":
        return "#ef4444";
      case "started":
      case "running":
        return "#4a6cf7";
      case "pending":
        return "#f59e0b";
      default:
        return "#6b7280";
    }
  };

  const getStatusColor = (current: string) => {
    switch (current.toLowerCase()) {
      case "online":
        return "#22c55e";
      case "offline":
        return "#ef4444";
      default:
        return "#f59e0b";
    }
  };

  const anyLoading = Object.values(loading).some(Boolean);

  return (
    <div className="page">
      <div className="page-head">
        <h2>Мониторинг Celery</h2>
        <div className="actions">
          <a
            href={status?.flower_url || "http://localhost:5555"}
            target="_blank"
            rel="noopener noreferrer"
            className="btn"
          >
            Flower UI
          </a>
          <button className="btn" onClick={() => void refreshAll()} disabled={refreshing}>
            {refreshing ? "Обновление..." : "Обновить"}
          </button>
        </div>
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        <article className="panel kpi-card">
          <h3>Статус кластера</h3>
          <p className={`kpi-status ${clusterStatus === "online" ? "ok" : "idle"}`} style={{ fontSize: 18 }}>
            <span
              style={{
                display: "inline-block",
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: getStatusColor(clusterStatus),
                marginRight: 8,
              }}
            />
            {loading.status && !status ? "Загрузка..." : clusterStatus.toUpperCase()}
          </p>
        </article>

        <article className="panel kpi-card">
          <h3>Воркеры</h3>
          <p className="kpi">
            {loading.workers && workers.length === 0 && !status ? "..." : `${mergedWorkers.active} / ${mergedWorkers.total}`}
          </p>
          <p className="muted" style={{ fontSize: 12 }}>
            активные / всего
          </p>
        </article>

        <article className="panel kpi-card">
          <h3>Активные задачи</h3>
          <p className="kpi">{loading.tasks && !status ? "..." : taskStats.active || 0}</p>
        </article>

        <article className="panel kpi-card">
          <h3>Успешно</h3>
          <p className="kpi" style={{ color: "#22c55e" }}>
            {loading.tasks && !status ? "..." : taskStats.successful || 0}
          </p>
        </article>

        <article className="panel kpi-card">
          <h3>Ошибки</h3>
          <p className="kpi" style={{ color: "#ef4444" }}>
            {loading.tasks && !status ? "..." : taskStats.failed || 0}
          </p>
        </article>

        <article className="panel kpi-card">
          <h3>Flower</h3>
          <p className={`kpi-status ${flowerAvailable ? "ok" : "idle"}`}>
            {loading.status && !status ? "Проверка..." : flowerAvailable ? "Доступен" : "Недоступен"}
          </p>
        </article>
      </div>

      <div className="panel">
        <h3>Воркеры ({workers.length})</h3>
        {loading.workers && workers.length === 0 ? (
          <p className="muted">Загрузка воркеров...</p>
        ) : workers.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Имя</th>
                <th>Статус</th>
                <th>Активные задачи</th>
                <th>Обработано</th>
                <th>Очереди</th>
                <th>Пул</th>
              </tr>
            </thead>
            <tbody>
              {workers.map((worker, idx) => (
                <tr key={idx}>
                  <td style={{ fontFamily: "monospace", fontSize: 13 }}>{worker.name}</td>
                  <td>
                    <span
                      className={`status ${
                        ["online", "busy"].includes((worker.status || "").toLowerCase()) ? "active" : ""
                      }`}
                    >
                      {worker.status || "Unknown"}
                    </span>
                  </td>
                  <td>{worker.active_tasks}</td>
                  <td>{worker.processed_tasks}</td>
                  <td>{worker.queues?.join(", ") || "celery"}</td>
                  <td>{(worker.pool as any)?.max_concurrency || (worker.pool as any)?.["max-concurrency"] || "N/A"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных о воркерах. Убедитесь, что Flower запущен.</p>
        )}
      </div>

      <div className="panel">
        <h3>Очереди ({queues.length})</h3>
        {loading.queues && queues.length === 0 ? (
          <p className="muted">Загрузка очередей...</p>
        ) : queues.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Сообщений</th>
                <th>Потребители</th>
                <th>Неподтверждено</th>
              </tr>
            </thead>
            <tbody>
              {queues.map((queue, idx) => (
                <tr key={idx}>
                  <td style={{ fontFamily: "monospace", fontSize: 13 }}>{queue.name}</td>
                  <td>{queue.messages}</td>
                  <td>{queue.consumers}</td>
                  <td>{queue.unacked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных об очередях</p>
        )}
      </div>

      {scheduledTasks.length > 0 && (
        <div className="panel">
          <h3>Периодические задачи (Celery Beat)</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Задача</th>
                <th>Описание</th>
                <th>Расписание</th>
                <th>Параметры</th>
              </tr>
            </thead>
            <tbody>
              {scheduledTasks.map((task, idx) => (
                <tr key={idx}>
                  <td style={{ fontFamily: "monospace", fontSize: 13 }}>{task.name}</td>
                  <td>{task.task}</td>
                  <td>{task.description || "-"}</td>
                  <td>
                    <code>{task.schedule}</code>
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {Object.entries(task.kwargs || {}).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 8 }}>
                        <strong>{k}:</strong> {String(v)}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <h3>Последние задачи ({tasks.length})</h3>
        {loading.tasks && tasks.length === 0 ? (
          <p className="muted">Загрузка задач...</p>
        ) : tasks.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Task ID</th>
                <th>Задача</th>
                <th>Статус</th>
                <th>Воркер</th>
                <th>Время</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task, idx) => (
                <tr key={idx}>
                  <td style={{ fontFamily: "monospace", fontSize: 11, wordBreak: "break-all" }}>{task.task_id}</td>
                  <td>{task.name}</td>
                  <td>
                    <span
                      className={`status ${task.state?.toLowerCase() === "success" ? "active" : ""}`}
                      style={{
                        background: getStateColor(task.state),
                        color: "white",
                        padding: "2px 8px",
                        borderRadius: 12,
                        fontSize: 12,
                      }}
                    >
                      {task.state}
                    </span>
                  </td>
                  <td>{task.worker?.hostname || "N/A"}</td>
                  <td style={{ fontSize: 12 }}>{task.started ? new Date(task.started).toLocaleTimeString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных о задачах</p>
        )}
      </div>

      {Object.keys(errors).length > 0 && (
        <div className="panel">
          <p className="error">Часть данных не обновилась: {Object.keys(errors).join(", ")}</p>
        </div>
      )}

      <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
        Компоненты загружаются независимо. Обновляется: status 15s, workers 20s, tasks/queues 30s.
        {anyLoading ? " Сейчас идет обновление..." : ""}
      </p>
    </div>
  );
}
