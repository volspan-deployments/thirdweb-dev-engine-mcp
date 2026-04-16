from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
import uvicorn
import threading
from fastmcp import FastMCP
import httpx
import os
import json
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("thirdweb-engine")

ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "http://localhost:3005")
THIRDWEB_API_SECRET_KEY = os.environ.get("THIRDWEB_API_SECRET_KEY", "")


def get_auth_headers() -> dict:
    headers = {
        "Content-Type": "application/json",
    }
    if THIRDWEB_API_SECRET_KEY:
        headers["Authorization"] = f"Bearer {THIRDWEB_API_SECRET_KEY}"
    return headers


@mcp.tool()
async def check_health() -> dict:
    """Check the health and availability of the thirdweb Engine server. Use this first to verify the server is running before making other requests, or to diagnose connectivity issues."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                f"{ENGINE_BASE_URL}/system/health",
                headers=get_auth_headers()
            )
            return {
                "status_code": response.status_code,
                "healthy": response.status_code == 200,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except httpx.ConnectError as e:
            return {"error": f"Connection failed: {str(e)}", "healthy": False}
        except Exception as e:
            return {"error": str(e), "healthy": False}


@mcp.tool()
async def get_api_spec() -> dict:
    """Retrieve the full OpenAPI JSON specification for the Engine server. Use this to discover all available endpoints, their parameters, request/response schemas, and authentication requirements. Useful when exploring capabilities or debugging API usage."""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.get(
                f"{ENGINE_BASE_URL}/openapi.json",
                headers=get_auth_headers()
            )
            if response.status_code == 200:
                return response.json()
            # Fallback to /json endpoint
            response2 = await client.get(
                f"{ENGINE_BASE_URL}/json",
                headers=get_auth_headers()
            )
            return response2.json()
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_authenticated_user() -> dict:
    """Retrieve information about the currently authenticated user session. Use this to verify authentication status, check which wallet address is logged in, or inspect session details after login."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                f"{ENGINE_BASE_URL}/auth/user",
                headers=get_auth_headers()
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_siwe_payload(address: str, chainId: int = 1) -> dict:
    """Generate a Sign-In With Ethereum (SIWE) payload/message that must be signed by the user's wallet to authenticate. Use this before login_with_siwe to obtain the message to sign.

    Args:
        address: The Ethereum wallet address (0x...) that will be used to sign in
        chainId: The EVM chain ID the wallet is connected to (e.g., 1 for Ethereum mainnet)
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                f"{ENGINE_BASE_URL}/auth/payload",
                headers=get_auth_headers(),
                json={"address": address, "chainId": chainId}
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def login_with_siwe(payload: str, signature: str) -> dict:
    """Authenticate with the Engine server using Sign-In With Ethereum (SIWE). First call get_siwe_payload to get a message to sign, then call this tool with the signed message to establish an authenticated session.

    Args:
        payload: The SIWE payload object containing the message that was signed, as returned by the get_siwe_payload tool
        signature: The cryptographic signature of the SIWE payload produced by the wallet
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            # Parse payload if it's a JSON string
            try:
                payload_obj = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload_obj = payload

            response = await client.post(
                f"{ENGINE_BASE_URL}/auth/login",
                headers=get_auth_headers(),
                json={"payload": payload_obj, "signature": signature}
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def logout() -> dict:
    """Log out the current user and revoke the active JWT session token. Use this to end an authenticated session securely."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                f"{ENGINE_BASE_URL}/auth/logout",
                headers=get_auth_headers()
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def relay_transaction(relayerId: str, request: str) -> dict:
    """Submit a gasless transaction through a specific relayer. Use this to send blockchain transactions without the end user paying gas fees. The relayer covers gas costs. Requires a valid relayer ID configured in Engine.

    Args:
        relayerId: UUID of the configured relayer to use for submitting the gasless transaction
        request: JSON string containing the transaction request details including target contract, data, and any forwarder request fields required by the relayer
    """
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            # Parse the request JSON string
            try:
                request_obj = json.loads(request)
            except (json.JSONDecodeError, TypeError):
                return {"error": "Invalid JSON in 'request' parameter"}

            response = await client.post(
                f"{ENGINE_BASE_URL}/relayer/{relayerId}",
                headers=get_auth_headers(),
                json=request_obj
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def get_transaction_status(queueId: Optional[str] = None) -> dict:
    """Check the status of a previously submitted blockchain transaction. Use this to poll whether a transaction has been mined, is pending, failed, or succeeded after submitting it through Engine.

    Args:
        queueId: The Engine queue ID returned when the transaction was submitted, used to look up its current status
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            params = {}
            if queueId:
                params["queueId"] = queueId

            response = await client.get(
                f"{ENGINE_BASE_URL}/transaction/status",
                headers=get_auth_headers(),
                params=params
            )
            return {
                "status_code": response.status_code,
                "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
            }
        except Exception as e:
            return {"error": str(e)}




_SERVER_SLUG = "thirdweb-dev-engine"

def _track(tool_name: str, ua: str = ""):
    import threading
    def _send():
        try:
            import urllib.request, json as _json
            data = _json.dumps({"slug": _SERVER_SLUG, "event": "tool_call", "tool": tool_name, "user_agent": ua}).encode()
            req = urllib.request.Request("https://www.volspan.dev/api/analytics/event", data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

async def health(request):
    return JSONResponse({"status": "ok", "server": mcp.name})

async def tools(request):
    registered = await mcp.list_tools()
    tool_list = [{"name": t.name, "description": t.description or ""} for t in registered]
    return JSONResponse({"tools": tool_list, "count": len(tool_list)})

sse_app = mcp.http_app(transport="sse")

app = Starlette(
    routes=[
        Route("/health", health),
        Route("/tools", tools),
        Mount("/", sse_app),
    ],
    lifespan=sse_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
