import { NavLink } from "react-router-dom";

export default function Sidebar() {
  const cls = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;
  return (
    <aside className="sidebar">
      <div className="sidebar-title">Навигация</div>
      <NavLink className={cls} to="/dashboard">
        <span>Главная</span>
      </NavLink>
      <NavLink className={cls} to="/papers">
        <span>Статьи</span>
      </NavLink>
      <NavLink className={cls} to="/vector-search">
        <span>Векторный поиск</span>
      </NavLink>
      <NavLink className={cls} to="/jobs">
        <span>Статус парсинга</span>
      </NavLink>
      <NavLink className={cls} to="/database">
        <span>База данных</span>
      </NavLink>
      <div className="sidebar-note">Backend: papers API + эвристики</div>
    </aside>
  );
}
