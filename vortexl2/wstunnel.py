#!/usr/bin/env python3
"""
VortexL2 wstunnel Module

Manages wstunnel for traffic obfuscation.
Wraps WireGuard UDP traffic in WebSocket Secure (wss://) to look like HTTPS.
"""

import subprocess
import os
import logging
import platform
import urllib.request
import tarfile
import zipfile
from pathlib import Path
from typing import Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Configuration
WSTUNNEL_VERSION = "10.1.0"  # Latest stable version
WSTUNNEL_BIN_PATH = Path("/usr/local/bin/wstunnel")
WSTUNNEL_CONFIG_DIR = Path("/etc/vortexl2/wstunnel")
WSTUNNEL_CERT_DIR = WSTUNNEL_CONFIG_DIR / "certs"
WSTUNNEL_LOG_FILE = Path("/var/log/vortexl2/wstunnel.log")

# Default ports
WSTUNNEL_LISTEN_PORT = 443  # HTTPS port for stealth
WIREGUARD_PORT = 51820      # WireGuard default port


def run_command(cmd: str, timeout: int = 30) -> Tuple[bool, str, str]:
    """Execute shell command."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def check_wstunnel_installed() -> bool:
    """Check if wstunnel is installed."""
    return WSTUNNEL_BIN_PATH.exists()


def get_wstunnel_version() -> Optional[str]:
    """Get installed wstunnel version."""
    if not check_wstunnel_installed():
        return None
    
    success, stdout, _ = run_command(f"{WSTUNNEL_BIN_PATH} --version")
    if success:
        return stdout.split()[-1] if stdout else None
    return None


def download_wstunnel() -> Tuple[bool, str]:
    """
    Download and install wstunnel binary from GitHub releases.
    """
    arch = platform.machine()
    
    # Map architecture names
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64", 
        "aarch64": "aarch64",
        "arm64": "aarch64"
    }
    
    if arch not in arch_map:
        return False, f"Unsupported architecture: {arch}"
    
    arch_name = arch_map[arch]
    
    # Download URL for wstunnel
    filename = f"wstunnel_{WSTUNNEL_VERSION}_linux_{arch_name}.tar.gz"
    url = f"https://github.com/erebe/wstunnel/releases/download/v{WSTUNNEL_VERSION}/{filename}"
    
    try:
        logger.info(f"Downloading wstunnel from {url}")
        
        # Download to temp location
        temp_file = Path(f"/tmp/{filename}")
        urllib.request.urlretrieve(url, temp_file)
        
        # Extract binary
        with tarfile.open(temp_file, "r:gz") as tar:
            # Find the wstunnel binary in archive
            for member in tar.getmembers():
                if member.name.endswith("wstunnel") or member.name == "wstunnel":
                    member.name = "wstunnel"
                    tar.extract(member, "/tmp")
                    break
        
        # Move to final location
        temp_bin = Path("/tmp/wstunnel")
        if temp_bin.exists():
            temp_bin.rename(WSTUNNEL_BIN_PATH)
            os.chmod(WSTUNNEL_BIN_PATH, 0o755)
            logger.info(f"wstunnel installed to {WSTUNNEL_BIN_PATH}")
        else:
            return False, "Binary not found in archive"
        
        # Cleanup
        temp_file.unlink(missing_ok=True)
        
        return True, f"wstunnel {WSTUNNEL_VERSION} installed successfully"
    
    except Exception as e:
        logger.error(f"Failed to download wstunnel: {e}")
        return False, f"Download failed: {e}"


def install_wstunnel() -> Tuple[bool, str]:
    """Install wstunnel if not present."""
    if check_wstunnel_installed():
        version = get_wstunnel_version()
        return True, f"wstunnel already installed (version: {version})"
    
    return download_wstunnel()


def generate_self_signed_cert() -> Tuple[bool, str]:
    """
    Generate self-signed TLS certificate for wstunnel.
    
    For production, use Let's Encrypt or real certificate.
    """
    try:
        WSTUNNEL_CERT_DIR.mkdir(parents=True, exist_ok=True)
        
        cert_file = WSTUNNEL_CERT_DIR / "server.crt"
        key_file = WSTUNNEL_CERT_DIR / "server.key"
        
        if cert_file.exists() and key_file.exists():
            return True, "TLS certificate already exists"
        
        # Generate self-signed certificate
        cmd = (
            f'openssl req -x509 -newkey rsa:4096 -keyout {key_file} -out {cert_file} '
            f'-days 365 -nodes -subj "/CN=cdn.cloudflare.com/O=Cloudflare/C=US"'
        )
        
        success, stdout, stderr = run_command(cmd)
        if not success:
            return False, f"Failed to generate certificate: {stderr}"
        
        # Secure permissions
        os.chmod(key_file, 0o600)
        os.chmod(cert_file, 0o644)
        
        logger.info("Generated self-signed TLS certificate")
        return True, f"TLS certificate generated at {cert_file}"
    
    except Exception as e:
        return False, f"Certificate generation failed: {e}"


def create_server_systemd_service(listen_port: int = WSTUNNEL_LISTEN_PORT) -> str:
    """Create systemd service for wstunnel server (Kharej)."""
    cert_file = WSTUNNEL_CERT_DIR / "server.crt"
    key_file = WSTUNNEL_CERT_DIR / "server.key"
    
    # wstunnel v10+ command syntax for server with TLS
    # Listens on 443 (HTTPS) and forwards to local WireGuard port
    service_content = f"""[Unit]
Description=VortexL2 wstunnel Server (Stealth Layer)
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={WSTUNNEL_BIN_PATH} server \\
    wss://0.0.0.0:{listen_port} \\
    --tls-certificate {cert_file} \\
    --tls-private-key {key_file} \\
    --restrict-to 127.0.0.1:{WIREGUARD_PORT}
Restart=always
RestartSec=5
StandardOutput=append:{WSTUNNEL_LOG_FILE}
StandardError=append:{WSTUNNEL_LOG_FILE}

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""
    return service_content


def create_client_systemd_service(
    server_host: str,
    server_port: int = WSTUNNEL_LISTEN_PORT
) -> str:
    """Create systemd service for wstunnel client (Iran)."""
    
    # wstunnel v10+ command syntax for client
    # Listens locally on WireGuard port and tunnels to server via WSS
    service_content = f"""[Unit]
Description=VortexL2 wstunnel Client (Stealth Layer)
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={WSTUNNEL_BIN_PATH} client \\
    --local-to-remote udp://127.0.0.1:{WIREGUARD_PORT}:127.0.0.1:{WIREGUARD_PORT} \\
    wss://{server_host}:{server_port} \\
    --tls-verify-certificate false
Restart=always
RestartSec=5
StandardOutput=append:{WSTUNNEL_LOG_FILE}
StandardError=append:{WSTUNNEL_LOG_FILE}

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""
    return service_content


def install_service(service_content: str, service_name: str = "vortexl2-wstunnel") -> Tuple[bool, str]:
    """Install systemd service file."""
    try:
        service_path = Path(f"/etc/systemd/system/{service_name}.service")
        
        with open(service_path, 'w') as f:
            f.write(service_content)
        
        # Reload systemd
        run_command("systemctl daemon-reload")
        
        return True, f"Service installed: {service_name}"
    
    except Exception as e:
        return False, f"Failed to install service: {e}"


def start_wstunnel_server(listen_port: int = WSTUNNEL_LISTEN_PORT) -> Tuple[bool, str]:
    """Start wstunnel in server mode (Kharej)."""
    steps = []
    
    # Ensure wstunnel is installed
    success, msg = install_wstunnel()
    steps.append(f"Install: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Generate TLS certificate
    success, msg = generate_self_signed_cert()
    steps.append(f"TLS Cert: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Create log directory
    WSTUNNEL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Install and start service
    service_content = create_server_systemd_service(listen_port)
    success, msg = install_service(service_content)
    steps.append(f"Service: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Enable and start
    run_command("systemctl enable vortexl2-wstunnel")
    success, stdout, stderr = run_command("systemctl start vortexl2-wstunnel")
    
    if not success:
        steps.append(f"Start failed: {stderr}")
        return False, "\n".join(steps)
    
    steps.append(f"✓ wstunnel server started on port {listen_port}")
    return True, "\n".join(steps)


def start_wstunnel_client(
    server_host: str,
    server_port: int = WSTUNNEL_LISTEN_PORT
) -> Tuple[bool, str]:
    """Start wstunnel in client mode (Iran)."""
    steps = []
    
    # Ensure wstunnel is installed  
    success, msg = install_wstunnel()
    steps.append(f"Install: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Create log directory
    WSTUNNEL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Install and start service
    service_content = create_client_systemd_service(server_host, server_port)
    success, msg = install_service(service_content)
    steps.append(f"Service: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Enable and start
    run_command("systemctl enable vortexl2-wstunnel")
    success, stdout, stderr = run_command("systemctl start vortexl2-wstunnel")
    
    if not success:
        steps.append(f"Start failed: {stderr}")
        return False, "\n".join(steps)
    
    steps.append(f"✓ wstunnel client connected to {server_host}:{server_port}")
    return True, "\n".join(steps)


def stop_wstunnel() -> Tuple[bool, str]:
    """Stop wstunnel service."""
    run_command("systemctl stop vortexl2-wstunnel")
    run_command("systemctl disable vortexl2-wstunnel")
    return True, "wstunnel stopped"


def get_status() -> dict:
    """Get wstunnel status."""
    status = {
        "installed": check_wstunnel_installed(),
        "version": get_wstunnel_version(),
        "running": False,
        "mode": None,
        "port": None
    }
    
    # Check if service is running
    success, stdout, _ = run_command("systemctl is-active vortexl2-wstunnel")
    status["running"] = success and stdout.strip() == "active"
    
    # Determine mode from service file
    service_path = Path("/etc/systemd/system/vortexl2-wstunnel.service")
    if service_path.exists():
        content = service_path.read_text()
        if "server" in content:
            status["mode"] = "server"
        elif "client" in content:
            status["mode"] = "client"
    
    return status


def test_connectivity(server_host: str, server_port: int = WSTUNNEL_LISTEN_PORT) -> Tuple[bool, str]:
    """
    Test wstunnel connectivity to server.
    """
    try:
        import socket
        import ssl
        
        # Create SSL context
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        # Try HTTPS connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        
        ssl_sock = context.wrap_socket(sock, server_hostname=server_host)
        ssl_sock.connect((server_host, server_port))
        ssl_sock.close()
        
        return True, f"TLS connection to {server_host}:{server_port} successful"
    
    except socket.timeout:
        return False, f"Connection to {server_host}:{server_port} timed out"
    except ConnectionRefusedError:
        return False, f"Connection to {server_host}:{server_port} refused"
    except Exception as e:
        return False, f"Connection test failed: {e}"


def full_teardown() -> Tuple[bool, str]:
    """Complete wstunnel teardown."""
    steps = []
    
    # Stop service
    stop_wstunnel()
    steps.append("Service stopped")
    
    # Remove service file
    service_path = Path("/etc/systemd/system/vortexl2-wstunnel.service")
    if service_path.exists():
        service_path.unlink()
        run_command("systemctl daemon-reload")
        steps.append("Service file removed")
    
    # Optionally remove certificates
    if WSTUNNEL_CERT_DIR.exists():
        import shutil
        shutil.rmtree(WSTUNNEL_CERT_DIR, ignore_errors=True)
        steps.append("Certificates removed")
    
    steps.append("✓ wstunnel teardown complete")
    return True, "\n".join(steps)
