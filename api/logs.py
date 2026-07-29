# api/logs.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
from datetime import datetime

router = APIRouter(prefix="/api/logs", tags=["Logs"])

# Store all active WebSocket connections
connected_clients: List[WebSocket] = []

@router.websocket("/ws")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs"""
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"🟢 Frontend connected (Total clients: {len(connected_clients)})")
    
    # Send welcome message
    await websocket.send_json({
        "type": "info",
        "message": "Connected to log stream",
        "timestamp": datetime.now().isoformat()
    })
    
    try:
        while True:
            # Keep connection alive, wait for messages (or just ping)
            # You can also receive messages from client if needed
            data = await websocket.receive_text()
            # Echo back for testing
            await websocket.send_json({
                "type": "echo",
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"🔴 Frontend disconnected (Total clients: {len(connected_clients)})")
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@router.post("/push")
async def push_log(data: dict):
    """Push a log message to all connected clients"""
    message = {
        "type": data.get("type", "log"),
        "message": data.get("message", ""),
        "data": data.get("data", {}),
        "timestamp": datetime.now().isoformat()
    }
    
    # Send to all connected clients
    for ws in connected_clients[:]:  # Copy list to avoid modification during iteration
        try:
            await ws.send_json(message)
        except Exception as e:
            print(f"Failed to send to client: {e}")
            if ws in connected_clients:
                connected_clients.remove(ws)
    
    return {"ok": True, "clients": len(connected_clients)}


@router.get("/clients")
async def get_client_count():
    """Get number of connected clients"""
    return {"connected_clients": len(connected_clients)}