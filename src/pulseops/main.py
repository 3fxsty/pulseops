from fastapi import FastAPI

app = FastAPI(
    title="PulseOps",
    description="Uptime monitoring for websites and APIs.",
    version="0.1.0",
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe: answers as long as the API process is up."""
    return {"status": "ok"}
