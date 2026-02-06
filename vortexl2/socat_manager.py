"""
VortexL2 Socat Port Forwarding Manager

Manages simple TCP port forwarding using socat.
Each port gets its own socat process.
"""

import subprocess
import re
from typing import List, Dict, Tuple, Optional


def run_command(cmd: str) -> Tuple[bool, str, str]:
    """Execute a shell command and return success, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


class SocatManager:
    """Manages socat-based port forwarding."""
    
    def __init__(self):
        """Initialize Socat manager."""
        pass
    
    def start_forward(self, local_port: int, remote_ip: str, remote_port: int) -> Tuple[bool, str]:
        """
        Start socat forward for a single port.
        
        Args:
            local_port: Local port to listen on
            remote_ip: Remote IP to forward to
            remote_port: Remote port to forward to
        
        Returns:
            (success, message)
        """
        # Check if socat is installed
        success, _, _ = run_command("which socat")
        if not success:
            return False, "socat is not installed. Install with: apt-get install socat"
        
        # Check if port is already in use
        if self.is_port_forwarded(local_port):
            return False, f"Port {local_port} is already being forwarded"
        
        # Build socat command
        # socat TCP-LISTEN:<port>,fork,reuseaddr TCP:<remote_ip>:<remote_port>
        cmd = f"nohup socat TCP-LISTEN:{local_port},fork,reuseaddr TCP:{remote_ip}:{remote_port} >/dev/null 2>&1 &"
        
        success, stdout, stderr = run_command(cmd)
        if not success:
            return False, f"Failed to start socat: {stderr}"
        
        # Verify it started
        import time
        time.sleep(0.2)
        if self.is_port_forwarded(local_port):
            return True, f"Socat forward started: {local_port} → {remote_ip}:{remote_port}"
        else:
            return False, "Socat process did not start successfully"
    
    def stop_forward(self, local_port: int) -> Tuple[bool, str]:
        """
        Stop socat forward for a specific port.
        
        Args:
            local_port: Local port to stop forwarding
        
        Returns:
            (success, message)
        """
        if not self.is_port_forwarded(local_port):
            return True, f"Port {local_port} is not being forwarded"
        
        # Kill socat process listening on this port
        cmd = f"pkill -f 'socat.*TCP-LISTEN:{local_port}[^0-9]'"
        success, stdout, stderr = run_command(cmd)
        
        # Verify it stopped
        import time
        time.sleep(0.2)
        if not self.is_port_forwarded(local_port):
            return True, f"Stopped socat forward on port {local_port}"
        else:
            return False, f"Failed to stop socat on port {local_port}"
    
    def stop_all_forwards(self) -> Tuple[bool, str]:
        """
        Stop all socat forwards.
        
        Returns:
            (success, message)
        """
        # Kill all socat processes
        cmd = "pkill -f 'socat.*TCP-LISTEN'"
        success, stdout, stderr = run_command(cmd)
        
        # Verify
        import time
        time.sleep(0.2)
        forwards = self.list_active_forwards()
        if len(forwards) == 0:
            return True, "All socat forwards stopped"
        else:
            return False, f"Some socat processes still running: {len(forwards)} remaining"
    
    def is_port_forwarded(self, local_port: int) -> bool:
        """
        Check if a port is currently being forwarded by socat.
        
        Args:
            local_port: Port to check
        
        Returns:
            True if forwarded, False otherwise
        """
        cmd = f"pgrep -f 'socat.*TCP-LISTEN:{local_port}[^0-9]'"
        success, stdout, stderr = run_command(cmd)
        return success and stdout.strip() != ""
    
    def list_active_forwards(self) -> List[Dict[str, any]]:
        """
        List all active socat forwards.
        
        Returns:
            List of dicts with keys: pid, local_port, remote_ip, remote_port
        """
        forwards = []
        
        # Get all socat processes
        cmd = "ps aux | grep '[s]ocat TCP-LISTEN'"
        success, stdout, stderr = run_command(cmd)
        
        if not success or not stdout:
            return forwards
        
        # Parse each line
        for line in stdout.strip().split('\n'):
            if not line:
                continue
            
            # Extract PID (second column)
            parts = line.split()
            if len(parts) < 11:
                continue
            
            pid = parts[1]
            
            # Find the command part (contains socat TCP-LISTEN:...)
            cmd_start = line.find('socat')
            if cmd_start == -1:
                continue
            
            cmd_part = line[cmd_start:]
            
            # Parse: socat TCP-LISTEN:8080,fork,reuseaddr TCP:10.30.30.2:80
            # Extract local port
            listen_match = re.search(r'TCP-LISTEN:(\d+)', cmd_part)
            if not listen_match:
                continue
            local_port = int(listen_match.group(1))
            
            # Extract remote IP and port
            remote_match = re.search(r'TCP:([\d.]+):(\d+)', cmd_part)
            if not remote_match:
                continue
            remote_ip = remote_match.group(1)
            remote_port = int(remote_match.group(2))
            
            forwards.append({
                'pid': pid,
                'local_port': local_port,
                'remote_ip': remote_ip,
                'remote_port': remote_port,
                'status': 'running'
            })
        
        return forwards
    
    def get_status(self) -> Dict[str, any]:
        """
        Get overall status of socat forwarding.
        
        Returns:
            Dict with status information
        """
        forwards = self.list_active_forwards()
        
        return {
            'mode': 'socat',
            'active': len(forwards) > 0,
            'forward_count': len(forwards),
            'forwards': forwards
        }


def stop_all_socat() -> Tuple[bool, str]:
    """
    Convenience function to stop all socat forwards.
    
    Returns:
        (success, message)
    """
    manager = SocatManager()
    return manager.stop_all_forwards()
