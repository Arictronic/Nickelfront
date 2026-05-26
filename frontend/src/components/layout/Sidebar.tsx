import { NavLink } from "react-router-dom";
import { useAuthStore } from "../../store/authStore";

function Icon({ path, viewBox = "0 0 24 24" }: { path: string; viewBox?: string }) {
  return (
    <svg className="nav-icon" viewBox={viewBox} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

const ICONS = {
  home:     "M3 9.5L12 3l9 6.5V21H15v-6H9v6H3z",
  papers:   "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
  search:   "M21 21l-4.35-4.35M17 11A6 6 0 111 11a6 6 0 0116 0z",
  metrics:  "M3 12h3l3-9 3 18 3-9h3M3 21h18",
  analysis: "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z",
  jobs:     "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  celery:   "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01",
  database: "M4 6c0 1.657 3.582 3 8 3s8-1.343 8-3M4 6c0-1.657 3.582-3 8-3s8 1.343 8 3M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6",
  settings: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
};

const RU = {
  home:     "Главная",
  papers:   "Статьи",
  search:   "Поиск",
  metrics:  "Метрики",
  analysis: "Анализ сплавов",
  jobs:     "Статус парсинга",
  tech:     "Технический отдел",
  tasks:    "Задачи Celery",
  db:       "База данных",
  settings: "Настройки",
} as const;

export default function Sidebar() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;
  const cls = ({ isActive }: { isActive: boolean }) =>
    `nav-item${isActive ? " active" : ""}`;

  return (
    <aside className="sidebar">
      <NavLink className={cls} to="/dashboard" title={RU.home}>
        <Icon path={ICONS.home} />
        <span>{RU.home}</span>
      </NavLink>

      <NavLink className={cls} to="/papers" title={RU.papers}>
        <Icon path={ICONS.papers} />
        <span>{RU.papers}</span>
      </NavLink>

      <NavLink className={cls} to="/search" title={RU.search}>
        <Icon path={ICONS.search} />
        <span>{RU.search}</span>
      </NavLink>

      <NavLink className={cls} to="/metrics" title={RU.metrics}>
        <Icon path={ICONS.metrics} />
        <span>{RU.metrics}</span>
      </NavLink>

      <NavLink className={cls} to="/analysis" title={RU.analysis}>
        <Icon path={ICONS.analysis} />
        <span>{RU.analysis}</span>
      </NavLink>

      <NavLink className={cls} to="/jobs" title={RU.jobs}>
        <Icon path={ICONS.jobs} />
        <span>{RU.jobs}</span>
      </NavLink>

      {isAdmin && (
        <>
          <div className="sidebar-section">{RU.tech}</div>

          <NavLink className={cls} to="/celery" title={RU.tasks}>
            <Icon path={ICONS.celery} />
            <span>{RU.tasks}</span>
          </NavLink>

          <NavLink className={cls} to="/database" title={RU.db}>
            <Icon path={ICONS.database} />
            <span>{RU.db}</span>
          </NavLink>

          <NavLink className={cls} to="/settings" title={RU.settings}>
            <Icon path={ICONS.settings} />
            <span>{RU.settings}</span>
          </NavLink>
        </>
      )}
    </aside>
  );
}
