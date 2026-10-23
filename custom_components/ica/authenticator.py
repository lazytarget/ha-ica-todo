import base64
import datetime
import hashlib
import logging
import re
from os import urandom

import homeassistant.util.dt as dt_util
import jwt
import requests

from .const import API
from .exceptions import IcaAuthError
from .icatypes import AuthCredentials, AuthState, JwtUserInfo, OAuthClient, OAuthToken

_LOGGER = logging.getLogger(__name__)


class IcaAuthenticator:
    """Class to handle authentications"""

    _credentials: AuthCredentials
    _auth_state: AuthState | None = None

    def __init__(
        self,
        credentials: AuthCredentials,
        state: AuthState | None,
        session: requests.Session | None = None,
    ) -> None:
        self._session = session or requests.Session()
        self._auth_state = state
        self._credentials = credentials

    def get_rest_url(self, endpoint: str):
        return f"{API.URLs.BASE_URL}/{endpoint}"

    def invoke_get(
        self,
        url,
        params=None,
        data=None,
        headers=None,
        timeout=30,
        allow_redirects=True,
    ):
        response = self._session.get(
            url,
            params=params,
            data=data,
            headers=headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )

        if response.status_code not in [200, 201, 302, 303]:
            _LOGGER.warning("[GET] %s Response Code: %s", url, response.status_code)

        response.raise_for_status()
        return response

    def invoke_post(
        self,
        url,
        params=None,
        data=None,
        json_data=None,
        headers=None,
        timeout=30,
        allow_redirects=True,
    ):
        response = self._session.post(
            url,
            params=params,
            data=data,
            json=json_data,
            headers=headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )

        if response.status_code not in [200, 201, 302, 303]:
            _LOGGER.warning("[POST] %s Response Code: %s", url, response.status_code)

        response.raise_for_status()
        return response

    def get_token_for_app_registration(self):
        url = self.get_rest_url(API.URLs.OAUTH2_TOKEN_ENDPOINT)
        d = {
            "client_id": API.AppRegistration.CLIENT_ID,
            "client_secret": API.AppRegistration.CLIENT_SECRET,
            "grant_type": "client_credentials",
            "scope": "dcr",
            "response_type": "token",
        }
        response = self.invoke_post(url, data=d)
        if response and response.status_code in [200, 201]:
            return response.json()["access_token"]
        response.raise_for_status()
        return None

    def register_app(self) -> OAuthClient:
        app_registration_api_access_token = self.get_token_for_app_registration()
        url = self.get_rest_url(API.AppRegistration.APP_REGISTRATION_ENDPOINT)
        j = {"software_id": "dcr-ica-app-template"}
        h = {"Authorization": f"Bearer {app_registration_api_access_token}"}
        response = self.invoke_post(url, json_data=j, headers=h)
        if response and response.status_code in [200, 201]:
            return OAuthClient(response.json())
        return None

    def init_oauth(self, registered_app: OAuthClient, code_challenge):
        url = self.get_rest_url(API.URLs.OAUTH2_AUTHORIZE_ENDPOINT)
        p = {
            "client_id": registered_app["client_id"],
            "scope": registered_app["scope"],
            "redirect_uri": "icacurity://app",
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
            "acr": "urn:se:curity:authentication:html-form:IcaCustomers",
        }
        # POST /oauth/v2/authorize
        response = self.invoke_get(url, params=p, allow_redirects=False)
        response.raise_for_status()

        location = response.headers.get("Location")
        if not location or not (match := re.search(r"&state=(\w*)", location)):
            raise IcaAuthError("Expected a Location redirect with a state")
        state = match[1]

        # GET /authn/authenticate
        response = self.invoke_get(location)
        response.raise_for_status()

        return state

    def init_login(self, credentials: AuthCredentials, state):
        url = self.get_rest_url(API.URLs.LOGIN_ENDPOINT)
        d = {
            "userName": credentials["username"],
            "password": credentials["password"],
        }
        # Posts login form...
        try:
            response = self.invoke_post(url, data=d)
        except requests.exceptions.HTTPError as err:
            if err.response is not None and err.response.status_code in (400, 401):
                raise IcaAuthError(
                    "Login was rejected, check the personal ID number and PIN"
                ) from err
            raise

        api_state = re.search(
            r'<input type="hidden" name="state" value="(\w*)', response.text
        )
        token = re.search(
            r'<input type="hidden" name="token" value="(\w*)', response.text
        )
        if not api_state or not token:
            # The login form is shown again when the credentials are wrong
            raise IcaAuthError(
                "Login was rejected, check the personal ID number and PIN"
            )

        if api_state[1] != state:
            _LOGGER.warning("Login states differ between client and server")

        return token[1]

    def get_access_token(
        self, registered_app: OAuthClient, state, token, code_verifier
    ) -> OAuthToken:
        url = self.get_rest_url(API.URLs.OAUTH2_AUTHORIZE_ENDPOINT)
        p = {
            "client_id": registered_app["client_id"],
            "forceAuthN": "true",
            "acr": "urn:se:curity:authentication:html-form:IcaCustomers",
        }
        d = {
            "token": token,
            "state": state,
        }
        # POST /oauth/v2/authorize
        response = self.invoke_post(url, params=p, data=d, allow_redirects=False)
        response.raise_for_status()

        location = response.headers.get("Location")
        if not location or not (match := re.search(r"&code=(\w*)", location)):
            raise IcaAuthError(
                "Expected a Location redirect with an authorization code"
            )
        code = match[1]

        # GET /authn/authenticate
        url = self.get_rest_url(API.URLs.OAUTH2_TOKEN_ENDPOINT)
        d = {
            "code": code,
            "client_id": registered_app["client_id"],
            "client_secret": registered_app["client_secret"],
            "grant_type": "authorization_code",
            "scope": registered_app["scope"],
            "response_type": "token",
            "code_verifier": code_verifier,
            "redirect_uri": "icacurity://app",
        }
        response = self.invoke_post(url, data=d)
        response.raise_for_status()
        tkn = response.json()
        return OAuthToken(tkn)

    def get_refresh_token(
        self, registered_app: OAuthClient, auth_token: OAuthToken
    ) -> OAuthToken:
        # Invokes /oauth/v2/token
        url = self.get_rest_url(API.URLs.OAUTH2_TOKEN_ENDPOINT)

        basic_auth = IcaAuthenticator.generate_basic_auth(registered_app)
        h: dict[str, str] = {"Authorization": f"Basic {basic_auth}"}
        d = {
            "grant_type": "refresh_token",
            "refresh_token": auth_token["refresh_token"],
        }
        response = self.invoke_post(url, data=d, headers=h)
        response.raise_for_status()
        tkn = response.json()
        return OAuthToken(tkn)

    @staticmethod
    def generate_basic_auth(registered_app: OAuthClient) -> str:
        """Generates the value for a Basic Auth header"""
        client_id = registered_app["client_id"]
        client_secret = registered_app["client_secret"]
        return base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")

    @staticmethod
    def generate_code_challenge():
        """Generates a code_challenge and code_verifier"""
        code_verifier = base64.urlsafe_b64encode(urandom(40)).decode("utf-8")
        code_verifier = re.sub("[^a-zA-Z0-9]+", "", code_verifier)

        code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode("utf-8")
        code_challenge = code_challenge.replace("=", "")

        return (code_challenge, code_verifier)

    def get_auth_state(self) -> AuthState | None:
        """This will get the current auth statee"""
        return self._auth_state

    def ensure_login(self, refresh: bool | None = None) -> AuthState:
        """This will ensure that a valid auth state is loaded"""
        state = self._auth_state or AuthState()
        self._auth_state = self._handle_login(
            self._credentials, state.copy(), refresh=refresh
        )
        return self._auth_state

    def _handle_login(
        self,
        credentials: AuthCredentials,
        auth_state: AuthState,
        refresh: bool | None = None,
        retry: int = 0,
    ) -> AuthState:
        """This will initiate an new login based on the current state and token expiration"""
        now = dt_util.utcnow()

        if new_client := not auth_state.get("client", None):
            # Initialize new client app to get a client_id/client_secret
            auth_state["client"] = self.register_app()
            _LOGGER.debug("Handle login :: Initialized new client")

        current_token = auth_state.get("token", None)
        current_token_expiry = (
            dt_util.parse_datetime(current_token["expiry"])
            if current_token and current_token.get("expiry", None)
            else None
        )

        if new_client or not current_token:
            auth_state = self._handle_new_login(credentials, auth_state)

        try:
            if current_token_expiry and current_token_expiry < now:
                _LOGGER.info(
                    "Handle login :: Token expired, will refresh... %s < %s",
                    current_token_expiry,
                    now,
                )
                auth_state = self._handle_refresh_login(auth_state)
            elif bool(refresh):
                _LOGGER.info(
                    "Handle login :: Refreshing... %s < %s",
                    current_token_expiry,
                    now,
                )
                auth_state = self._handle_refresh_login(auth_state)
        except requests.exceptions.HTTPError as err:
            if err.response.status_code == 400:
                if retry > 2:
                    _LOGGER.error("Could not refresh the ICA token")
                    raise
                # Initiate a new login
                _LOGGER.info(
                    "Refresh attempt resulted in status %s. Doing a new login instead...",
                    err.response.status_code,
                )
                auth_state = auth_state.copy()
                auth_state.pop("token", None)

                return self._handle_login(
                    credentials, auth_state, refresh, retry=retry + 1
                )
            _LOGGER.warning(
                "Got %s response during login. Err: %s",
                err.response.status_code,
                err,
            )
            raise

        return auth_state

    def _handle_new_login(self, credentials: AuthCredentials, auth_state: AuthState):
        """This will run the complete login chain"""
        _LOGGER.info("Handle login :: Full login initiated")
        now = dt_util.utcnow()

        # Generate code_challenge & code_verifier
        (code_challenge, code_verifier) = IcaAuthenticator.generate_code_challenge()

        # Initiate OAuth login with Authorization-code with PKCE
        state = self.init_oauth(auth_state["client"], code_challenge)

        token = self.init_login(credentials, state)

        access_token = self.get_access_token(
            auth_state["client"], state, token, code_verifier
        )

        auth_state["token"] = access_token
        auth_state["token"]["expiry"] = str(
            now
            + datetime.timedelta(seconds=auth_state["token"].get("expires_in", 2592000))
        )

        # Parse and append the Person Name
        decoded = jwt.decode(
            access_token["id_token"], options={"verify_signature": False}
        )
        auth_state["user"] = JwtUserInfo(decoded)
        return auth_state

    def _handle_refresh_login(self, auth_state: AuthState):
        """This will request a new access_token by sending the refresh_token"""
        now = dt_util.utcnow()

        if refresh_token := self.get_refresh_token(
            auth_state["client"], auth_state["token"]
        ):
            auth_state["token"].update(refresh_token)
            auth_state["token"]["expiry"] = str(
                now
                + datetime.timedelta(
                    seconds=auth_state["token"].get("expires_in", 2592000)
                )
            )
            _LOGGER.debug("Handle login :: Refreshed token")
        else:
            raise IcaAuthError("Failed to refresh the ICA token")
        return auth_state
