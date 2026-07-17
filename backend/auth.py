import os

import msal
from dotenv import load_dotenv

load_dotenv()

SCOPES = os.environ["GRAPH_SCOPES"].split()

# In Docker this points into a volume so the login survives rebuilds
CACHE_PATH = os.environ.get("TOKEN_CACHE_PATH", "token_cache.bin")

# SerializableTokenCache persists refresh tokens across restarts (fine for dev;
# use encrypted storage or a DB for anything beyond local use)
cache = msal.SerializableTokenCache()


def load_cache():
    if os.path.exists(CACHE_PATH):
        cache.deserialize(open(CACHE_PATH).read())


def save_cache():
    if cache.has_state_changed:
        open(CACHE_PATH, "w").write(cache.serialize())


app_msal = None


def get_msal_app():
    global app_msal
    if app_msal is None:
        load_cache()
        app_msal = msal.ConfidentialClientApplication(
            os.environ["CLIENT_ID"],
            client_credential=os.environ["CLIENT_SECRET"],
            authority=os.environ["AUTHORITY"],
            token_cache=cache,
        )
    return app_msal


def get_auth_url():
    return get_msal_app().get_authorization_request_url(
        SCOPES, redirect_uri=os.environ["REDIRECT_URI"]
    )


def redeem_code(code: str):
    app = get_msal_app()
    result = app.acquire_token_by_authorization_code(
        code, scopes=SCOPES, redirect_uri=os.environ["REDIRECT_URI"]
    )
    if "access_token" in result:
        # A new login replaces any previously connected account — otherwise
        # get_token() keeps serving the old account's tokens.
        new_user = (result.get("id_token_claims") or {}).get("preferred_username")
        for acct in app.get_accounts():
            if acct.get("username") != new_user:
                app.remove_account(acct)
    save_cache()
    return result


def get_token() -> str:
    """Silent token acquisition using the cached refresh token."""
    app = get_msal_app()
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("No account connected. Visit /auth/login first.")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    save_cache()
    if not result or "access_token" not in result:
        raise RuntimeError(f"Token refresh failed: {result}")
    return result["access_token"]
