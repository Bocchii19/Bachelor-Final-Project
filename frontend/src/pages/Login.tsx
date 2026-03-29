/**
 * Login Page
 */

import React, { useState } from "react";
import { Form, Input, Button, Card, Typography, message, Space } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import apiClient from "../api/client";

const { Title, Text } = Typography;

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append("username", values.email);
      formData.append("password", values.password);

      const res = await apiClient.post("/auth/login", formData, {
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });

      localStorage.setItem("access_token", res.data.access_token);
      message.success("Đăng nhập thành công!");
      navigate("/");
    } catch {
      message.error("Email hoặc mật khẩu không đúng");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
      }}
    >
      <Card
        style={{
          width: 420,
          borderRadius: 16,
          boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        }}
        styles={{ body: { padding: "40px 36px" } }}
      >
        <Space
          direction="vertical"
          size="large"
          style={{ width: "100%", textAlign: "center" }}
        >
          <div>
            <Title level={2} style={{ marginBottom: 4 }}>
              🎓 CV Attendance
            </Title>
            <Text type="secondary">Hệ thống điểm danh tự động</Text>
          </div>

          <Form
            name="login"
            onFinish={onFinish}
            size="large"
            style={{ textAlign: "left" }}
          >
            <Form.Item
              name="email"
              rules={[{ required: true, message: "Vui lòng nhập email!" }]}
            >
              <Input prefix={<UserOutlined />} placeholder="Email" />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: "Vui lòng nhập mật khẩu!" }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="Mật khẩu" />
            </Form.Item>

            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                style={{
                  height: 48,
                  borderRadius: 8,
                  fontWeight: 600,
                  background: "linear-gradient(135deg, #667eea, #764ba2)",
                  border: "none",
                }}
              >
                Đăng nhập
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </div>
  );
};

export default Login;
