import { Outlet } from "react-router-dom";
import { ToastContainer, useToast } from "../ui/Toast";
import Header from "./Header";
import Sidebar from "./Sidebar";
import Footer from "./Footer";
import QwenTokenWatcher from "../QwenTokenWatcher";

export function useGlobalToast() {
  return useToast();
}

export default function Layout() {
  const toast = useGlobalToast();

  return (
    <div className="app-shell">
      <QwenTokenWatcher />
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
