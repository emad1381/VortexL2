#!/usr/bin/env python3
"""
VortexL2 - L2TPv3 Tunnel Manager

Main entry point and CLI handler.
"""

import sys
import os
import argparse
import subprocess
import signal
from rich.panel import Panel

# Ensure we can import the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vortexl2 import __version__
from vortexl2.config import TunnelConfig, ConfigManager, GlobalConfig
from vortexl2.tunnel import TunnelManager
from vortexl2.forward import get_forward_manager, get_forward_mode, set_forward_mode, ForwardManager
from vortexl2 import ui


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    print("\n")
    ui.console.print("[yellow]Interrupted. Goodbye![/]")
    sys.exit(0)


def check_root():
    """Check if running as root."""
    if os.geteuid() != 0:
        ui.show_error("VortexL2 must be run as root (use sudo)")
        sys.exit(1)


def restart_forward_daemon():
    """Restart the forward daemon service to pick up config changes.
    
    Only starts HAProxy if forward mode is 'haproxy'.
    """
    mode = get_forward_mode()
    
    # Only start HAProxy if in haproxy mode
    if mode == "haproxy":
        subprocess.run(
            "systemctl start haproxy",
            shell=True,
            capture_output=True
        )
    
    # Restart the forward daemon
    subprocess.run(
        "systemctl restart vortexl2-forward-daemon",
        shell=True,
        capture_output=True
    )


def cmd_apply():
    """
    Apply all tunnel configurations (idempotent).
    Used by systemd service on boot.
    Note: Port forwarding is managed by the forward-daemon service
    """
    manager = ConfigManager()
    tunnels = manager.get_all_tunnels()
    
    if not tunnels:
        print("VortexL2: No tunnels configured, skipping")
        return 0
    
    errors = 0
    for config in tunnels:
        if not config.is_configured():
            print(f"VortexL2: Tunnel '{config.name}' not fully configured, skipping")
            continue
        
        tunnel = TunnelManager(config)
        
        # Setup tunnel
        success, msg = tunnel.full_setup()
        print(f"Tunnel '{config.name}': {msg}")
        
        if not success:
            errors += 1
            continue
    
    print("VortexL2: Tunnel setup complete. Port forwarding managed by forward-daemon service")
    return 1 if errors > 0 else 0


def handle_prerequisites():
    """Handle prerequisites installation."""
    ui.show_banner()
    ui.show_info("Installing prerequisites...")
    
    # Use temp config for prerequisites (they're system-wide)
    tunnel = TunnelManager(TunnelConfig("temp"))
    
    success, msg = tunnel.install_prerequisites()
    ui.show_output(msg, "Prerequisites Installation")
    
    if success:
        ui.show_success("Prerequisites installed successfully")
    else:
        ui.show_error(msg)
    
    ui.wait_for_enter()


def handle_create_tunnel(manager: ConfigManager):
    """Handle tunnel creation (config + start)."""
    ui.show_banner()
    
    # Ask for side first
    side = ui.prompt_tunnel_side()
    if not side:
        return
    
    # Get tunnel name
    name = ui.prompt_tunnel_name()
    if not name:
        return
    
    if manager.tunnel_exists(name):
        ui.show_error(f"Tunnel '{name}' already exists")
        ui.wait_for_enter()
        return
    
    # Create tunnel config in memory (not saved yet)
    config = manager.create_tunnel(name)
    ui.show_info(f"Tunnel '{name}' will use interface {config.interface_name}")
    
    # Configure tunnel based on side
    if not ui.prompt_tunnel_config(config, side, manager):
        # User cancelled or error - no config file was created
        ui.show_error("Configuration cancelled.")
        ui.wait_for_enter()
        return
    
    # Start tunnel
    ui.show_info("Starting tunnel...")
    tunnel = TunnelManager(config)
    success, msg = tunnel.full_setup()
    ui.show_output(msg, "Tunnel Setup")
    
    if success:
        # Only save config after successful tunnel creation
        config.save()
        ui.show_success(f"Tunnel '{name}' created and started successfully!")
    else:
        ui.show_error("Tunnel creation failed. Config not saved.")
    
    ui.wait_for_enter()


def handle_delete_tunnel(manager: ConfigManager):
    """Handle tunnel deletion (stop + remove config)."""
    ui.show_banner()
    ui.show_tunnel_list(manager)
    
    tunnels = manager.list_tunnels()
    if not tunnels:
        ui.show_warning("No tunnels to delete")
        ui.wait_for_enter()
        return
    
    selected = ui.prompt_select_tunnel(manager)
    if not selected:
        return
    
    if not ui.confirm(f"Are you sure you want to delete tunnel '{selected}'?", default=False):
        return
    
    # Stop tunnel first
    config = manager.get_tunnel(selected)
    if config:
        tunnel = TunnelManager(config)
        forward = ForwardManager(config)
        
        # Remove all port forwards from config
        if config.forwarded_ports:
            ui.show_info("Clearing port forwards from config...")
            ports_to_remove = list(config.forwarded_ports)  # Copy list since we're modifying it
            for port in ports_to_remove:
                forward.remove_forward(port)
            ui.show_success(f"Removed {len(ports_to_remove)} port forward(s) from config")
        
        # Stop tunnel
        ui.show_info("Stopping tunnel...")
        success, msg = tunnel.full_teardown()
        ui.show_output(msg, "Tunnel Teardown")
    
    # Delete config
    manager.delete_tunnel(selected)
    ui.show_success(f"Tunnel '{selected}' deleted")
    ui.wait_for_enter()


def handle_list_tunnels(manager: ConfigManager):
    """Handle listing all tunnels."""
    ui.show_banner()
    ui.show_tunnel_list(manager)
    ui.wait_for_enter()


def handle_forwards_menu(manager: ConfigManager):
    """Handle port forwards submenu."""
    ui.show_banner()
    
    # Select tunnel for forwards
    config = ui.prompt_select_tunnel_for_forwards(manager)
    if not config:
        return
    
    while True:
        ui.show_banner()
        
        # Get current forward mode
        current_mode = get_forward_mode()
        
        # Get the appropriate manager based on mode
        forward = get_forward_manager(config)
        
        ui.console.print(f"[bold]Managing forwards for tunnel: [magenta]{config.name}[/][/]\n")
        
        if current_mode == "none":
            ui.console.print("[yellow]⚠ Port forwarding is DISABLED. Select option 6 to enable.[/]\n")
        else:
            ui.console.print(f"[green]Forward mode: {current_mode.upper()}[/]\n")
        
        # Show current forwards if manager is available
        if forward:
            forwards = forward.list_forwards()
            if forwards:
                ui.show_forwards_list(forwards)
        else:
            # Show config-only forwards when mode is none
            from vortexl2.haproxy_manager import HAProxyManager
            temp_manager = HAProxyManager(config)
            forwards = temp_manager.list_forwards()
            if forwards:
                ui.show_forwards_list(forwards)
        
        choice = ui.show_forwards_menu(current_mode)
        
        if choice == "0":
            break
        elif choice == "1":
            # Add forwards - require mode selection first
            if current_mode == "none":
                ui.show_error("Please select a port forward mode first! (Option 6)")
            else:
                ports = ui.prompt_ports()
                if ports:
                    # Always use HAProxyManager to add to config (it just updates YAML)
                    from vortexl2.haproxy_manager import HAProxyManager
                    config_manager = HAProxyManager(config)
                    success, msg = config_manager.add_multiple_forwards(ports)
                    ui.show_output(msg, "Add Forwards to Config")
                    restart_forward_daemon()
                    ui.show_success("Forwards added. Daemon restarted to apply changes.")
            ui.wait_for_enter()
        elif choice == "2":
            # Remove forwards (from config)
            ports = ui.prompt_ports()
            if ports:
                from vortexl2.haproxy_manager import HAProxyManager
                config_manager = HAProxyManager(config)
                success, msg = config_manager.remove_multiple_forwards(ports)
                ui.show_output(msg, "Remove Forwards from Config")
                if current_mode != "none":
                    restart_forward_daemon()
                    ui.show_success("Forwards removed. Daemon restarted to apply changes.")
            ui.wait_for_enter()
        elif choice == "3":
            # List forwards (already shown above)
            ui.wait_for_enter()
        elif choice == "4":
            # Restart daemon
            if current_mode == "none":
                ui.show_error("Port forwarding is disabled. Enable a mode first.")
            else:
                restart_forward_daemon()
                ui.show_success("Forward daemon restarted.")
            ui.wait_for_enter()
        elif choice == "5":
            # Validate and reload
            if current_mode == "none":
                ui.show_error("Port forwarding is disabled. Enable a mode first.")
            elif forward:
                ui.show_info("Validating configuration and reloading...")
                success, msg = forward.validate_and_reload()
                ui.show_output(msg, "Validate & Reload")
                if success:
                    ui.show_success("Reloaded successfully")
                else:
                    ui.show_error(msg)
            ui.wait_for_enter()
        elif choice == "6":
            # Change forward mode
            mode_choice = ui.show_forward_mode_menu(current_mode)
            new_mode = None
            if mode_choice == "1":
                new_mode = "none"
            elif mode_choice == "2":
                new_mode = "haproxy"
            elif mode_choice == "3":
                new_mode = "socat"
            
            if new_mode and new_mode != current_mode:
                # Stop and cleanup current mode before switching
                if current_mode == "haproxy":
                    ui.show_info("Stopping HAProxy forwards...")
                    if forward:
                        import asyncio
                        try:
                            asyncio.run(forward.stop_all_forwards())
                            ui.show_success("✓ HAProxy forwards stopped")
                        except Exception as e:
                            ui.show_warning(f"Could not stop HAProxy gracefully: {e}")
                    # Always stop HAProxy service when switching away from haproxy mode
                    subprocess.run("systemctl stop haproxy", shell=True, capture_output=True)
                    subprocess.run("systemctl stop vortexl2-forward-daemon", shell=True, capture_output=True)
                
                elif current_mode == "socat":
                    ui.show_info("Stopping Socat forwards...")
                    try:
                        from vortexl2.socat_manager import stop_all_socat
                        success, msg = stop_all_socat()
                        if success:
                            ui.show_success(f"✓ {msg}")
                        else:
                            ui.show_warning(msg)
                    except Exception as e:
                        ui.show_warning(f"Could not stop Socat gracefully: {e}")
                    subprocess.run("systemctl stop vortexl2-forward-daemon", shell=True, capture_output=True)
                
                # Set new mode
                set_forward_mode(new_mode)
                ui.show_success(f"Forward mode changed to: {new_mode.upper()}")
                
                # If enabling a mode, offer to start
                if new_mode != "none":
                    if ui.Confirm.ask("Start port forwarding now?", default=True):
                        restart_forward_daemon()
                        ui.show_success("Forward daemon started.")
                else:
                    # Make sure everything is stopped when going to none
                    subprocess.run("systemctl stop haproxy", shell=True, capture_output=True)
                    subprocess.run("systemctl stop vortexl2-forward-daemon", shell=True, capture_output=True)
                    ui.show_info("All port forwarding stopped.")
            ui.wait_for_enter()
        elif choice == "7":
            # Setup auto-restart cron
            from vortexl2.cron_manager import (
                get_auto_restart_status,
                add_auto_restart_cron,
                remove_auto_restart_cron
            )
            
            enabled, status = get_auto_restart_status()
            ui.console.print(f"\n[bold]Current status:[/] {status}\n")
            
            ui.console.print("[bold white]Auto-Restart Setup:[/]")
            ui.console.print("  Configure automatic restart for HAProxy port forwarding daemon")
            ui.console.print("  (Note: This only restarts port forwarding, NOT tunnels)\n")
            ui.console.print("[bold cyan]Options:[/]")
            ui.console.print("  [bold cyan][1][/] Enable with custom interval")
            ui.console.print("  [bold cyan][2][/] Disable auto-restart")
            ui.console.print("  [bold cyan][0][/] Cancel\n")
            
            cron_choice = ui.Prompt.ask("[bold cyan]Select option[/]", default="0")
            
            if cron_choice == "1":
                ui.console.print("\n[dim]Enter restart interval in minutes (e.g., 30, 60, 120)[/]")
                ui.console.print("[dim]Recommended: 60 (every hour), 30 (every 30 min)[/]")
                interval_input = ui.Prompt.ask("[bold cyan]Interval (minutes)[/]", default="60")
                
                try:
                    interval = int(interval_input)
                    if interval < 1:
                        ui.show_error("Interval must be at least 1 minute")
                    elif interval > 1440:
                        ui.show_error("Interval cannot exceed 1440 minutes (24 hours)")
                    else:
                        success, msg = add_auto_restart_cron(interval)
                        if success:
                            ui.show_success(msg)
                        else:
                            ui.show_error(msg)
                except ValueError:
                    ui.show_error(f"Invalid interval: {interval_input}. Must be a number.")
            elif cron_choice == "2":
                success, msg = remove_auto_restart_cron()
                if success:
                    ui.show_success(msg)
                else:
                    ui.show_error(msg)
            
            ui.wait_for_enter()


def handle_logs(manager: ConfigManager):
    """Handle log viewing."""
    ui.show_banner()
    
    services = [
        "vortexl2-tunnel.service",
        "vortexl2-forward-daemon.service"
    ]
    
    for service in services:
        result = subprocess.run(
            f"journalctl -u {service} -n 20 --no-pager",
            shell=True,
            capture_output=True,
            text=True
        )
        output = result.stdout or result.stderr or "No logs available"
        ui.show_output(output, f"Logs: {service}")
    
    ui.wait_for_enter()


def handle_uninstall():
    """Complete uninstall of VortexL2 and all its components."""
    ui.show_banner()
    
    ui.console.print(Panel(
        "[bold red]⚠️ WARNING: Complete Uninstall[/]\n\n"
        "This will remove:\n"
        "• All VortexL2 files and scripts\n"
        "• All tunnel configurations\n"
        "• All WireGuard configs and keys\n"
        "• All systemd services\n"
        "• All logs and data\n\n"
        "[yellow]This action cannot be undone![/]",
        title="🗑️ Uninstall VortexL2",
        border_style="red"
    ))
    
    if not ui.confirm("\n⚠️ Are you SURE you want to completely remove VortexL2?", default=False):
        ui.show_info("Uninstall cancelled.")
        ui.wait_for_enter()
        return
    
    # Double confirm
    if not ui.confirm("🔴 FINAL WARNING: Type 'y' to confirm complete removal", default=False):
        ui.show_info("Uninstall cancelled.")
        ui.wait_for_enter()
        return
    
    ui.show_info("Starting complete uninstall...")
    
    # 1. Stop all services
    ui.show_info("[1/7] Stopping services...")
    services = [
        "vortexl2-tunnel",
        "vortexl2-forward-daemon",
        "vortexl2-wstunnel",
        "wg-quick@wg0",
    ]
    for service in services:
        subprocess.run(f"systemctl stop {service}", shell=True, capture_output=True)
        subprocess.run(f"systemctl disable {service}", shell=True, capture_output=True)
    
    # Stop WireGuard
    subprocess.run("wg-quick down wg0", shell=True, capture_output=True)
    
    # 2. Remove systemd service files
    ui.show_info("[2/7] Removing systemd services...")
    service_files = [
        "/etc/systemd/system/vortexl2-tunnel.service",
        "/etc/systemd/system/vortexl2-forward-daemon.service",
        "/etc/systemd/system/vortexl2-wstunnel.service",
    ]
    for f in service_files:
        subprocess.run(f"rm -f {f}", shell=True, capture_output=True)
    subprocess.run("systemctl daemon-reload", shell=True, capture_output=True)
    
    # 3. Remove WireGuard configs
    ui.show_info("[3/7] Removing WireGuard configs...")
    subprocess.run("rm -f /etc/wireguard/wg0.conf", shell=True, capture_output=True)
    
    # 4. Remove VortexL2 directories
    ui.show_info("[4/7] Removing VortexL2 files...")
    dirs_to_remove = [
        "/opt/vortexl2",
        "/etc/vortexl2",
        "/var/log/vortexl2",
        "/var/lib/vortexl2",
    ]
    for d in dirs_to_remove:
        subprocess.run(f"rm -rf {d}", shell=True, capture_output=True)
    
    # 5. Remove launcher script
    ui.show_info("[5/7] Removing launcher...")
    subprocess.run("rm -f /usr/local/bin/vortexl2", shell=True, capture_output=True)
    
    # 6. Remove wstunnel binary
    ui.show_info("[6/7] Removing wstunnel...")
    subprocess.run("rm -f /usr/local/bin/wstunnel", shell=True, capture_output=True)
    
    # 7. Remove kernel module configs
    ui.show_info("[7/7] Cleaning up system configs...")
    subprocess.run("rm -f /etc/modules-load.d/vortexl2.conf", shell=True, capture_output=True)
    
    ui.console.print()
    ui.show_success("✅ VortexL2 has been completely removed!")
    ui.console.print("\n[dim]Thank you for using VortexL2![/]")
    ui.console.print("[dim]GitHub: github.com/emad1381/VortexL2[/]")
    ui.wait_for_enter()
    
    # Exit the program
    ui.console.print("\n[bold green]Goodbye![/]\n")
    sys.exit(0)


def handle_stealth_port_forwards():
    """Handle stealth tunnel port forwards with HAProxy."""
    from pathlib import Path
    
    HAPROXY_STEALTH_CFG = Path("/etc/vortexl2/haproxy/stealth.cfg")
    HAPROXY_STEALTH_CFG.parent.mkdir(parents=True, exist_ok=True)
    
    # Get tunnel IPs based on role
    role_file = Path("/etc/vortexl2/role")
    role = role_file.read_text().strip() if role_file.exists() else "unknown"
    
    if role == "iran":
        local_ip = "10.100.0.2"
        remote_ip = "10.100.0.1"
    else:
        local_ip = "10.100.0.1"
        remote_ip = "10.100.0.2"
    
    while True:
        ui.show_banner()
        
        # Show current forwards
        forwards = []
        if HAPROXY_STEALTH_CFG.exists():
            content = HAPROXY_STEALTH_CFG.read_text()
            import re
            for match in re.finditer(r'frontend stealth_(\d+)', content):
                port = match.group(1)
                forwards.append(port)
        
        ui.console.print(Panel(
            f"[bold cyan]🔀 Stealth Port Forwards[/]\n\n"
            f"[bold]Role:[/] {role.upper()}\n"
            f"[bold]Local Tunnel IP:[/] {local_ip}\n"
            f"[bold]Remote Tunnel IP:[/] {remote_ip}\n\n"
            f"[bold]Active Forwards:[/] {', '.join(forwards) if forwards else 'None'}",
            border_style="green"
        ))
        
        menu_items = [
            ("1", "➕ Add Port Forward"),
            ("2", "➖ Remove Port Forward"),
            ("3", "📋 List Port Forwards"),
            ("4", "🔄 Restart HAProxy"),
            ("5", "✅ Validate Config"),
            ("0", "← Back"),
        ]
        
        from rich.table import Table
        from rich import box
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        table.add_column("Option", style="bold cyan", width=4)
        table.add_column("Description", style="white")
        
        for opt, desc in menu_items:
            table.add_row(f"[{opt}]", desc)
        
        ui.console.print(table)
        choice = ui.Prompt.ask("\n[bold cyan]Select option[/]", default="0")
        
        if choice == "0":
            break
            
        elif choice == "1":
            # Add port forward
            ui.show_banner()
            ui.console.print(Panel(
                f"[bold yellow]Add Port Forward[/]\n\n"
                f"Traffic will be forwarded:\n"
                f"[cyan]0.0.0.0:PORT → {remote_ip}:PORT[/]\n\n"
                f"This allows external connections to reach the other server through the stealth tunnel.",
                border_style="yellow"
            ))
            
            port = ui.Prompt.ask("\n[bold cyan]Port to forward[/]", default="")
            if not port or not port.isdigit():
                ui.show_error("Invalid port")
                ui.wait_for_enter()
                continue
            
            port = int(port)
            if port < 1 or port > 65535:
                ui.show_error("Port must be 1-65535")
                ui.wait_for_enter()
                continue
            
            # Generate HAProxy config for this port
            haproxy_entry = f"""
# Stealth forward port {port}
frontend stealth_{port}
    bind *:{port}
    mode tcp
    default_backend stealth_backend_{port}

backend stealth_backend_{port}
    mode tcp
    server tunnel {remote_ip}:{port} check
"""
            
            # Read existing config or create new
            if HAPROXY_STEALTH_CFG.exists():
                existing = HAPROXY_STEALTH_CFG.read_text()
                if f"frontend stealth_{port}" in existing:
                    ui.show_warning(f"Port {port} already configured")
                    ui.wait_for_enter()
                    continue
            else:
                existing = "# VortexL2 Stealth Port Forwards\n# Generated by VortexL2\n"
            
            HAPROXY_STEALTH_CFG.write_text(existing + haproxy_entry)
            
            # Update main HAProxy config to include our file
            main_cfg = Path("/etc/haproxy/haproxy.cfg")
            if main_cfg.exists():
                main_content = main_cfg.read_text()
                include_line = f"# Include stealth forwards\n# See {HAPROXY_STEALTH_CFG}\n"
                if str(HAPROXY_STEALTH_CFG) not in main_content and "stealth forwards" not in main_content:
                    # We'll use a separate approach - create a combined config
                    pass
            
            # Create combined config
            combined_cfg = Path("/etc/vortexl2/haproxy/combined.cfg")
            base_haproxy = """global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

defaults
    log global
    mode tcp
    option tcplog
    option dontlognull
    timeout connect 5000
    timeout client 50000
    timeout server 50000
"""
            combined_cfg.write_text(base_haproxy + HAPROXY_STEALTH_CFG.read_text())
            
            ui.show_success(f"Port {port} forward added!")
            ui.show_info("Restarting HAProxy...")
            
            result = subprocess.run(f"haproxy -c -f {combined_cfg}", shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                subprocess.run(f"haproxy -f {combined_cfg} -D -sf $(cat /run/haproxy.pid 2>/dev/null) 2>/dev/null || haproxy -f {combined_cfg} -D", 
                              shell=True, capture_output=True)
                ui.show_success("HAProxy restarted!")
            else:
                ui.show_error(f"Config error: {result.stderr}")
            ui.wait_for_enter()
            
        elif choice == "2":
            # Remove port forward
            ui.show_banner()
            if not forwards:
                ui.show_warning("No port forwards configured")
                ui.wait_for_enter()
                continue
            
            ui.console.print(f"[bold]Current forwards:[/] {', '.join(forwards)}")
            port = ui.Prompt.ask("\n[bold cyan]Port to remove[/]", default="")
            
            if port not in forwards:
                ui.show_error("Port not found")
                ui.wait_for_enter()
                continue
            
            # Remove from config
            content = HAPROXY_STEALTH_CFG.read_text()
            import re
            pattern = rf'\n# Stealth forward port {port}\nfrontend stealth_{port}.*?backend stealth_backend_{port}.*?check\n'
            content = re.sub(pattern, '', content, flags=re.DOTALL)
            HAPROXY_STEALTH_CFG.write_text(content)
            
            ui.show_success(f"Port {port} removed!")
            ui.show_info("Restart HAProxy with option [4] to apply")
            ui.wait_for_enter()
            
        elif choice == "3":
            # List port forwards
            ui.show_banner()
            if HAPROXY_STEALTH_CFG.exists():
                ui.show_output(HAPROXY_STEALTH_CFG.read_text(), "Stealth Port Forwards Config")
            else:
                ui.show_info("No port forwards configured")
            ui.wait_for_enter()
            
        elif choice == "4":
            # Restart HAProxy
            ui.show_banner()
            combined_cfg = Path("/etc/vortexl2/haproxy/combined.cfg")
            
            if not combined_cfg.exists():
                ui.show_error("No config found. Add a port forward first.")
                ui.wait_for_enter()
                continue
            
            ui.show_info("Restarting HAProxy...")
            subprocess.run("pkill haproxy", shell=True, capture_output=True)
            result = subprocess.run(f"haproxy -f {combined_cfg} -D", shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                ui.show_success("HAProxy restarted!")
            else:
                ui.show_error(f"Error: {result.stderr or result.stdout}")
            ui.wait_for_enter()
            
        elif choice == "5":
            # Validate config
            ui.show_banner()
            combined_cfg = Path("/etc/vortexl2/haproxy/combined.cfg")
            
            if not combined_cfg.exists():
                ui.show_error("No config found. Add a port forward first.")
                ui.wait_for_enter()
                continue
            
            ui.show_info("Validating HAProxy config...")
            result = subprocess.run(f"haproxy -c -f {combined_cfg}", shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                ui.show_success("Config is valid!")
            else:
                ui.show_error(f"Config error:\n{result.stderr}")
            ui.wait_for_enter()


def handle_stealth_menu():
    """Handle stealth tunnel management menu."""
    from pathlib import Path
    
    while True:
        ui.show_banner()
        choice = ui.show_stealth_menu()
        
        if choice == "0":
            return
        
        elif choice == "1":
            # Show stealth status
            ui.show_stealth_status()
            ui.wait_for_enter()
            
        elif choice == "2":
            # Add peer key
            ui.show_banner()
            peer_key = ui.prompt_peer_public_key()
            
            if peer_key:
                role_file = Path("/etc/vortexl2/role")
                role = role_file.read_text().strip() if role_file.exists() else "unknown"
                
                # Read current WireGuard config
                wg_config = Path("/etc/wireguard/wg0.conf")
                if wg_config.exists():
                    config_content = wg_config.read_text()
                    
                    # Check if Peer already exists
                    if "[Peer]" in config_content:
                        ui.show_warning("Peer already configured. Updating...")
                        # Remove old peer section
                        lines = config_content.split('\n')
                        new_lines = []
                        skip = False
                        for line in lines:
                            if line.startswith("[Peer]"):
                                skip = True
                            elif line.startswith("[") and skip:
                                skip = False
                            if not skip:
                                new_lines.append(line)
                        config_content = '\n'.join(new_lines)
                    
                    # Add new peer section
                    psk_file = Path("/etc/vortexl2/keys/wg_preshared.key")
                    psk = psk_file.read_text().strip() if psk_file.exists() else ""
                    
                    if role == "kharej":
                        # Server: Peer is Iran client
                        peer_section = f"""
[Peer]
PublicKey = {peer_key}
AllowedIPs = 10.100.0.2/32
PersistentKeepalive = 25
"""
                    else:
                        # Client: Peer is Kharej server
                        kharej_ip_file = Path("/etc/vortexl2/kharej_ip")
                        kharej_ip = kharej_ip_file.read_text().strip() if kharej_ip_file.exists() else "127.0.0.1"
                        peer_section = f"""
[Peer]
PublicKey = {peer_key}
Endpoint = 127.0.0.1:51820
AllowedIPs = 10.100.0.0/24, 10.30.30.0/24
PersistentKeepalive = 25
"""
                    
                    config_content = config_content.rstrip() + '\n' + peer_section
                    wg_config.write_text(config_content)
                    
                    ui.show_success("Peer key added to WireGuard config!")
                    ui.show_info("Restarting WireGuard interface...")
                    
                    # Stop first if running
                    subprocess.run("wg-quick down wg0", shell=True, capture_output=True)
                    
                    # Start WireGuard
                    result = subprocess.run("wg-quick up wg0", shell=True, capture_output=True, text=True)
                    if result.returncode == 0:
                        ui.show_success("WireGuard started!")
                    else:
                        ui.show_error(f"WireGuard error: {result.stderr or result.stdout}")
                else:
                    ui.show_error("WireGuard config not found. Run stealth_install.sh first.")
                
                ui.wait_for_enter()
            
        elif choice == "3":
            # Start WireGuard
            ui.show_banner()
            ui.show_info("Starting WireGuard...")
            result = subprocess.run("wg-quick up wg0", shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                ui.show_success("WireGuard started!")
            else:
                ui.show_error(f"Error: {result.stderr}")
            ui.wait_for_enter()
            
        elif choice == "4":
            # Stop WireGuard
            ui.show_banner()
            ui.show_info("Stopping WireGuard...")
            result = subprocess.run("wg-quick down wg0", shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                ui.show_success("WireGuard stopped!")
            else:
                ui.show_error(f"Error: {result.stderr}")
            ui.wait_for_enter()
            
        elif choice == "5":
            # View logs
            ui.show_banner()
            for service in ["vortexl2-wstunnel"]:
                result = subprocess.run(
                    f"journalctl -u {service} -n 30 --no-pager",
                    shell=True, capture_output=True, text=True)
                ui.show_output(result.stdout or "No logs", f"Logs: {service}")
            
            # WireGuard status
            result = subprocess.run("wg show", shell=True, capture_output=True, text=True)
            ui.show_output(result.stdout or "WireGuard not running", "WireGuard Status")
            ui.wait_for_enter()
            
        elif choice == "6":
            # Test connection
            ui.show_banner()
            ui.show_info("Testing tunnel connectivity...")
            
            role_file = Path("/etc/vortexl2/role")
            role = role_file.read_text().strip() if role_file.exists() else "unknown"
            
            if role == "kharej":
                test_ip = "10.100.0.2"
            else:
                test_ip = "10.100.0.1"
            
            result = subprocess.run(f"ping -c 3 {test_ip}", shell=True, capture_output=True, text=True)
            ui.show_output(result.stdout or result.stderr, f"Ping {test_ip}")
            
            if result.returncode == 0:
                ui.show_success("Tunnel connectivity OK!")
            else:
                ui.show_error("Tunnel not reachable. Check WireGuard and wstunnel status.")
            ui.wait_for_enter()
            
        elif choice == "7":
            # Show my public key
            ui.show_banner()
            key_file = Path("/etc/vortexl2/keys/wg_public.key")
            if key_file.exists():
                pub_key = key_file.read_text().strip()
                ui.console.print(Panel(
                    f"[bold green]{pub_key}[/]",
                    title="🔐 Your Public Key",
                    border_style="green"
                ))
                ui.console.print("\n[dim]Copy this key and paste it on the other server.[/]")
            else:
                ui.show_error("Keys not generated. Run stealth_install.sh first.")
            ui.wait_for_enter()
            
        elif choice == "8":
            # Regenerate keys
            ui.show_banner()
            if ui.confirm("⚠️ This will generate NEW keys. The other server will need your NEW key. Continue?", default=False):
                ui.show_info("Stopping WireGuard...")
                subprocess.run("wg-quick down wg0", shell=True, capture_output=True)
                
                ui.show_info("Generating new WireGuard keys...")
                result = subprocess.run("wg genkey", shell=True, capture_output=True, text=True)
                private_key = result.stdout.strip()
                
                result = subprocess.run(f"echo '{private_key}' | wg pubkey", shell=True, capture_output=True, text=True)
                public_key = result.stdout.strip()
                
                # Save keys
                keys_dir = Path("/etc/vortexl2/keys")
                keys_dir.mkdir(parents=True, exist_ok=True)
                (keys_dir / "wg_private.key").write_text(private_key)
                (keys_dir / "wg_public.key").write_text(public_key)
                
                # Update WireGuard config
                wg_config = Path("/etc/wireguard/wg0.conf")
                if wg_config.exists():
                    config = wg_config.read_text()
                    import re
                    config = re.sub(r'PrivateKey = .+', f'PrivateKey = {private_key}', config)
                    wg_config.write_text(config)
                
                ui.show_success("New keys generated!")
                ui.console.print(f"\n[bold]New Public Key:[/] [green]{public_key}[/]")
                ui.console.print("\n[yellow]⚠️ Share this new key with the other server![/]")
            ui.wait_for_enter()
            
        elif choice == "9":
            # Disable tunnel
            ui.show_banner()
            if ui.confirm("❌ Disable stealth tunnel completely?", default=False):
                ui.show_info("Stopping WireGuard...")
                subprocess.run("wg-quick down wg0", shell=True, capture_output=True)
                subprocess.run("systemctl disable wg-quick@wg0", shell=True, capture_output=True)
                
                ui.show_info("Stopping wstunnel...")
                subprocess.run("systemctl stop vortexl2-wstunnel", shell=True, capture_output=True)
                subprocess.run("systemctl disable vortexl2-wstunnel", shell=True, capture_output=True)
                
                ui.show_success("Stealth tunnel disabled!")
                ui.console.print("\n[dim]To re-enable, use options [3] Start WireGuard[/]")
            ui.wait_for_enter()
            
        elif choice.lower() == "p":
            # Stealth Port Forwards submenu
            handle_stealth_port_forwards()


def main_menu():
    """Main interactive menu loop."""
    check_root()
    
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Clear screen before starting
    ui.clear_screen()
    
    # Initialize config manager
    manager = ConfigManager()
    
    while True:
        ui.show_banner()
        choice = ui.show_main_menu()
        
        try:
            if choice == "0":
                ui.console.print("\n[bold green]Goodbye![/]\n")
                break
            elif choice == "1":
                handle_prerequisites()
            elif choice == "2":
                handle_create_tunnel(manager)
            elif choice == "3":
                handle_delete_tunnel(manager)
            elif choice == "4":
                handle_list_tunnels(manager)
            elif choice == "5":
                handle_forwards_menu(manager)
            elif choice == "6":
                handle_logs(manager)
            elif choice == "7":
                handle_stealth_menu()
            elif choice == "8":
                handle_uninstall()
            else:
                ui.show_warning("Invalid option")
                ui.wait_for_enter()
        except KeyboardInterrupt:
            ui.console.print("\n[yellow]Interrupted[/]")
            continue
        except Exception as e:
            ui.show_error(f"Error: {e}")
            ui.wait_for_enter()


def main():
    """CLI entry point."""
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    parser = argparse.ArgumentParser(
        description="VortexL2 - L2TPv3 Tunnel Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (none)     Open interactive management panel
  apply      Apply all tunnel configurations (used by systemd)

Examples:
  sudo vortexl2           # Open management panel
  sudo vortexl2 apply     # Apply all tunnels (for systemd)
        """
    )
    parser.add_argument(
        'command',
        nargs='?',
        choices=['apply'],
        help='Command to run'
    )
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'VortexL2 {__version__}'
    )
    
    args = parser.parse_args()
    
    if args.command == 'apply':
        check_root()
        sys.exit(cmd_apply())
    else:
        main_menu()


if __name__ == "__main__":
    main()
