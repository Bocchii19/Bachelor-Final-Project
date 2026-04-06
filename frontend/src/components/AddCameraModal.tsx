/**
 * AddCameraModal — Form modal to add or edit cameras.
 */

import React, { useEffect } from "react";
import { Modal, Form, Input, Select, InputNumber, message } from "antd";
import api from "../api/client";

interface AddCameraModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  editCamera?: {
    id: string;
    name: string;
    rtsp_url: string;
    type: string;
    onvif_host?: string | null;
    onvif_port?: number | null;
    onvif_user?: string | null;
    onvif_password?: string | null;
  } | null;
}

const AddCameraModal: React.FC<AddCameraModalProps> = ({
  open,
  onClose,
  onSuccess,
  editCamera,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = React.useState(false);
  const camType = Form.useWatch("type", form);

  useEffect(() => {
    if (open) {
      if (editCamera) {
        form.setFieldsValue({
          name: editCamera.name,
          rtsp_url: editCamera.rtsp_url,
          type: editCamera.type,
          onvif_host: editCamera.onvif_host || "",
          onvif_port: editCamera.onvif_port || 80,
          onvif_user: editCamera.onvif_user || "",
          onvif_password: editCamera.onvif_password || "",
        });
      } else {
        form.resetFields();
      }
    }
  }, [open, editCamera, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      if (editCamera) {
        await api.put(`/ptz/cameras/${editCamera.id}`, values);
        message.success("Đã cập nhật camera");
      } else {
        await api.post("/ptz/cameras", values);
        message.success("Đã thêm camera mới");
      }
      onSuccess();
      onClose();
    } catch (err: any) {
      if (err?.response?.data?.detail) {
        message.error(err.response.data.detail);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={editCamera ? "Sửa Camera" : "Thêm Camera"}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={loading}
      okText={editCamera ? "Cập nhật" : "Thêm"}
      cancelText="Hủy"
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ type: "fixed", onvif_port: 80 }}
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="name"
          label="Tên camera"
          rules={[{ required: true, message: "Nhập tên camera" }]}
        >
          <Input placeholder="Camera Lớp 408" />
        </Form.Item>

        <Form.Item
          name="rtsp_url"
          label="RTSP URL"
          rules={[{ required: true, message: "Nhập RTSP URL" }]}
        >
          <Input placeholder="rtsp://192.168.1.100:554/stream1" />
        </Form.Item>

        <Form.Item
          name="type"
          label="Loại camera"
          rules={[{ required: true }]}
        >
          <Select
            options={[
              { label: "Fixed (cố định)", value: "fixed" },
              { label: "PTZ (xoay/nghiêng/zoom)", value: "ptz" },
            ]}
          />
        </Form.Item>

        {camType === "ptz" && (
          <>
            <Form.Item name="onvif_host" label="ONVIF Host">
              <Input placeholder="192.168.1.100" />
            </Form.Item>
            <Form.Item name="onvif_port" label="ONVIF Port">
              <InputNumber min={1} max={65535} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="onvif_user" label="ONVIF User">
              <Input placeholder="admin" />
            </Form.Item>
            <Form.Item name="onvif_password" label="ONVIF Password">
              <Input.Password placeholder="password" />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
};

export default AddCameraModal;
