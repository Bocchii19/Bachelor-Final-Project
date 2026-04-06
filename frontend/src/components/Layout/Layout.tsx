/**
 * Layout — App shell with sidebar navigation.
 */

import React, { useState, useEffect } from "react";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  Layout as AntLayout,
  Menu,
  Typography,
  Avatar,
  Dropdown,
  Button,
  Tag,
  theme,
} from "antd";
import {
  DashboardOutlined,
  TableOutlined,
  QuestionCircleOutlined,
  CalendarOutlined,
  TeamOutlined,
  VideoCameraOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  UserOutlined,
  ScanOutlined,
} from "@ant-design/icons";
import api from "../../api/client";

const { Header, Sider, Content } = AntLayout;
const { Title } = Typography;

const menuItems = [
  { key: "/", icon: <DashboardOutlined />, label: "Dashboard" },
  { key: "/attendance", icon: <TableOutlined />, label: "Điểm danh" },
  { key: "/sessions", icon: <CalendarOutlined />, label: "Buổi học" },
  { key: "/unknown-faces", icon: <QuestionCircleOutlined />, label: "Chưa nhận diện" },
  { key: "/students", icon: <TeamOutlined />, label: "Sinh viên" },
  { key: "/ptz", icon: <VideoCameraOutlined />, label: "Camera Dashboard" },
];

const Layout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [attendanceActive, setAttendanceActive] = useState(false);
  const [attendanceCount, setAttendanceCount] = useState(0);
  const navigate = useNavigate();
  const location = useLocation();
  const { token: themeToken } = theme.useToken();

  // Poll attendance status every 3s
  useEffect(() => {
    const check = async () => {
      try {
        const res = await api.get("/ptz/attendance-results");
        setAttendanceActive(res.data.active);
        setAttendanceCount(res.data.recognized?.length || 0);
      } catch {
        setAttendanceActive(false);
      }
    };
    check();
    const interval = setInterval(check, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    navigate("/login");
  };

  const userMenu = {
    items: [
      {
        key: "logout",
        icon: <LogoutOutlined />,
        label: "Đăng xuất",
        onClick: handleLogout,
      },
    ],
  };

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        style={{
          background: "linear-gradient(180deg, #001529 0%, #002140 100%)",
          boxShadow: "2px 0 8px rgba(0,0,0,0.15)",
        }}
        width={250}
      >
        <div
          style={{
            height: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderBottom: "1px solid rgba(255,255,255,0.1)",
          }}
        >
          <Title
            level={4}
            style={{
              color: "#fff",
              margin: 0,
              fontWeight: 700,
              letterSpacing: "-0.5px",
            }}
          >
            {collapsed ? "CV" : "CV Attendance"}
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{
            borderRight: 0,
            marginTop: 8,
          }}
        />
      </Sider>

      <AntLayout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
            zIndex: 1,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Button
              type="text"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 16 }}
            />
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {/* Attendance Status Indicator */}
            <Tag
              icon={<ScanOutlined />}
              color={attendanceActive ? "processing" : "default"}
              style={{ cursor: "pointer", fontSize: 13 }}
              onClick={() => navigate("/ptz")}
            >
              {attendanceActive
                ? `Đang điểm danh (${attendanceCount} SV)`
                : "Chưa điểm danh"}
            </Tag>

            <Dropdown menu={userMenu} placement="bottomRight">
              <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8 }}>
                <Avatar icon={<UserOutlined />} style={{ backgroundColor: themeToken.colorPrimary }} />
                <span>Admin</span>
              </div>
            </Dropdown>
          </div>
        </Header>

        <Content
          style={{
            margin: 24,
            padding: 24,
            background: themeToken.colorBgContainer,
            borderRadius: themeToken.borderRadiusLG,
            minHeight: 280,
          }}
        >
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
};

export default Layout;
