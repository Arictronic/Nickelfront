import { Outlet } from "react-router-dom";
import { useToast, ToastContainer } from "../ui/Toast";
import Header from "./Header";
import Sidebar from "./Sidebar";
import Footer from "./Footer";

// Глобальный экземпляр для toast (упрощенная реализация)
let globalToasts: any[] = [];
let globalSetToasts: (toasts: any[]) => void = () => {};

export function useGlobalToast() {
  return useToast();
}

export default function Layout() {
  const toast = useGlobalToast();
  
  return (
    <div className="app-shell">
      <Header />
      <div className="app-body">
        <Sidebar />
        <main className="content">
          <Outlet />
        </main>
      </div>
      <Footer />
      <ToastContainer toasts={toast.toasts} onDismiss={toast.dismiss} />
    </div>
  );
}
