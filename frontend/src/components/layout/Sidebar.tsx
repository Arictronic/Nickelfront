import { NavLink } from "react-router-dom";
import { useAuthStore } from "../../store/authStore";

const RU = {
  home: "\u0413\u043b\u0430\u0432\u043d\u0430\u044f",
  papers: "\u0421\u0442\u0430\u0442\u044c\u0438",
  search: "\u041f\u043e\u0438\u0441\u043a",
  metrics: "\u041c\u0435\u0442\u0440\u0438\u043a\u0438",
  jobs: "\u0421\u0442\u0430\u0442\u0443\u0441 \u043f\u0430\u0440\u0441\u0438\u043d\u0433\u0430",
  tech: "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u043e\u0442\u0434\u0435\u043b",
  tasks: "\u0417\u0430\u0434\u0430\u0447\u0438",
  db: "\u0411\u0430\u0437\u0430 \u0434\u0430\u043d\u043d\u044b\u0445",
} as const;

export default function Sidebar() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;
  const cls = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;

  return (
    <aside className="sidebar">
      <NavLink className={cls} to="/dashboard">
        <span>{RU.home}</span>
      </NavLink>
      <NavLink className={cls} to="/papers">
        <span>{RU.papers}</span>
      </NavLink>
      <NavLink className={cls} to="/search">
        <span>{RU.search}</span>
      </NavLink>
      <NavLink className={cls} to="/metrics">
        <span>{RU.metrics}</span>
      </NavLink>
      <NavLink className={cls} to="/jobs">
        <span>{RU.jobs}</span>
      </NavLink>

      {isAdmin && (
        <>
          <div className="sidebar-section">{RU.tech}</div>
          <NavLink className={cls} to="/celery">
            <span>{RU.tasks}</span>
          </NavLink>
          <NavLink className={cls} to="/database">
            <span>{RU.db}</span>
          </NavLink>
        </>
      )}
    </aside>
  );
}

