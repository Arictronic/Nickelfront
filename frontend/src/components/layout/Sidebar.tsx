import { NavLink } from "react-router-dom";

export default function Sidebar() {
  const cls = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? " active" : ""}`;
  return (
    <aside className="sidebar">
      <div className="sidebar-title">Навигация</div>
      <NavLink className={cls} to="/dashboard">
        <span>Главная</span>
      </NavLink>
      <NavLink className={cls} to="/patents">
        <span>Патенты</span>
      </NavLink>
      <NavLink className={cls} to="/analytics">
        <span>Аналитика</span>
      </NavLink>
      <div className="sidebar-note">Режим: frontend</div>
    </aside>
  );
}
