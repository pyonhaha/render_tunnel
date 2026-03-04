#!/usr/bin/env python3
"""
WebSocket Tunnel Server for Render.com
"""

import socket
import threading
import base64
import hashlib
import os
import struct
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PORT", 10000))
BUFFER_SIZE = 65536


def compute_accept_key(key):
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    sha1 = hashlib.sha1((key + GUID).encode()).digest()
    return base64.b64encode(sha1).decode()


def parse_ws_frame(data):
    if len(data) < 2:
        return None, None, 0
    byte1, byte2 = data[0], data[1]
    opcode = byte1 & 0x0F
    masked = (byte2 & 0x80) != 0
    payload_len = byte2 & 0x7F
    offset = 2
    if payload_len == 126:
        if len(data) < 4:
            return None, None, 0
        payload_len = struct.unpack('>H', data[2:4])[0]
        offset = 4
    elif payload_len == 127:
        if len(data) < 10:
            return None, None, 0
        payload_len = struct.unpack('>Q', data[2:10])[0]
        offset = 10
    if masked:
        if len(data) < offset + 4 + payload_len:
            return None, None, 0
        mask = data[offset:offset+4]
        offset += 4
        payload = bytearray(data[offset:offset+payload_len])
        for i in range(len(payload)):
            payload[i] ^= mask[i % 4]
        payload = bytes(payload)
    else:
        if len(data) < offset + payload_len:
            return None, None, 0
        payload = data[offset:offset+payload_len]
    return opcode, payload, offset + payload_len


def create_ws_frame(payload, opcode=0x02):
    frame = bytearray()
    frame.append(0x80 | opcode)
    length = len(payload)
    if length <= 125:
        frame.append(length)
    elif length <= 65535:
        frame.append(126)
        frame.extend(struct.pack('>H', length))
    else:
        frame.append(127)
        frame.extend(struct.pack('>Q', length))
    frame.extend(payload)
    return bytes(frame)


def forward_ws_to_tcp(ws_socket, tcp_socket):
    buffer = b""
    try:
        while True:
            data = ws_socket.recv(BUFFER_SIZE)
            if not data:
                break
            buffer += data
            while True:
                opcode, payload, consumed = parse_ws_frame(buffer)
                if opcode is None:
                    break
                buffer = buffer[consumed:]
                if opcode == 0x08:
                    return
                elif opcode in (0x01, 0x02):
                    tcp_socket.sendall(payload)
    except:
        pass


def forward_tcp_to_ws(tcp_socket, ws_socket):
    try:
        while True:
            data = tcp_socket.recv(BUFFER_SIZE)
            if not data:
                break
            frame = create_ws_frame(data)
            ws_socket.sendall(frame)
    except:
        pass


def handle_websocket(client_socket, path, headers):
    remote_socket = None
    try:
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "tunnel":
            return
        host = parts[1]
        port = int(parts[2])
        print(f"[>] Tunnel to {host}:{port}")

        remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote_socket.settimeout(30)
        remote_socket.connect((host, port))
        print(f"[✓] Connected to {host}:{port}")

        ws_key = headers.get("sec-websocket-key", "") 
        accept_key = compute_accept_key(ws_key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n"
            "\r\n"
        )
        client_socket.send(response.encode())

        client_socket.settimeout(None)
        remote_socket.settimeout(None)

        t1 = threading.Thread(target=forward_ws_to_tcp, args=(client_socket, remote_socket), daemon=True)
        t2 = threading.Thread(target=forward_tcp_to_ws, args=(remote_socket, client_socket), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception as e:
        print(f"[!] Error: {e}")
    finally:
        try:
            client_socket.close()
        except:
            pass
        if remote_socket:
            try:
                remote_socket.close()
            except:
                pass


def handle_client(client_socket, client_addr):
    print(f"[+] Connection from {client_addr[0]}")
    try:
        client_socket.settimeout(60)
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client_socket.recv(4096)
            if not chunk:
                return
            request += chunk

        lines = request.decode().split("\r\n")
        first_line = lines[0]
        method, path, _ = first_line.split()

        headers = {}
        for line in lines[1:]:
            if ": " in line:
                key, value = line.split(": ", 1)
                headers[key.lower()] = value

        if path == "/health":
            response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nOK"
            client_socket.send(response.encode())
            client_socket.close()
            return

        if headers.get("upgrade", "").lower() == "websocket":
            handle_websocket(client_socket, path, headers)
        else:
            response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nWebSocket Tunnel Server"
            client_socket.send(response.encode())
            client_socket.close()
    except Exception as e:
        print(f"[!] Error: {e}")
        try:
            client_socket.close()
        except:
            pass


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(100)

    print(f"�🚀 WebSocket Tunnel Server running on port {PORT}")

    while True:
        client, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(client, addr), daemon=True)
        t.start()


if __name__ == '__main__':
    main()
