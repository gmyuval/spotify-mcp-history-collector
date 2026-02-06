"""Main FastAPI application for Spotify MCP Admin Frontend."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="Spotify MCP Admin Frontend",
    description="Management UI for users, sync status, analytics, logs",
    version="0.1.0",
)


@app.get("/healthz")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Spotify MCP Admin Frontend", "version": "0.1.0"}
