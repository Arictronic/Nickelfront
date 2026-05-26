import { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "../api/client";
import { reprocessAllPapers, stopCeleryQueues } from "../api/papers";

type CeleryStatus = {
  status: "online" | "offline" | "unknown" | "degraded" | string;
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
  flower_api_available?: boolean;
  expected_queues?: string[];
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
  timestamp?: string | number | null;
  stale_seconds?: number;
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
  started?: string | number | null;
  received?: string | number | null;
  succeeded?: string | number | null;
  failed?: string | number | null;
  retries: number;
  worker: Record<string, any> | string | null;
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

const EXPECTED_QUEUES = ["celery", "content", "qwen"] as const;

const PANEL_LABELS: Record<PanelKey, string> = {
  status: "статус кластера",
  workers: "воркеры",
  queues: "очереди",
  tasks: "задачи",
  scheduled: "периодические задачи",
};

const QUEUE_LABELS: Record<string, string> = {
  celery: "celery (парсинг/служебные)",
  content: "content (PDF/текст/эмбеддинги)",
  qwen: "qwen (Qwen AI)",
};

const WORKER_STATUS_LABELS: Record<string, string> = {
  online: "Онлайн",
  busy: "Занят",
  stale: "Нет свежего ответа",
  offline: "Офлайн",
  unknown: "Неизвестно",
};

const TASK_STATE_LABELS: Record<string, string> = {
  success: "Успешно",
  failure: "Ошибка",
  started: "В работе",
  running: "В работе",
  pending: "Ожидает",
  received: "Получена",
  retry: "Повтор",
  revoked: "Отменена",
  unknown: "Неизвестно",
};

function normalizeKey(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function formatQueueName(name: string | undefined | null): string {
  const key = normalizeKey(name);
  return QUEUE_LABELS[key] || String(name || "—");
}

function formatWorkerStatus(status: string | undefined | null): string {
  const key = normalizeKey(status);
  return WORKER_STATUS_LABELS[key] || String(status || "Неизвестно");
}

function formatTaskState(state: string | undefined | null): string {
  const key = normalizeKey(state);
  return TASK_STATE_LABELS[key] || String(state || "Неизвестно");
}

function getTaskWorkerName(worker: TaskInfo["worker"]): string {
  if (!worker) return "—";
  if (typeof worker === "string") return worker;
  return worker.hostname || worker.name || worker.worker || "—";
}


type TaskTimestamp = string | number | null | undefined;

function toTimestampMs(value: TaskTimestamp): number | null {
  if (value === null || value === undefined || value === "") return null;

  if (typeof value === "number") {
    return value < 10_000_000_000 ? value * 1000 : value;
  }

  const text = String(value).trim();
  const numeric = Number(text);

  if (Number.isFinite(numeric) && /^\d+(\.\d+)?$/.test(text)) {
    return numeric < 10_000_000_000 ? numeric * 1000 : numeric;
  }

  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatTaskTime(task: TaskInfo): string {
  const ms = toTimestampMs(task.started ?? task.received ?? task.succeeded ?? task.failed);
  return ms === null ? "—" : new Date(ms).toLocaleString();
}

function getPoolConcurrency(pool: WorkerInfo["pool"]): string | number {
  if (!pool || typeof pool !== "object") return "N/A";
  return (
    (pool as any).max_concurrency ||
    (pool as any)["max-concurrency"] ||
    (pool as any).maxConcurrency ||
    "N/A"
  );
}

function taskStatsFromList(tasks: TaskInfo[]) {
  return tasks.reduce(
    (acc, task) => {
      const state = normalizeKey(task.state);
      acc.total += 1;
      if (["started", "running", "active"].includes(state)) acc.active += 1;
      if (state === "success") acc.successful += 1;
      if (state === "failure") acc.failed += 1;
      return acc;
    },
    { total: 0, active: 0, successful: 0, failed: 0 }
  );
}

const initialLoading: PanelState = {
  status: true,
  workers: true,
  queues: true,
  tasks: true,
  scheduled: true,
};

export default function CeleryMonitoring() {
  const [refreshing, setRefreshing] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [stoppingQueues, setStoppingQueues] = useState(false);
  const [recoverMessage, setRecoverMessage] = useState<string | null>(null);
  const [queueStopMessage, setQueueStopMessage] = useState<string | null>(null);
  const [recoverLimit, setRecoverLimit] = useState(500);

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

  const normalizeRecoverLimit = (value: unknown) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return 100;
    return Math.max(1, Math.min(5000, Math.floor(parsed)));
  };

  const recoverPaperStatuses = async () => {
    const normalizedLimit = normalizeRecoverLimit(recoverLimit);
    setRecoverLimit(normalizedLimit);
    if (
      !window.confirm(
        `Поставить в очередь повторную обработку максимум ${normalizedLimit} статей? Это загрузит celery/qwen очереди.`
      )
    )
      return;
    setRecovering(true);
    setRecoverMessage(null);
    try {
      const res = await reprocessAllPapers({ limit: normalizedLimit });
      setRecoverMessage(`Поставлено в очередь: ${res.queued}`);
      await refreshAll();
    } catch (e: any) {
      setRecoverMessage(`Ошибка восстановления: ${e?.message || "неизвестная ошибка"}`);
    } finally {
      setRecovering(false);
    }
  };

  const stopQueues = async () => {
    if (
      !window.confirm(
        "Очистить очереди Celery? Ожидающие задачи будут удалены из broker, а активным задачам будет отправлен revoke/cancel flag. На Windows запущенные задачи могут завершиться только после cooperative cancel-проверки внутри worker."
      )
    ) {
      return;
    }

    setStoppingQueues(true);
    setQueueStopMessage(null);
    try {
      const res = await stopCeleryQueues(false);
      setQueueStopMessage(`Очереди очищены: отправлено revoke для задач ${res.revoked}, удалено сообщений из broker ${res.purged}.`);
      await refreshAll();
    } catch (e: any) {
      setQueueStopMessage(`Ошибка остановки очередей: ${e?.message || "неизвестная ошибка"}`);
    } finally {
      setStoppingQueues(false);
    }
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
    const recentStats = taskStatsFromList(tasks);
    const statusStats = status?.tasks;

    return {
      total: Math.max(statusStats?.total ?? 0, recentStats.total),
      active: Math.max(statusStats?.active ?? 0, recentStats.active),
      successful: Math.max(statusStats?.successful ?? 0, recentStats.successful),
      failed: Math.max(statusStats?.failed ?? 0, recentStats.failed),
    };
  }, [status, tasks]);

  const knownQueueNames = useMemo(() => {
    const names = new Set<string>();
    queues.forEach((queue) => {
      const key = normalizeKey(queue.name);
      if (key) names.add(key);
    });
    workers.forEach((worker) => {
      (worker.queues || []).forEach((queueName) => {
        const key = normalizeKey(queueName);
        if (key) names.add(key);
      });
    });
    return names;
  }, [queues, workers]);

  const expectedQueues = useMemo(() => {
    const fromStatus = (status?.expected_queues || [])
      .map((queueName) => String(queueName || "").trim())
      .filter(Boolean);
    return fromStatus.length ? fromStatus : [...EXPECTED_QUEUES];
  }, [status]);

  const canCheckExpectedQueues = !loading.workers && !loading.queues && (workers.length > 0 || queues.length > 0);
  const missingExpectedQueues = canCheckExpectedQueues
    ? expectedQueues.filter((queueName) => !knownQueueNames.has(normalizeKey(queueName)))
    : [];
  const hasMissingCoreQueues = missingExpectedQueues.length > 0;

  const rawClusterStatus = status?.status ?? (mergedWorkers.total > 0 ? "online" : "unknown");
  const clusterStatus = hasMissingCoreQueues && mergedWorkers.total > 0 ? "degraded" : rawClusterStatus;
  const clusterStatusLabel =
    clusterStatus === "degraded"
      ? "НЕПОЛНЫЙ"
      : clusterStatus === "online"
        ? "ONLINE"
        : clusterStatus === "offline"
          ? "OFFLINE"
          : "UNKNOWN";
  const flowerAvailable =
    status?.flower_available ?? (mergedWorkers.total > 0 || workers.length > 0 ? true : false);
  const flowerApiAvailable = status?.flower_api_available ?? false;

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
      case "degraded":
        return "#f59e0b";
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
          <button className="btn btn-danger" onClick={() => void stopQueues()} disabled={stoppingQueues}>
            {stoppingQueues ? "Очистка..." : "Очистить очереди"}
          </button>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="muted">лимит:</span>
            <input
              className="input"
              type="number"
              min={1}
              max={5000}
              value={recoverLimit}
              onChange={(e) => setRecoverLimit(normalizeRecoverLimit(e.target.value))}
              style={{ width: 96 }}
              disabled={recovering}
            />
          </label>
          <button className="btn btn-primary" onClick={() => void recoverPaperStatuses()} disabled={recovering}>
            {recovering ? "Восстановление..." : "Восстановить статусы статей"}
          </button>
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

      {recoverMessage && (
        <div className="panel">
          <p className={recoverMessage.startsWith("Ошибка") ? "error" : "muted"}>{recoverMessage}</p>
        </div>
      )}

      {queueStopMessage && (
        <div className="panel">
          <p className={queueStopMessage.startsWith("Ошибка") ? "error" : "muted"}>{queueStopMessage}</p>
        </div>
      )}

      {hasMissingCoreQueues && (
        <div className="panel" style={{ borderColor: "#f59e0b", background: "color-mix(in srgb, #f59e0b 8%, var(--surface))" }}>
          <h3 style={{ color: "#92400e" }}>Неполный набор Celery-очередей</h3>
          <p className="muted">
            Не видны обязательные очереди: {missingExpectedQueues.map(formatQueueName).join(", ")}.
            {missingExpectedQueues.map(normalizeKey).includes("celery")
              ? " Парсинг и служебные задачи не будут выполняться, пока regular worker не запущен."
              : " Проверь соответствующий worker."}
          </p>
        </div>
      )}

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
            {loading.status && !status ? "Загрузка..." : clusterStatusLabel}
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
            {loading.status && !status ? "Проверка..." : flowerAvailable ? "UI доступен" : "UI недоступен"}
          </p>
          <p className="muted" style={{ fontSize: 12 }}>
            API: {loading.status && !status ? "проверка..." : flowerApiAvailable ? "доступен" : "недоступен"}
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
                  <td style={{ fontFamily: "monospace", fontSize: 13, wordBreak: "break-all" }}>{worker.name}</td>
                  <td>
                    <span
                      className={`status ${
                        ["online", "busy"].includes((worker.status || "").toLowerCase()) ? "active" : ""
                      }`}
                      title={worker.stale_seconds ? `Последний ответ ${worker.stale_seconds} сек. назад` : undefined}
                    >
                      {formatWorkerStatus(worker.status)}
                    </span>
                  </td>
                  <td>{worker.active_tasks}</td>
                  <td>{worker.processed_tasks}</td>
                  <td>{worker.queues?.length ? worker.queues.map(formatQueueName).join(", ") : "—"}</td>
                  <td>{getPoolConcurrency(worker.pool)}</td>
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
                  <td style={{ fontFamily: "monospace", fontSize: 13 }}>{formatQueueName(queue.name)}</td>
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
                      {formatTaskState(task.state)}
                    </span>
                  </td>
                  <td>{getTaskWorkerName(task.worker)}</td>
                  <td style={{ fontSize: 12 }}>{formatTaskTime(task)}</td>
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
          <p className="error" style={{ marginBottom: 8 }}>Часть данных не обновилась:</p>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {Object.entries(errors).map(([panel, message]) => (
              <li key={panel} className="error">
                <strong>{PANEL_LABELS[panel as PanelKey] || panel}</strong>: {message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
        Компоненты загружаются независимо. Обновляется: status 15s, workers 20s, tasks/queues 30s.
        {anyLoading ? " Сейчас идет обновление..." : ""}
      </p>
    </div>
  );
}
