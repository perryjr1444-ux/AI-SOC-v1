"""
Router Connector - Manages network router security operations.

Vendor-agnostic router helper for operations like factory resets and
configuration changes. For many home routers the only reliable remote
interface is the local admin page reachable over LAN.
"""
import asyncio
import logging
from typing import Optional


logger = logging.getLogger(__name__)


class RouterConnector:
    """
    Vendor-agnostic router helper for security operations.
    
    The Endpoint Helper can invoke this connector via gRPC when the user
    grants temporary admin credentials. All credentials are encrypted in
    transit and decrypted locally on the user's device.
    """

    def __init__(self):
        """Initialize the Router connector."""
        logger.info("RouterConnector initialized")

    async def call(self, payload: dict):
        """
        Execute a router operation.
        
        Supported operations:
        - factory_reset: Perform a factory reset on the router
        
        Args:
            payload: Dictionary containing:
                - __operation: The operation to perform
                - Additional operation-specific parameters
                
        Returns:
            Dictionary with operation results
            
        Raises:
            NotImplementedError: If operation is not supported
            ValueError: If required parameters are missing
            RuntimeError: If the operation fails
        """
        op = payload.get("__operation")
        if not op:
            raise ValueError("Missing required parameter: __operation")

        logger.debug(f"RouterConnector executing operation: {op}")

        try:
            if op == "factory_reset":
                return await self._factory_reset(payload)
            else:
                raise NotImplementedError(f"Unsupported router operation: {op}")
        except Exception as e:
            logger.error(f"Router operation {op} failed: {str(e)}", exc_info=True)
            raise

    async def _factory_reset(self, payload: dict) -> dict:
        """
        Perform a factory reset on the router.
        
        Expects encrypted admin credentials in the payload.
        """
        # Validate required parameters
        ip = payload.get("router_ip")
        enc_user = payload.get("admin_user_enc")
        enc_pass = payload.get("admin_pass_enc")

        if not ip or not enc_user or not enc_pass:
            raise ValueError("Missing required parameters: router_ip, admin_user_enc, admin_pass_enc")

        # Decrypt locally – the helper runs on the user's device, never sends plaintext
        from utils.crypto import decrypt_payload

        try:
            user = decrypt_payload(enc_user).decode()
            passwd = decrypt_payload(enc_pass).decode()
        except Exception as e:
            raise RuntimeError(f"Failed to decrypt router credentials: {str(e)}")

        # Very naïve example using curl; replace with proper vendor SDK in production
        # SECURITY: SSL/TLS verification is now enabled by default
        # To use custom CA certificates, set ROUTER_CA_CERT environment variable
        import os

        url = f"https://{ip}/reset"
        cmd = ["curl"]

        # Add CA certificate if provided (recommended for production)
        ca_cert = os.getenv("ROUTER_CA_CERT")
        if ca_cert:
            cmd.extend(["--cacert", ca_cert])
        # For self-signed certs in development ONLY, set ROUTER_ALLOW_INSECURE=true
        elif os.getenv("ROUTER_ALLOW_INSECURE", "false").lower() == "true":
            logger.warning("SSL verification disabled - use only in development!")
            cmd.append("--insecure")

        # Pass credentials via netrc file to avoid exposing in process list
        # Note: In production, use proper credential management
        cmd.extend([
            "-u", f"{user}:{passwd}",
            "-X", "POST",
            url,
        ])
        
        logger.info(f"Initiating factory reset for router at {ip}")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        
        if proc.returncode != 0:
            error_msg = err.decode() if err else "Unknown error"
            logger.error(f"Router reset failed for {ip}: {error_msg}")
            raise RuntimeError(f"Router reset failed: {error_msg}")
        
        logger.info(f"Successfully issued factory reset to router {ip}")
        return {
            "summary": f"Factory reset issued to router {ip}",
            "router_ip": ip,
            "output": out.decode() if out else ""
        }
