import { useEffect, useRef, useState } from "react";
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

export default function CeleryMonitoring() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  
  // Status data
  const [status, setStatus] = useState<CeleryStatus | null>(null);
  
  // Workers data
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  
  // Queues data
  const [queues, setQueues] = useState<QueueInfo[]>([]);
  
  // Tasks data
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  
  // Scheduled tasks data
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledTask[]>([]);
  const [fullRefreshEvery] = useState(3); // every 3 light polls
  const pollTickRef = useRef(0);
  const refreshingRef = useRef(false);

  useEffect(() => {
    refreshingRef.current = refreshing;
  }, [refreshing]);

  useEffect(() => {
    loadMonitoringData(true);
    // Light auto-refresh: status only, every 15s.
    const interval = setInterval(() => {
      void loadMonitoringData(false);
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  const loadMonitoringData = async (full: boolean = false) => {
    if (refreshingRef.current) return;
    
    setRefreshing(true);
    setError(null);
    
    try {
      const nextTick = pollTickRef.current + 1;
      const shouldFullRefresh = full || nextTick % fullRefreshEvery === 0;
      pollTickRef.current = nextTick;

      if (shouldFullRefresh) {
        const [statusRes, workersRes, queuesRes, tasksRes, scheduledRes] = await Promise.all([
          apiClient.get<CeleryStatus>("/monitoring/celery/status", { timeout: 3000 }).catch(() => null),
          apiClient.get<{ workers: WorkerInfo[] }>("/monitoring/celery/workers", { timeout: 4000 }).catch(() => null),
          apiClient.get<{ queues: QueueInfo[] }>("/monitoring/celery/queues", { timeout: 4000 }).catch(() => null),
          apiClient.get<{ tasks: TaskInfo[] }>("/monitoring/celery/tasks?limit=20", { timeout: 4000 }).catch(() => null),
          apiClient.get<{ scheduled_tasks: ScheduledTask[] }>("/monitoring/celery/scheduled-tasks", { timeout: 3000 }).catch(() => null),
        ]);

        if (statusRes) {
          setStatus(statusRes.data);
        }
        if (workersRes) setWorkers(workersRes.data.workers || []);
        if (queuesRes) setQueues(queuesRes.data.queues || []);
        if (tasksRes) setTasks(tasksRes.data.tasks || []);
        if (scheduledRes) setScheduledTasks(scheduledRes.data.scheduled_tasks || []);
      } else {
        const statusRes = await apiClient
          .get<CeleryStatus>("/monitoring/celery/status", { timeout: 3000 })
          .catch(() => null);
        if (statusRes) {
          setStatus(statusRes.data);
        } else {
          setStatus((prev) => prev);
        }
      }
      
      setLoading(false);
    } catch (e: any) {
      setError(e.message || "Ошибка загрузки данных");
      setLoading(false);
    } finally {
      setRefreshing(false);
    }
  };

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

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case "online":
        return "#22c55e";
      case "offline":
        return "#ef4444";
      default:
        return "#f59e0b";
    }
  };

  if (loading) {
    return (
      <div className="page">
        <div className="page-head">
          <h2>Мониторинг Celery</h2>
        </div>
        <div className="panel">
          <p>Загрузка данных мониторинга...</p>
        </div>
      </div>
    );
  }

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
            🌸 Flower UI
          </a>
          <button className="btn" onClick={() => void loadMonitoringData(true)} disabled={refreshing}>
            {refreshing ? "Обновление..." : "Обновить"}
          </button>
        </div>
      </div>

      {/* Status KPI */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        <article className="panel kpi-card">
          <h3>Статус кластера</h3>
          <p className={`kpi-status ${status?.status === "online" ? "ok" : "idle"}`} style={{ fontSize: 18 }}>
            <span style={{ 
              display: "inline-block", 
              width: 12, 
              height: 12, 
              borderRadius: "50%", 
              background: getStatusColor(status?.status || "unknown"),
              marginRight: 8,
            }} />
            {status?.status?.toUpperCase() || "UNKNOWN"}
          </p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Воркеры</h3>
          <p className="kpi">{status?.workers.active || 0} / {status?.workers.total || 0}</p>
          <p className="muted" style={{ fontSize: 12 }}>активные / всего</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Активные задачи</h3>
          <p className="kpi">{status?.tasks.active || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Успешно</h3>
          <p className="kpi" style={{ color: "#22c55e" }}>{status?.tasks.successful || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Ошибки</h3>
          <p className="kpi" style={{ color: "#ef4444" }}>{status?.tasks.failed || 0}</p>
        </article>
        
        <article className="panel kpi-card">
          <h3>Flower</h3>
          <p className={`kpi-status ${status?.flower_available ? "ok" : "idle"}`}>
            {status?.flower_available ? "Доступен" : "Недоступен"}
          </p>
        </article>
      </div>

      {/* Workers */}
      <div className="panel">
        <h3>Воркеры ({workers.length})</h3>
        {workers.length > 0 ? (
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
                    <span className={`status ${worker.status?.toLowerCase() === "online" ? "active" : ""}`}>
                      {worker.status || "Unknown"}
                    </span>
                  </td>
                  <td>{worker.active_tasks}</td>
                  <td>{worker.processed_tasks}</td>
                  <td>{worker.queues?.join(", ") || "celery"}</td>
                  <td>{worker.pool?.max_concurrency || "N/A"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных о воркерах. Убедитесь, что Flower запущен.</p>
        )}
      </div>

      {/* Queues */}
      <div className="panel">
        <h3>Очереди ({queues.length})</h3>
        {queues.length > 0 ? (
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

      {/* Scheduled Tasks */}
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
                  <td>{task.description || "—"}</td>
                  <td><code>{task.schedule}</code></td>
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

      {/* Recent Tasks */}
      <div className="panel">
        <h3>Последние задачи ({tasks.length})</h3>
        {tasks.length > 0 ? (
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
                  <td style={{ fontFamily: "monospace", fontSize: 11, wordBreak: "break-all" }}>
                    {task.task_id}
                  </td>
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
                  <td style={{ fontSize: 12 }}>
                    {task.started ? new Date(task.started).toLocaleTimeString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Нет данных о задачах</p>
        )}
      </div>

      {error && (
        <div className="panel">
          <p className="error">{error}</p>
          <p className="muted" style={{ fontSize: 13 }}>
            Примечание: Убедитесь, что Flower запущен через <code>run_flower.bat</code>
          </p>
        </div>
      )}

      <p className="muted" style={{ marginTop: 16, fontSize: 12 }}>
        Статус обновляется каждые 15 секунд, полный срез реже. Flower: {status?.flower_url || "http://localhost:5555"}
      </p>
    </div>
  );
}
