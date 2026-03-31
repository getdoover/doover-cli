import time
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
import rich

from pydoover.api.auth import AuthProfile, ConfigManager, Doover2AuthClient

DEFAULT_AUTH_CLIENT_ID = "08a9ae8c-0668-428b-a691-f7eaa526aca0"


class DooverCLIAuthClient(Doover2AuthClient):
    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        profile_name: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._config_manager = config_manager
        self._profile_name = profile_name

    @classmethod
    def device_login(
        cls,
        *,
        staging: bool = False,
        timeout: float = 60.0,
        open_browser: bool = True,
    ) -> "DooverCLIAuthClient":
        if staging:
            auth_server_url = "https://auth.staging.udoover.com"
            control_base_url = "https://api.staging.udoover.com"
            data_base_url = "https://data.staging.udoover.com/api"
        else:
            auth_server_url = "https://auth.doover.com"
            control_base_url = "https://api.doover.com"
            data_base_url = "https://data.doover.com/api"

        config = requests.get(
            f"{auth_server_url}/.well-known/openid-configuration",
            timeout=timeout,
        ).json()
        endpoint = config["device_authorization_endpoint"]

        device_config = requests.post(
            endpoint,
            params={
                "client_id": DEFAULT_AUTH_CLIENT_ID,
                "scope": "offline_access",
                "metaData.device.name": "Doover CLI - Python",
                "metaData.device.type": "other",
            },
            timeout=timeout,
        ).json()

        rich.print(
            f"[green]User Code: \n\n[bold cyan]{device_config['user_code']}[/bold cyan]\n[/green]"
        )

        login_url = f"{auth_server_url}/oauth2/device?" + urlencode(
            {
                "user_code": device_config["user_code"],
                "client_id": DEFAULT_AUTH_CLIENT_ID,
            }
        )
        print(
            f"Alternatively, copy this link into your browser to complete the login:\n{login_url}"
        )
        if open_browser:
            webbrowser.open(login_url, new=0, autoraise=True)

        for _ in range(device_config["expires_in"] // device_config["interval"]):
            time.sleep(device_config["interval"])

            resp = requests.post(
                config["token_endpoint"],
                params={
                    "device_code": device_config["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": DEFAULT_AUTH_CLIENT_ID,
                },
                timeout=timeout,
            )
            if not resp.ok:
                continue

            token_data = resp.json()
            return cls(
                token=token_data["access_token"],
                token_expires=datetime.now(timezone.utc)
                + timedelta(seconds=token_data["expires_in"]),
                control_base_url=control_base_url,
                data_base_url=data_base_url,
                auth_server_url=auth_server_url,
                auth_server_client_id=DEFAULT_AUTH_CLIENT_ID,
                refresh_token=token_data["refresh_token"],
                refresh_token_id=token_data["refresh_token_id"],
                timeout=timeout,
            )

        raise RuntimeError("Auth login expired. Please try again later.")

    @classmethod
    def from_profile_name(
        cls,
        profile_name: str,
        *,
        config_manager: ConfigManager | None = None,
        timeout: float = 60.0,
    ) -> "DooverCLIAuthClient":
        manager = config_manager or ConfigManager(profile_name)
        profile = manager.get(profile_name)
        if profile is None:
            raise RuntimeError(f"No configuration found for profile {profile_name}.")

        return cls(
            token=profile.token,
            token_expires=profile.token_expires,
            refresh_token=profile.refresh_token,
            refresh_token_id=profile.refresh_token_id,
            control_base_url=profile.control_base_url,
            data_base_url=profile.data_base_url,
            auth_server_url=profile.auth_server_url,
            auth_server_client_id=profile.auth_server_client_id,
            timeout=timeout,
            config_manager=manager,
            profile_name=profile_name,
        )

    def to_profile(self, profile_name: str) -> AuthProfile:
        return AuthProfile(
            profile=profile_name,
            token=self.token,
            token_expires=self.token_expires,
            control_base_url=self.control_base_url,
            data_base_url=self.data_base_url,
            refresh_token=self.refresh_token,
            refresh_token_id=self.refresh_token_id,
            auth_server_url=self.auth_server_url,
            auth_server_client_id=self.auth_server_client_id,
        )

    def persist_profile(
        self,
        profile_name: str | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        manager = config_manager or self._config_manager
        name = profile_name or self._profile_name
        if manager is None or name is None:
            return

        manager.create(self.to_profile(name))
        manager.current_profile = name
        manager.write()
        self._config_manager = manager
        self._profile_name = name

    def refresh_access_token(self):
        super().refresh_access_token()
        self.persist_profile()
