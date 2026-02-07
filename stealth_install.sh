#!/bin/bash
#
# VortexL2 Stealth Tunnel Installer
# One-liner installation for encrypted, undetectable tunnels
#
# Usage:
#   Kharej (Server):  curl -fsSL https://raw.githubusercontent.com/.../stealth_install.sh | sudo bash -s -- kharej
#   Iran (Client):    curl -fsSL https://raw.githubusercontent.com/.../stealth_install.sh | sudo bash -s -- iran KHAREJ_IP
#
# Features:
#   - WireGuard encryption (MTU optimized: 1280)
#   - wstunnel obfuscation (wss:// on port 443)
#   - L2TPv3 Layer 2 tunnel
#   - HAProxy port forwarding
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
VORTEXL2_DIR="/opt/vortexl2"
CONFIG_DIR="/etc/vortexl2"
KEYS_DIR="${CONFIG_DIR}/keys"
LOG_DIR="/var/log/vortexl2"
WSTUNNEL_VERSION="10.1.0"
WSTUNNEL_BIN="/usr/local/bin/wstunnel"
WSTUNNEL_PORT=443
WIREGUARD_PORT=51820
WG_MTU=1280  # Conservative MTU for protocol wrapping

# Banner
print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║   ██╗   ██╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗██╗     ║"
    echo "║   ██║   ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝██║     ║"
    echo "║   ██║   ██║██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ ██║     ║"
    echo "║   ╚██╗ ██╔╝██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ ██║     ║"
    echo "║    ╚████╔╝ ╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗███████╗║"
    echo "║     ╚═══╝   ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚══════╝║"
    echo "║                                                               ║"
    echo "║              S T E A L T H   T U N N E L                     ║"
    echo "║         Encrypted • Undetectable • Fast                       ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Logging
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check requirements
check_requirements() {
    log_step "Checking requirements..."
    
    # Check root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (sudo)"
        exit 1
    fi
    
    # Check OS
    if [[ ! -f /etc/debian_version ]] && [[ ! -f /etc/lsb-release ]]; then
        log_error "This script requires Debian/Ubuntu"
        exit 1
    fi
    
    log_info "Requirements check passed"
}

# Create directories
create_directories() {
    log_step "Creating directories..."
    
    mkdir -p "${CONFIG_DIR}/tunnels"
    mkdir -p "${KEYS_DIR}"
    mkdir -p "${LOG_DIR}"
    chmod 700 "${KEYS_DIR}"
    
    log_info "Directories created"
}

# Install system dependencies
install_dependencies() {
    log_step "Installing system dependencies..."
    
    apt-get update -qq
    apt-get install -y -qq \
        python3 \
        python3-pip \
        python3-venv \
        git \
        iproute2 \
        haproxy \
        wireguard-tools \
        openssl \
        curl \
        jq
    
    # Load L2TP kernel modules
    modprobe l2tp_core 2>/dev/null || true
    modprobe l2tp_netlink 2>/dev/null || true
    modprobe l2tp_eth 2>/dev/null || true
    
    # Ensure modules load on boot
    cat > /etc/modules-load.d/vortexl2.conf << EOF
l2tp_core
l2tp_netlink
l2tp_eth
EOF
    
    log_info "System dependencies installed"
}

# Install wstunnel
install_wstunnel() {
    log_step "Installing wstunnel..."
    
    if [[ -f "${WSTUNNEL_BIN}" ]]; then
        log_info "wstunnel already installed"
        return 0
    fi
    
    # Detect architecture
    ARCH=$(uname -m)
    case $ARCH in
        x86_64|amd64) ARCH_NAME="x86_64" ;;
        aarch64|arm64) ARCH_NAME="aarch64" ;;
        *)
            log_error "Unsupported architecture: $ARCH"
            exit 1
            ;;
    esac
    
    # Download wstunnel
    WSTUNNEL_URL="https://github.com/erebe/wstunnel/releases/download/v${WSTUNNEL_VERSION}/wstunnel_${WSTUNNEL_VERSION}_linux_${ARCH_NAME}.tar.gz"
    
    log_info "Downloading wstunnel from ${WSTUNNEL_URL}..."
    
    cd /tmp
    curl -sSL "${WSTUNNEL_URL}" -o wstunnel.tar.gz
    tar -xzf wstunnel.tar.gz
    mv wstunnel "${WSTUNNEL_BIN}"
    chmod +x "${WSTUNNEL_BIN}"
    rm -f wstunnel.tar.gz
    
    log_info "wstunnel ${WSTUNNEL_VERSION} installed"
}

# Install VortexL2 Python package
install_vortexl2() {
    log_step "Installing VortexL2..."
    
    # Clone or update repo
    if [[ -d "${VORTEXL2_DIR}" ]]; then
        cd "${VORTEXL2_DIR}"
        git pull -q
    else
        git clone -q https://github.com/emad1381/VortexL2.git "${VORTEXL2_DIR}"
    fi
    
    # Install Python dependencies
    cd "${VORTEXL2_DIR}"
    pip3 install -q -r requirements.txt 2>/dev/null || {
        apt-get install -y python3-rich python3-yaml
    }
    
    # Create launcher script
    cat > /usr/local/bin/vortexl2 << 'EOF'
#!/bin/bash
cd /opt/vortexl2
exec python3 -m vortexl2.main "$@"
EOF
    chmod +x /usr/local/bin/vortexl2
    
    log_info "VortexL2 installed"
}

# Generate WireGuard keys
generate_wg_keys() {
    log_step "Generating WireGuard keys..."
    
    WG_PRIVATE_KEY=$(wg genkey)
    WG_PUBLIC_KEY=$(echo "$WG_PRIVATE_KEY" | wg pubkey)
    WG_PRESHARED_KEY=$(wg genpsk)
    
    # Save keys
    echo "$WG_PRIVATE_KEY" > "${KEYS_DIR}/wg_private.key"
    echo "$WG_PUBLIC_KEY" > "${KEYS_DIR}/wg_public.key"
    echo "$WG_PRESHARED_KEY" > "${KEYS_DIR}/wg_preshared.key"
    chmod 600 "${KEYS_DIR}"/*.key
    
    log_info "WireGuard keys generated"
    log_info "Public Key: ${WG_PUBLIC_KEY}"
}

# Generate TLS certificate for wstunnel
generate_tls_cert() {
    log_step "Generating TLS certificate..."
    
    CERT_DIR="${CONFIG_DIR}/wstunnel/certs"
    mkdir -p "${CERT_DIR}"
    
    if [[ -f "${CERT_DIR}/server.crt" ]]; then
        log_info "TLS certificate already exists"
        return 0
    fi
    
    openssl req -x509 -newkey rsa:4096 \
        -keyout "${CERT_DIR}/server.key" \
        -out "${CERT_DIR}/server.crt" \
        -days 365 -nodes \
        -subj "/CN=cdn.cloudflare.com/O=Cloudflare/C=US" \
        2>/dev/null
    
    chmod 600 "${CERT_DIR}/server.key"
    
    log_info "TLS certificate generated"
}

# Test UDP connectivity (diagnostic)
test_udp_connectivity() {
    local HOST=$1
    local PORT=${2:-$WIREGUARD_PORT}
    
    log_step "Testing UDP connectivity to ${HOST}:${PORT}..."
    
    # Simple UDP test using nc
    timeout 5 bash -c "echo 'test' | nc -u -w 2 ${HOST} ${PORT}" 2>/dev/null
    
    if [[ $? -eq 0 ]]; then
        log_info "UDP connectivity test passed"
        return 0
    else
        log_warn "UDP may be blocked. Tunnel will use wstunnel for obfuscation."
        log_warn "This is expected behavior - wstunnel wraps UDP in HTTPS"
        return 1
    fi
}

# Setup Kharej (Server)
setup_kharej() {
    log_step "Setting up Kharej (Server) mode..."
    
    # Generate WireGuard keys
    generate_wg_keys
    
    # Generate TLS certificate
    generate_tls_cert
    
    # Create WireGuard config
    # Note: peer key will be added when Iran connects
    cat > /etc/wireguard/wg0.conf << EOF
# VortexL2 Stealth Tunnel - Server (Kharej)
[Interface]
PrivateKey = $(cat ${KEYS_DIR}/wg_private.key)
Address = 10.100.0.1/24
ListenPort = ${WIREGUARD_PORT}
MTU = ${WG_MTU}

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT

# [Peer] will be added when Iran client connects
EOF
    chmod 600 /etc/wireguard/wg0.conf
    
    # Create wstunnel server service
    cat > /etc/systemd/system/vortexl2-wstunnel.service << EOF
[Unit]
Description=VortexL2 wstunnel Server (Stealth Layer)
After=network.target

[Service]
Type=simple
ExecStart=${WSTUNNEL_BIN} server \\
    wss://0.0.0.0:${WSTUNNEL_PORT} \\
    --tls-certificate ${CONFIG_DIR}/wstunnel/certs/server.crt \\
    --tls-private-key ${CONFIG_DIR}/wstunnel/certs/server.key \\
    --restrict-to 127.0.0.1:${WIREGUARD_PORT}
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/wstunnel.log
StandardError=append:${LOG_DIR}/wstunnel.log

[Install]
WantedBy=multi-user.target
EOF
    
    # Enable and start services
    systemctl daemon-reload
    systemctl enable vortexl2-wstunnel
    systemctl start vortexl2-wstunnel
    
    # Save role
    echo "kharej" > "${CONFIG_DIR}/role"
    
    log_info "Kharej setup complete!"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  KHAREJ (SERVER) SETUP COMPLETE${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${YELLOW}Public Key:${NC} $(cat ${KEYS_DIR}/wg_public.key)"
    echo ""
    echo -e "  ${CYAN}Next Steps:${NC}"
    echo -e "  1. Copy the public key above"
    echo -e "  2. Run on Iran server:"
    echo ""
    echo -e "     ${GREEN}curl -fsSL https://raw.githubusercontent.com/emad1381/VortexL2/main/stealth_install.sh | sudo bash -s -- iran YOUR_KHAREJ_IP${NC}"
    echo ""
    echo -e "  3. After Iran setup, add Iran's public key to this server with:"
    echo -e "     ${YELLOW}sudo vortexl2${NC}"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
}

# Setup Iran (Client)
setup_iran() {
    local KHAREJ_IP=$1
    
    if [[ -z "$KHAREJ_IP" ]]; then
        log_error "Kharej IP is required!"
        echo ""
        echo "Usage: $0 iran KHAREJ_IP"
        echo ""
        exit 1
    fi
    
    log_step "Setting up Iran (Client) mode..."
    log_step "Kharej server: ${KHAREJ_IP}"
    
    # Test connectivity
    test_udp_connectivity "${KHAREJ_IP}" "${WSTUNNEL_PORT}" || true
    
    # Generate WireGuard keys
    generate_wg_keys
    
    # Create WireGuard config
    # Note: peer key will be added after getting server's public key
    cat > /etc/wireguard/wg0.conf << EOF
# VortexL2 Stealth Tunnel - Client (Iran)
[Interface]
PrivateKey = $(cat ${KEYS_DIR}/wg_private.key)
Address = 10.100.0.2/24
MTU = ${WG_MTU}

# Peer will be configured after key exchange
# [Peer]
# PublicKey = <KHAREJ_PUBLIC_KEY>
# Endpoint = 127.0.0.1:${WIREGUARD_PORT}
# AllowedIPs = 10.100.0.0/24, 10.30.30.0/24
# PersistentKeepalive = 25
EOF
    chmod 600 /etc/wireguard/wg0.conf
    
    # Create wstunnel client service
    cat > /etc/systemd/system/vortexl2-wstunnel.service << EOF
[Unit]
Description=VortexL2 wstunnel Client (Stealth Layer)
After=network.target

[Service]
Type=simple
ExecStart=${WSTUNNEL_BIN} client \\
    --local-to-remote udp://127.0.0.1:${WIREGUARD_PORT}:127.0.0.1:${WIREGUARD_PORT} \\
    wss://${KHAREJ_IP}:${WSTUNNEL_PORT} \\
    --tls-verify-certificate false
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/wstunnel.log
StandardError=append:${LOG_DIR}/wstunnel.log

[Install]
WantedBy=multi-user.target
EOF
    
    # Save configuration
    echo "iran" > "${CONFIG_DIR}/role"
    echo "${KHAREJ_IP}" > "${CONFIG_DIR}/kharej_ip"
    
    # Enable services (don't start WireGuard yet - need peer key)
    systemctl daemon-reload
    systemctl enable vortexl2-wstunnel
    systemctl start vortexl2-wstunnel
    
    log_info "Iran setup complete!"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  IRAN (CLIENT) SETUP COMPLETE${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${YELLOW}Your Public Key:${NC} $(cat ${KEYS_DIR}/wg_public.key)"
    echo ""
    echo -e "  ${CYAN}Next Steps:${NC}"
    echo ""
    echo -e "  1. Get the Kharej server's public key"
    echo -e "  2. Run ${YELLOW}sudo vortexl2${NC} to complete setup"
    echo -e "  3. Exchange keys and test connection"
    echo ""
    echo -e "  ${CYAN}Quick Test Commands:${NC}"
    echo -e "     wstunnel status: ${YELLOW}systemctl status vortexl2-wstunnel${NC}"
    echo -e "     wstunnel logs:   ${YELLOW}journalctl -u vortexl2-wstunnel -f${NC}"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
}

# Install base VortexL2 system services
install_services() {
    log_step "Installing VortexL2 system services..."
    
    # Copy systemd services from repo
    cp "${VORTEXL2_DIR}/systemd/vortexl2-tunnel.service" /etc/systemd/system/
    cp "${VORTEXL2_DIR}/systemd/vortexl2-forward-daemon.service" /etc/systemd/system/
    
    systemctl daemon-reload
    systemctl enable vortexl2-tunnel
    
    log_info "Services installed"
}

# Main
main() {
    print_banner
    
    ROLE=${1:-}
    KHAREJ_IP=${2:-}
    
    if [[ -z "$ROLE" ]]; then
        echo ""
        echo "Usage:"
        echo "  Kharej (Server):  $0 kharej"
        echo "  Iran (Client):    $0 iran KHAREJ_IP"
        echo ""
        exit 1
    fi
    
    check_requirements
    create_directories
    install_dependencies
    install_wstunnel
    install_vortexl2
    install_services
    
    case "$ROLE" in
        kharej|server)
            setup_kharej
            ;;
        iran|client)
            setup_iran "$KHAREJ_IP"
            ;;
        *)
            log_error "Unknown role: $ROLE"
            echo "Valid roles: kharej, iran"
            exit 1
            ;;
    esac
    
    echo ""
    log_info "Installation complete! Run 'sudo vortexl2' to manage your tunnel."
}

main "$@"
