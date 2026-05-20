import { NavLink } from "react-router-dom";
import { useAuthStore } from "../../store/authStore";

const IconDashboard = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
  </svg>
);
const IconPapers = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
    <line x1="9" y1="13" x2="15" y2="13" /><line x1="9" y1="17" x2="15" y2="17" />
  </svg>
);
const IconSearch = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const IconMetrics = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
  </svg>
);
const IconJobs = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14" />
  </svg>
);
const IconTasks = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);
const IconDB = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
  </svg>
);

const cls = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;

export default function Sidebar() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;

  return (
    <aside className="sidebar">
      <NavLink className={cls} to="/dashboard">
        <IconDashboard />
        <span>Главная</span>
      </NavLink>
      <NavLink className={cls} to="/papers">
        <IconPapers />
        <span>Статьи</span>
      </NavLink>
      <NavLink className={cls} to="/search">
        <IconSearch />
        <span>Поиск</span>
      </NavLink>
      <NavLink className={cls} to="/metrics">
        <IconMetrics />
        <span>Метрики</span>
      </NavLink>
      <NavLink className={cls} to="/jobs">
        <IconJobs />
        <span>Статус парсинга</span>
      </NavLink>

      {isAdmin && (
        <>
          <div
            style={{
              padding: "16px 14px 6px",
              fontSize: "10px",
              fontWeight: 700,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "var(--muted)",
            }}
          >
            Технический отдел
          </div>
          <NavLink className={cls} to="/celery">
            <IconTasks />
            <span>Задачи</span>
          </NavLink>
          <NavLink className={cls} to="/database">
            <IconDB />
            <span>База данных</span>
          </NavLink>
        </>
      )}
    </aside>
  );
}