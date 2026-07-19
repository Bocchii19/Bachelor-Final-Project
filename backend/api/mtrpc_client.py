"""
MTRPC Client cho Camera PTZ
Hỗ trợ điều khiển camera qua giao thức MTRPC với Digest Authentication
"""

import requests
import json
import hashlib
import uuid


class MTRPCClient:
    def __init__(self, host, port=80):
        """
        Khởi tạo MTRPC Client
        
        Args:
            host: Địa chỉ IP camera
            port: Cổng HTTP (mặc định 80)
        """
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/mtrpc"
        self.session_id = "0"
        self.message_id = 0
        
    def _get_message_id(self):
        """Lấy message ID tiếp theo"""
        self.message_id += 1
        return self.message_id
    
    def _send_request(self, method, params=None):
        """
        Gửi yêu cầu MTRPC
        
        Args:
            method: Tên phương thức RPC
            params: Tham số
            
        Returns:
            Dữ liệu phản hồi hoặc None nếu lỗi
        """
        if params is None:
            params = {}
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._get_message_id(),
            "session": self.session_id
        }
        
        try:
            response = requests.post(
                self.base_url,
                json=payload,
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                if "result" in result:
                    return result["result"]
                elif "error" in result:
                    print(f"RPC Error: {result['error']}")
                    return None
            else:
                print(f"HTTP Error: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Lỗi kết nối: {e}")
            return None
    
    def _calculate_response(self, username, password, nonce, realm, qop):
        """
        Tính toán digest response theo tài liệu MTRPC
        
        Formula:
        HA1 = MD5(username:realm:password)
        HA2 = MD5(method:uri)
        response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
        """
        # HA1 = MD5(username:realm:password)
        ha1_str = f"{username}:{realm}:{password}"
        ha1 = hashlib.md5(ha1_str.encode()).hexdigest()
        
        # HA2 = MD5(method:uri)
        method = "POST"
        uri = "/mtrpc"
        ha2_str = f"{method}:{uri}"
        ha2 = hashlib.md5(ha2_str.encode()).hexdigest()
        
        # response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
        nc = "00000001"
        cnonce = str(uuid.uuid4())
        response_str = f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}"
        response = hashlib.md5(response_str.encode()).hexdigest()
        
        return response, cnonce, nc
    
    def login(self, username, password):
        """
        Đăng nhập vào camera theo tài liệu MTRPC
        
        Args:
            username: Tên đăng nhập
            password: Mật khẩu
            
        Returns:
            True nếu đăng nhập thành công
        """
        # Bước 1: Login Challenge
        print("Bước 1: Gửi LoginChallenge...")
        challenge_result = self._send_request("Auth.LoginChallenge", {
            "data": {
                "encrypt_type": "kEncryptDigest",
                "login_type": "kLoginWeb",
                "username": username
            }
        })
        
        if not challenge_result:
            print("✗ LoginChallenge thất bại")
            return False
        
        # Lấy session_id từ LoginChallenge
        challenge_session = challenge_result.get("session_id")
        if not challenge_session:
            print("✗ Không nhận được session_id từ LoginChallenge")
            return False
        
        # Lấy digest info
        digest_info = challenge_result.get("data", {}).get("digest", {})
        nonce = digest_info.get("nonce")
        realm = digest_info.get("realm")
        qop = digest_info.get("qop")
        
        if not all([nonce, realm, qop]):
            print(f"✗ Thiếu thông tin digest: nonce={nonce}, realm={realm}, qop={qop}")
            return False
        
        print(f"✓ LoginChallenge thành công - Session: {challenge_session}")
        
        # Bước 2: Tính toán response
        response, cnonce, nc = self._calculate_response(username, password, nonce, realm, qop)
        
        # Bước 3: Login với digest
        print("Bước 2: Gửi Login với Digest...")
        login_result = self._send_request("Auth.Login", {
            "data": {
                "digest": {
                    "cnonce": cnonce,
                    "nc": nc,
                    "nonce": nonce,
                    "qop": qop,
                    "realm": realm,
                    "response": response,
                    "uri": "/mtrpc"
                },
                "encrypt_type": "kEncryptDigest",
                "login_type": "kLoginWeb",
                "username": username
            },
            "session_id": challenge_session
        })
        
        if not login_result:
            print("✗ Login thất bại")
            return False
        
        # Lấy session_id mới từ Login
        login_data = login_result.get("data", {})
        new_session_id = login_data.get("session_id")
        
        if not new_session_id:
            print("✗ Không nhận được session_id từ Login")
            return False
        
        self.session_id = new_session_id
        print(f"✓ Đăng nhập thành công! Session ID: {self.session_id}")
        return True
    
    def connect(self, username="admin", password=""):
        """
        Kết nối tới camera
        
        Args:
            username: Tên đăng nhập (mặc định: admin)
            password: Mật khẩu (mặc định: rỗng)
            
        Returns:
            True nếu kết nối thành công
        """
        return self.login(username, password)
    
    def ptz_control(self, cmd, operate="kOperateStart", step=5, position_3d=None):
        """
        Điều khiển PTZ
        
        Args:
            cmd: Lệnh (kCmdUp, kCmdDown, kCmdLeft, kCmdRight, kCmdZoomTele, kCmdZoomWide, etc.)
            operate: Thao tác (kOperateStart, kOperateStop)
            step: Tốc độ (1-8)
            position_3d: Dict coordinates {"x": 0, "y": 0, "width": 0, "height": 0} for 3D positioning
            
        Returns:
            True nếu thành công
        """
        # Default empty 3D position if not provided
        if position_3d is None:
            position_3d = {"x": 0, "y": 0, "width": 0, "height": 0}
            
        data = {
            "cmd": cmd,
            "operate": operate,
            "channel": 0,
            "step": step,
            "preset": 0,
            "zoom": 1 if "Zoom" in cmd else 0,
            "patrol": 0,
            "position_3d": position_3d,
            "auto_scan": 0,
            "mode_path": 0,
            "preset_name": ""
        }
        
        result = self._send_request("Control.DoPtz", {
            "data": data,
            "session_id": self.session_id
        })
        
        return result is not None
    
    def logout(self):
        """Đăng xuất khỏi camera"""
        if self.session_id and self.session_id != "0":
            try:
                self._send_request("Auth.Logout", {
                    "session_id": self.session_id
                })
                print("✓ Đã đăng xuất")
            except:
                pass
            self.session_id = "0"


# ============================================================================
# RELAY CLIENT - Kết nối camera qua Relay Server (cross-network)
# ============================================================================

import threading
import time

try:
    import websocket as ws_client  # websocket-client package
    WS_CLIENT_AVAILABLE = True
except ImportError:
    WS_CLIENT_AVAILABLE = False


class RelayMTRPCClient:
    """
    MTRPC Client qua Relay Server (WebSocket)
    Cùng interface với MTRPCClient nhưng gửi lệnh qua WebSocket tới Relay
    """
    
    def __init__(self, relay_host, relay_port=8765, relay_token=""):
        """
        Khởi tạo Relay MTRPC Client
        
        Args:
            relay_host: Địa chỉ IP/domain của Relay Server
            relay_port: Cổng WebSocket của Relay Server (mặc định 8765)
            relay_token: Token xác thực
        """
        if not WS_CLIENT_AVAILABLE:
            raise ImportError("Cần cài đặt websocket-client: pip install websocket-client")
        
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.relay_token = relay_token
        self.ws_url = f"ws://{relay_host}:{relay_port}"
        self.ws = None
        self.connected = False
        self.session_id = "0"
        self._lock = threading.Lock()
        
        # Stream callback
        self.stream_callback = None
        self.streaming = False
        self._stream_thread = None
    
    def _send_and_receive(self, data):
        """Gửi JSON và nhận phản hồi qua WebSocket"""
        with self._lock:
            try:
                if not self.ws:
                    return None
                
                self.ws.send(json.dumps(data))
                response = self.ws.recv()
                return json.loads(response)
                
            except Exception as e:
                print(f"Relay WebSocket error: {e}")
                self.connected = False
                return None
    
    def _connect_ws(self):
        """Kết nối WebSocket tới Relay Server"""
        try:
            self.ws = ws_client.WebSocket()
            self.ws.connect(self.ws_url, timeout=10)
            
            # Xác thực
            if self.relay_token:
                result = self._send_and_receive({
                    "action": "auth",
                    "token": self.relay_token
                })
                if not result or result.get("status") != "ok":
                    print(f"✗ Xác thực Relay thất bại: {result}")
                    return False
            
            self.connected = True
            print(f"✓ Đã kết nối Relay Server: {self.ws_url}")
            return True
            
        except Exception as e:
            print(f"✗ Không thể kết nối Relay Server: {e}")
            return False
    
    def login(self, username, password):
        """
        Đăng nhập camera qua Relay
        
        Args:
            username: Tên đăng nhập camera
            password: Mật khẩu camera
            
        Returns:
            True nếu đăng nhập thành công
        """
        # Kết nối WebSocket trước
        if not self.connected:
            if not self._connect_ws():
                return False
        
        # Gửi lệnh login qua relay
        result = self._send_and_receive({
            "action": "login",
            "username": username,
            "password": password
        })
        
        if result and result.get("status") == "ok":
            self.session_id = "relay"
            print("✓ Đăng nhập camera qua Relay thành công")
            return True
        else:
            msg = result.get("message", "Unknown error") if result else "No response"
            print(f"✗ Đăng nhập qua Relay thất bại: {msg}")
            return False
    
    def connect(self, username="admin", password=""):
        """Kết nối tới camera qua Relay"""
        return self.login(username, password)
    
    def ptz_control(self, cmd, operate="kOperateStart", step=5, position_3d=None):
        """
        Điều khiển PTZ qua Relay
        
        Args:
            cmd: Lệnh PTZ (kCmdUp, kCmdDown, kCmdLeft, kCmdRight, etc.)
            operate: Thao tác (kOperateStart, kOperateStop)
            step: Tốc độ (1-8)
            position_3d: Dict coordinates for 3D positioning
            
        Returns:
            True nếu thành công
        """
        data = {
            "action": "ptz_control",
            "cmd": cmd,
            "operate": operate,
            "step": step
        }
        if position_3d:
            data["position_3d"] = position_3d
        
        result = self._send_and_receive(data)
        return result is not None and result.get("status") == "ok"
    
    def send_mtrpc_request(self, method, params=None):
        """
        Gửi bất kỳ MTRPC request nào qua Relay
        
        Args:
            method: Tên MTRPC method
            params: Tham số
            
        Returns:
            Kết quả hoặc None
        """
        result = self._send_and_receive({
            "action": "mtrpc_request",
            "method": method,
            "params": params or {}
        })
        
        if result and result.get("status") == "ok":
            return result.get("result")
        return None
    
    def start_stream(self, callback):
        """
        Bắt đầu nhận video stream từ Relay
        
        Args:
            callback: Hàm callback(jpeg_bytes) được gọi mỗi khi nhận được frame
        """
        self.stream_callback = callback
        self.streaming = True
        
        def stream_loop():
            try:
                # Dùng WebSocket riêng cho stream
                stream_ws = ws_client.WebSocket()
                stream_ws.connect(self.ws_url, timeout=10)
                
                # Auth
                if self.relay_token:
                    stream_ws.send(json.dumps({
                        "action": "auth",
                        "token": self.relay_token
                    }))
                    stream_ws.recv()  # Auth response
                
                # Subscribe stream
                stream_ws.send(json.dumps({
                    "action": "subscribe_stream"
                }))
                
                # First response is JSON confirmation
                first_msg = stream_ws.recv()
                
                # Subsequent messages are binary JPEG frames
                while self.streaming:
                    try:
                        data = stream_ws.recv()
                        if isinstance(data, bytes) and self.stream_callback:
                            self.stream_callback(data)
                    except Exception as e:
                        if self.streaming:
                            print(f"Stream error: {e}")
                        break
                
                stream_ws.close()
                
            except Exception as e:
                print(f"Stream connection error: {e}")
        
        self._stream_thread = threading.Thread(target=stream_loop, daemon=True)
        self._stream_thread.start()
    
    def stop_stream(self):
        """Dừng nhận video stream"""
        self.streaming = False
        self.stream_callback = None
    
    def logout(self):
        """Ngắt kết nối Relay"""
        try:
            if self.connected and self.ws:
                self._send_and_receive({"action": "logout"})
                self.ws.close()
                print("✓ Đã ngắt kết nối Relay")
        except:
            pass
        finally:
            self.ws = None
            self.connected = False
            self.session_id = "0"
    
    def ping(self):
        """Kiểm tra kết nối Relay"""
        result = self._send_and_receive({"action": "ping"})
        return result is not None and result.get("status") == "ok"


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_client(mode="direct", **kwargs):
    """
    Tạo MTRPC client phù hợp theo mode kết nối
    
    Args:
        mode: "direct" hoặc "relay"
        
    Kwargs cho direct mode:
        host: IP camera
        port: Port MTRPC (default 80)
        
    Kwargs cho relay mode:
        relay_host: IP/domain Relay Server
        relay_port: Port WebSocket (default 8765)
        relay_token: Token xác thực
        
    Returns:
        MTRPCClient hoặc RelayMTRPCClient
    """
    if mode == "relay":
        return RelayMTRPCClient(
            relay_host=kwargs.get("relay_host", "localhost"),
            relay_port=kwargs.get("relay_port", 8765),
            relay_token=kwargs.get("relay_token", "")
        )
    else:
        return MTRPCClient(
            host=kwargs.get("host", "192.168.1.100"),
            port=kwargs.get("port", 80)
        )
