"""kortex auth commands."""

from __future__ import annotations

import getpass
from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.config import (
    CliProfile,
    get_profile,
    set_active_profile,
    update_profile,
)
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Authenticate against the Kortex API.", no_args_is_help=True)


@app.command()
def login(
    email: Annotated[str, typer.Option(prompt=True)],
    api_url: Annotated[str, typer.Option(envvar="KORTEX_API_URL")] = "http://localhost:8000",
    profile: Annotated[str, typer.Option()] = "default",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Log in with email + password and save tokens to the profile."""
    password = getpass.getpass("password: ")
    client = ApiClient(profile=CliProfile(name=profile, api_url=api_url))
    try:
        result = client.post(
            "/v1/auth/login", json={"email": email, "password": password}
        )
    except CliApiError as e:
        fail(str(e))
        return
    update_profile(
        CliProfile(
            name=profile,
            api_url=api_url,
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
        )
    )
    set_active_profile(profile)
    print_obj({"profile": profile, "expires_in": result["expires_in"]}, json_output=json_output)


@app.command()
def whoami(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.get("/v1/auth/whoami")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command()
def use(profile: str) -> None:
    """Switch active profile."""
    set_active_profile(profile)
    print_obj({"active": profile})


@app.command()
def logout() -> None:
    """Forget tokens for the active profile."""
    p = get_profile()
    update_profile(CliProfile(name=p.name, api_url=p.api_url, api_key=None,
                              access_token=None, refresh_token=None))
    print_obj({"profile": p.name, "logged_out": True})
