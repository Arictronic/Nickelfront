import { NavLink } from "react-router-dom";

export default function Sidebar() {
  const cls = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;
  return (
    <aside className="sidebar">
      <div className="sidebar-title">Навигация</div>

      <div className="sidebar-section">Пользовательский отдел</div>
      <NavLink className={cls} to="/dashboard">
        <span>Главная</span>
      </NavLink>
      <NavLink className={cls} to="/papers">
        <span>Статьи</span>
      </NavLink>
      <NavLink className={cls} to="/vector-search">
        <span>Векторный поиск</span>
      </NavLink>
      <NavLink className={cls} to="/metrics">
        <span>Метрики</span>
      </NavLink>
      <NavLink className={cls} to="/search">
        <span>Поиск</span>
      </NavLink>
      <NavLink className={cls} to="/jobs">
        <span>Статус парсинга</span>
      </NavLink>

      <div className="sidebar-section">Технический отдел</div>
      <NavLink className={cls} to="/celery">
        <span>Задачи</span>
      </NavLink>
      <NavLink className={cls} to="/database">
        <span>База данных</span>
      </NavLink>
    </aside>
  );
}
