/**
 * CV Attendance System — Main Application with Routing
 */

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, theme } from "antd";
import viVN from "antd/locale/vi_VN";

import Layout from "./components/Layout/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import AttendanceSheet from "./pages/AttendanceSheet";
import Sessions from "./pages/Sessions";
import UnknownQueue from "./pages/UnknownQueue";
import Students from "./pages/Students";
import CameraView from "./pages/CameraView";

// Auth guard
const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const token = localStorage.getItem("access_token");
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

const App: React.FC = () => {
  return (
    <ConfigProvider
      locale={viVN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#4f46e5",
          borderRadius: 8,
          fontFamily:
            "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        },
        components: {
          Table: {
            headerBg: "#fafafa",
            headerColor: "#374151",
            rowHoverBg: "#f0f5ff",
          },
          Card: {
            borderRadiusLG: 12,
          },
          Menu: {
            darkItemBg: "transparent",
            darkSubMenuItemBg: "transparent",
          },
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="attendance" element={<AttendanceSheet />} />
            <Route path="sessions" element={<Sessions />} />
            <Route path="unknown-faces" element={<UnknownQueue />} />
            <Route path="students" element={<Students />} />
            <Route path="ptz" element={<CameraView />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
};

export default App;
