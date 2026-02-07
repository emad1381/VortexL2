#!/usr/bin/env python3
"""
VortexL2 WireGuard Integration Module

Manages WireGuard encryption layer for stealth tunnel.
Provides key generation, configuration, and lifecycle management.
"""

import subprocess
import os
import logging
from pathlib import Path
from typing import Tuple, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Configuration paths
WG_CONFIG_DIR = Path("/etc/wireguard")
WG_CONFIG_FILE = WG_CONFIG_DIR / "wg0.conf"
WG_INTERFACE = "wg0"

# Critical settings per user requirements
WG_MTU = 1280  # Conservative MTU for protocol wrapping (L2TP->WG->WSS)
WG_KEEPALIVE = 25  # PersistentKeepalive for NAT traversal
WG_LISTEN_PORT = 51820  # Default WireGuard port (tunneled via wstunnel)


@dataclass
class WireGuardKeys:
    """WireGuard keypair."""
    private_key: str
    public_key: str


def run_command(cmd: str, check: bool = False) -> Tuple[bool, str, str]:
    """Execute shell command and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def check_wireguard_installed() -> bool:
    """Check if WireGuard tools are installed."""
    success, _, _ = run_command("which wg")
    return success


def install_wireguard() -> Tuple[bool, str]:
    """Install WireGuard tools."""
    steps = []
    
    if check_wireguard_installed():
        return True, "WireGuard already installed"
    
    steps.append("Installing WireGuard tools...")
    success, stdout, stderr = run_command("apt-get update && apt-get install -y wireguard-tools")
    
    if not success:
        return False, f"Failed to install WireGuard: {stderr}"
    
    steps.append("WireGuard installed successfully")
    return True, "\n".join(steps)


def generate_keypair() -> WireGuardKeys:
    """Generate WireGuard private/public keypair."""
    # Generate private key
    success, private_key, _ = run_command("wg genkey")
    if not success or not private_key:
        raise RuntimeError("Failed to generate WireGuard private key")
    
    # Derive public key
    success, public_key, _ = run_command(f"echo '{private_key}' | wg pubkey")
    if not success or not public_key:
        raise RuntimeError("Failed to generate WireGuard public key")
    
    return WireGuardKeys(private_key=private_key, public_key=public_key)


def generate_preshared_key() -> str:
    """Generate WireGuard preshared key for additional security."""
    success, psk, _ = run_command("wg genpsk")
    if not success or not psk:
        raise RuntimeError("Failed to generate preshared key")
    return psk


def create_server_config(
    private_key: str,
    peer_public_key: str,
    tunnel_ip: str = "10.100.0.1/24",
    listen_port: int = WG_LISTEN_PORT,
    preshared_key: Optional[str] = None
) -> str:
    """
    Generate WireGuard server configuration (for Kharej).
    
    Args:
        private_key: Server's private key
        peer_public_key: Client's public key
        tunnel_ip: WireGuard tunnel IP (default: 10.100.0.1/24)
        listen_port: UDP listen port
        preshared_key: Optional preshared key for extra security
    
    Returns:
        WireGuard configuration file content
    """
    config = f"""# VortexL2 Stealth Tunnel - WireGuard Server Config
# Generated automatically - do not edit manually

[Interface]
PrivateKey = {private_key}
Address = {tunnel_ip}
ListenPort = {listen_port}
MTU = {WG_MTU}

# Firewall rules for tunnel routing
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT

[Peer]
# Iran Client
PublicKey = {peer_public_key}
AllowedIPs = 10.100.0.2/32
PersistentKeepalive = {WG_KEEPALIVE}
"""
    
    if preshared_key:
        config = config.replace(
            f"AllowedIPs = 10.100.0.2/32",
            f"PresharedKey = {preshared_key}\nAllowedIPs = 10.100.0.2/32"
        )
    
    return config


def create_client_config(
    private_key: str,
    peer_public_key: str,
    server_endpoint: str,
    tunnel_ip: str = "10.100.0.2/24",
    server_port: int = WG_LISTEN_PORT,
    preshared_key: Optional[str] = None
) -> str:
    """
    Generate WireGuard client configuration (for Iran).
    
    Args:
        private_key: Client's private key
        peer_public_key: Server's public key
        server_endpoint: Server's public IP or 127.0.0.1 if via wstunnel
        tunnel_ip: WireGuard tunnel IP (default: 10.100.0.2/24)
        server_port: Server's WireGuard port
        preshared_key: Optional preshared key
    
    Returns:
        WireGuard configuration file content
    """
    # When using wstunnel, endpoint is localhost (wstunnel forwards to real server)
    endpoint = f"{server_endpoint}:{server_port}"
    
    config = f"""# VortexL2 Stealth Tunnel - WireGuard Client Config
# Generated automatically - do not edit manually

[Interface]
PrivateKey = {private_key}
Address = {tunnel_ip}
MTU = {WG_MTU}

[Peer]
# Kharej Server
PublicKey = {peer_public_key}
Endpoint = {endpoint}
AllowedIPs = 10.100.0.0/24, 10.30.30.0/24
PersistentKeepalive = {WG_KEEPALIVE}
"""
    
    if preshared_key:
        config = config.replace(
            f"Endpoint = {endpoint}",
            f"PresharedKey = {preshared_key}\nEndpoint = {endpoint}"
        )
    
    return config


def write_config(config_content: str, config_path: Path = WG_CONFIG_FILE) -> Tuple[bool, str]:
    """Write WireGuard configuration to file with proper permissions."""
    try:
        WG_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        # Secure permissions (owner read/write only)
        os.chmod(config_path, 0o600)
        
        logger.info(f"WireGuard config written to {config_path}")
        return True, f"Config saved to {config_path}"
    
    except Exception as e:
        logger.error(f"Failed to write WireGuard config: {e}")
        return False, f"Failed to write config: {e}"


def start_wireguard(interface: str = WG_INTERFACE) -> Tuple[bool, str]:
    """Start WireGuard interface."""
    # Check if already running
    success, stdout, _ = run_command(f"wg show {interface} 2>/dev/null")
    if success and stdout:
        return True, f"WireGuard {interface} already running"
    
    # Bring up interface
    success, stdout, stderr = run_command(f"wg-quick up {interface}")
    if not success:
        # Try alternative method
        logger.debug(f"wg-quick failed: {stderr}, trying manual setup")
        success, stdout, stderr = run_command(
            f"ip link add dev {interface} type wireguard && "
            f"wg setconf {interface} {WG_CONFIG_FILE} && "
            f"ip link set {interface} up"
        )
        if not success:
            return False, f"Failed to start WireGuard: {stderr}"
    
    logger.info(f"WireGuard {interface} started")
    return True, f"WireGuard {interface} started successfully"


def stop_wireguard(interface: str = WG_INTERFACE) -> Tuple[bool, str]:
    """Stop WireGuard interface."""
    success, stdout, stderr = run_command(f"wg-quick down {interface}")
    if not success:
        # Force cleanup
        run_command(f"ip link del {interface} 2>/dev/null")
    
    return True, f"WireGuard {interface} stopped"


def get_status(interface: str = WG_INTERFACE) -> Dict:
    """Get WireGuard interface status."""
    status = {
        "interface": interface,
        "running": False,
        "public_key": None,
        "listen_port": None,
        "peers": [],
        "transfer": {"rx": 0, "tx": 0}
    }
    
    success, stdout, _ = run_command(f"wg show {interface}")
    if not success or not stdout:
        return status
    
    status["running"] = True
    
    # Parse output
    for line in stdout.split('\n'):
        line = line.strip()
        if line.startswith("public key:"):
            status["public_key"] = line.split(":")[1].strip()
        elif line.startswith("listening port:"):
            status["listen_port"] = int(line.split(":")[1].strip())
        elif line.startswith("transfer:"):
            # Parse transfer stats
            parts = line.split(",")
            for part in parts:
                if "received" in part:
                    status["transfer"]["rx"] = part.strip()
                elif "sent" in part:
                    status["transfer"]["tx"] = part.strip()
        elif line.startswith("peer:"):
            status["peers"].append(line.split(":")[1].strip()[:16] + "...")
    
    return status


def test_udp_connectivity(host: str, port: int = WG_LISTEN_PORT, timeout: int = 5) -> Tuple[bool, str]:
    """
    Test if UDP port is reachable (for diagnostics).
    
    Note: This is a basic test, not definitive for WireGuard connectivity.
    """
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        
        # Send test packet
        sock.sendto(b"test", (host, port))
        
        # Try to receive response (WireGuard won't respond, but we can test if it's blocked)
        try:
            sock.recvfrom(1024)
        except socket.timeout:
            # Timeout is expected (WireGuard doesn't respond to random packets)
            pass
        
        sock.close()
        return True, f"UDP port {port} appears reachable (no immediate rejection)"
    
    except socket.error as e:
        return False, f"UDP connectivity test failed: {e}"
    except Exception as e:
        return False, f"UDP test error: {e}"


def full_setup_server(peer_public_key: str, preshared_key: Optional[str] = None) -> Tuple[bool, str]:
    """
    Complete WireGuard server setup (Kharej side).
    
    Args:
        peer_public_key: Client's public key
        preshared_key: Optional preshared key
    
    Returns:
        (success, message) tuple
    """
    steps = []
    
    # Install WireGuard
    success, msg = install_wireguard()
    steps.append(f"Install: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Generate server keys
    try:
        keys = generate_keypair()
        steps.append(f"Generated server keypair")
    except Exception as e:
        return False, f"Key generation failed: {e}"
    
    # Create config
    config = create_server_config(
        private_key=keys.private_key,
        peer_public_key=peer_public_key,
        preshared_key=preshared_key
    )
    
    success, msg = write_config(config)
    steps.append(f"Config: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Start WireGuard
    success, msg = start_wireguard()
    steps.append(f"Start: {msg}")
    
    if success:
        steps.append(f"\n✓ Server setup complete!")
        steps.append(f"Server Public Key: {keys.public_key}")
    
    return success, "\n".join(steps)


def full_setup_client(
    peer_public_key: str,
    server_endpoint: str,
    preshared_key: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Complete WireGuard client setup (Iran side).
    
    Args:
        peer_public_key: Server's public key
        server_endpoint: Server IP or 127.0.0.1 for wstunnel
        preshared_key: Optional preshared key
    
    Returns:
        (success, message) tuple
    """
    steps = []
    
    # Install WireGuard
    success, msg = install_wireguard()
    steps.append(f"Install: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Generate client keys
    try:
        keys = generate_keypair()
        steps.append(f"Generated client keypair")
    except Exception as e:
        return False, f"Key generation failed: {e}"
    
    # Create config
    config = create_client_config(
        private_key=keys.private_key,
        peer_public_key=peer_public_key,
        server_endpoint=server_endpoint,
        preshared_key=preshared_key
    )
    
    success, msg = write_config(config)
    steps.append(f"Config: {msg}")
    if not success:
        return False, "\n".join(steps)
    
    # Start WireGuard
    success, msg = start_wireguard()
    steps.append(f"Start: {msg}")
    
    if success:
        steps.append(f"\n✓ Client setup complete!")
        steps.append(f"Client Public Key: {keys.public_key}")
    
    return success, "\n".join(steps)


def full_teardown(interface: str = WG_INTERFACE) -> Tuple[bool, str]:
    """Complete WireGuard teardown."""
    steps = []
    
    # Stop interface
    success, msg = stop_wireguard(interface)
    steps.append(f"Stop: {msg}")
    
    # Remove config
    if WG_CONFIG_FILE.exists():
        WG_CONFIG_FILE.unlink()
        steps.append("Config file removed")
    
    steps.append("✓ WireGuard teardown complete")
    return True, "\n".join(steps)
