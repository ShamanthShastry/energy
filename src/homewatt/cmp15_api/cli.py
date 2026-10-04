from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def serve(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000), reload: bool = typer.Option(False)):
    """Run the API (and the built dashboard at / when dashboard/dist exists)."""
    import uvicorn

    uvicorn.run("homewatt.cmp15_api.app:app", host=host, port=port, reload=reload, log_level="info")
