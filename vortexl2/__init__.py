"""VortexL2 - L2TPv3 Tunnel Manager"""

__version__ = "3.0.0"
__author__ = "Iliya-Developer"

from .config import TunnelConfig, ConfigManager
from .tunnel import TunnelManager
from .forward import ForwardManager

# Stealth tunnel modules
try:
    from .wireguard import WireGuardKeys, generate_keypair
    from .wstunnel import check_wstunnel_installed
except ImportError:
    pass  # Optional dependencies
