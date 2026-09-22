import requests, json
import hashlib
import pandas as pd
from datetime import datetime
import time, ast
from typing import Union, Optional, Dict, Any, List

from configs.log_utils import get_logger, manila_tz
from configs.config import ENV

logger = get_logger(__file__, level = "INFO")


def _int_env(key: str, default: int) -> int:
    raw = ENV.get(key) if isinstance(ENV, dict) else None
    try:
        return int(raw) if raw is not None else default
    except Exception:
        return default

# Tunables for agent-data fetch to avoid long crawls
AGENT_DATA_MESSAGE_AGE = _int_env("AGENT_DATA_MESSAGE_AGE", 90)
AGENT_DATA_LIMIT = _int_env("AGENT_DATA_LIMIT", 200)

def convert_dt_series(s: pd.Series) -> pd.Series:
    def convert(v):
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
            return pd.NaT
        if isinstance(v, pd.Timestamp):
            # if tz-aware, convert to local then drop tz; if naive, treat as local
            return v.tz_convert(manila_tz).tz_localize(None) if v.tzinfo else v
        # parse strings (handles "2025-08-05 00:47:16", "2025-08-05T00:47:16+08:00", etc.)
        ts = pd.to_datetime(v, errors="coerce", utc=False)
        if pd.isna(ts):
            return pd.NaT
        # if parsed with tz (offset present), convert to local then drop tz
        if getattr(ts, "tzinfo", None):
            ts = ts.tz_convert(manila_tz).tz_localize(None)
        # else it's already naive → treat as local clock time
        return ts

    out = s.map(convert)
    # ensure dtype is datetime64[ns] (tz-naive)
    return pd.to_datetime(out, errors="coerce")


class ManychatUtils:
    """
    A utility class for interacting with the ManyChat API and web interface.
    
    This class provides methods to:
    - Fetch and manage user information
    - Load and process conversation messages
    - Handle chat assignments and agent data
    - Manage tags and custom fields
    - Create notes in conversations
    
    The class supports both API-based operations (using API key) and web interface
    operations (using cookies and headers).

    Attributes:
        DEFAULT_MESSAGE_TYPES (list): Default message types to filter ['msgin', 'msgout_api', 'msgout_lc', 'assign', 'reassign']
        DEFAULT_TIMEOUT (int): Default timeout in seconds for requests (60)
        DEFAULT_MESSAGE_AGE (int): Default message age filter in days (60)
        DEFAULT_LIMIT (int): Default limit for number of messages to retrieve (250)

    Args:
        user_id (Optional[str]): The ManyChat user ID
        user_name (Optional[str]): The ManyChat username
        
    Environment Variables Required:
        MANYCHAT_PAGE_ID: The Facebook page ID connected to ManyChat
        MANYCHAT_API_KEY: The ManyChat API key for authentication
        
    Example:
        >>> manychat = ManychatUtils(user_id="12345")
        >>> user_info = manychat.get_user_info()
        >>> messages = manychat.load_messages(limit=100)
    """

    # constants
    DEFAULT_MESSAGE_TYPES = ['msgin', 'msgout_api', 'msgout_lc',
                             'msgin_tiktok', 'msgout_api_tiktok', 'msgout_lc_tiktok', 
                             'msgin_instagram', 'msgout_api_instagram', 'msgout_lc_instagram', 
                             'assign', 'reassign']
    DEFAULT_TIMEOUT = 30 # seconds
    DEFAULT_MESSAGE_AGE = 60 # days
    DEFAULT_LIMIT = 250 # messages
    
    def __init__(self, 
                 user_id : Union[str, None] = None,
                 user_name : Union[str, None] = None):
        # basic info
        self._api_base_url = 'https://api.manychat.com/fb'
        self._app_base_url = 'https://app.manychat.com/fb'
        self.user_id = user_id if user_id else None
        self.user_name = user_name if user_name else None

        # credentials
        self._page_id = ENV.get('MANYCHAT_PAGE_ID') if isinstance(ENV, dict) else None
        self._api_key = ENV.get('MANYCHAT_API_KEY') if isinstance(ENV, dict) else None

        # headers
        self._app_headers = ast.literal_eval(ENV.get('MANYCHAT_APP_HEADERS', "{}")) if isinstance(ENV, dict) else {}
        self._api_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self._api_key}' if self._api_key else '',
            }

        # cookies
        self._cookies = ast.literal_eval(ENV.get('MANYCHAT_COOKIES', "{}")) if isinstance(ENV, dict) else {}

        if self._api_key:
            self._check_api_key()
        self._user_data = self.get_user_info().get('data') if self.user_id or self.user_name else None
        
        # user-specific attributes
        self.limiter = None
        self._agent_data : Optional[Dict[str, Any]] = None
        self._tags_data : Optional[Dict[str, Any]] = None
        self._cfs_data : Optional[Dict[str, Any]] = None
        self._messages_data : Optional[Dict[str, Any]] = None

    @property
    def api_base_url(self) -> str:
        return self._api_base_url

    @property
    def api_headers(self) -> dict:
        return self._api_headers
        
    def _handle_error(self, exception: Exception, operation: str) -> dict:
        """
        Handles common error response pattern for API calls.
        
        Args:
            exception (Exception): The caught exception
            operation (str): Description of the operation that failed
            
        Returns:
            dict: Standardized error response
        """
        user_data = self.user_name if self.user_name else self.user_id
        
        try:
            error_dict = ast.literal_eval(str(exception))
            try:
                error_message = ast.literal_eval(error_dict.get('text', str(exception)))
            except:
                error_message = error_dict.get('text', str(exception))
            status_code = error_dict.get('status_code')
        except:
            error_message = str(exception)
            status_code = {
                ValueError: 400,
                KeyError: 400,
                TypeError: 400,
                FileNotFoundError: 404,
                NotImplementedError: 501,
            }.get(type(exception), 500)  # Default to 500 for unknown exceptions
        
        status_suffix = f" (status={status_code})" if status_code not in (None, "") else ""
        err_msg = f"Error {operation} for {user_data}{status_suffix}: {error_message}"
        logger.error(err_msg)
        
        return {
            "status": "error",
            "status_code": status_code,
            "message": err_msg,
            "data": None
        }

    def _build_app_page_url(self, path: str) -> str:
        """Build a ManyChat app URL using the configured page id."""
        base = str(self._app_base_url or "").rstrip("/")
        page_id = str(self._page_id or "").strip().strip("/")
        suffix = str(path or "").lstrip("/")
        if not page_id:
            return f"{base}/{suffix}"
        return f"{base}{page_id}/{suffix}"

    def _require_user_id(self) -> Optional[dict]:
        if not self.user_id:
            return {"status": "error", "message": "subscriber_id cannot be blank.", "status_code": 400, "data": None}
        return None

    def _check_api_key(self):
        """Validates API key configuration and tests it against the API."""
        if not self._api_key:
            logger.warning("ManyChat API key is missing.")
            return
        if not (self.user_id or self.user_name):
            return
        response = self.get_user_info()
        if response.get('status') == 'error':
            logger.warning(f"Failed to validate API key for {self.user_name}: {response.get('message')}")

    def get_user_info(self) -> dict:
        """
        Get user information based on user_id or user_name.

        Returns:
            dict: User information if successful, raises an exception otherwise.
        """
        
        if (not self.user_id) and (not self.user_name):
            return {"status": "error", "message": "subscriber_id cannot be blank.", "status_code": 400}
        
        # If user_id is provided, use it to get user info
        if self.user_id:
            params = {
                'subscriber_id': self.user_id
            }
            endpoint = 'getInfo'
        
        # If user_name is provided, use it to get user info
        else:
            params = {
            'name': self.user_name,
            }
            endpoint = 'findByName'

        try:
            response = requests.get(
                                    f'{self._api_base_url}/subscriber/{endpoint}', 
                                    params=params, 
                                    headers=self._api_headers
                        )
            if response.status_code != 200:
                # Store status code before raising exception
                error_response = {
                    'text': response.text,
                    'status_code': response.status_code
                }
                raise Exception(str(error_response))
                
            # update user data if response is successful
            if isinstance(response.json().get('data'), list):
                self.user_id = response.json().get('data')[0]['id']
                self.user_name = response.json().get('data')[0]['name']
                output = response.json()['data'][0]
            else:
                self.user_id = response.json().get('data')['id']
                self.user_name = response.json().get('data')['name']
                output = response.json()['data']

            # update output data
            output['updated_datetime'] = datetime.now(manila_tz)
            output['user_id'] = output.pop('id')
            output['user_name'] = output.pop('name')

            # Process datetime fields
            datetime_fields = ['subscribed', 'last_interaction', 'ig_last_interaction',
                            'last_seen', 'ig_last_seen', 'updated_datetime']
            for field in datetime_fields:
                if field in output:
                    if output[field]:
                        output[field] = pd.to_datetime(output[field]).astimezone(manila_tz).strftime('%Y-%m-%d %H:%M:%S')

            # convert custom fields with datetime types to manila_tz strings
            if output['custom_fields']:
                for cf in output['custom_fields']:
                    if cf['type'] == 'datetime':
                        cf['value'] = pd.to_datetime(cf['value']).astimezone(manila_tz).strftime('%Y-%m-%d %H:%M:%S')

            self.user_info = output
            return {'status' : 'success',
                    'status_code' : 200,
                    'message' : 'Successfully fetched user info.',
                    'data': output}
            
        except Exception as e:
            return self._handle_error(e, 'fetching user info')

    def _safe_post(self, url: str, payload: dict, timeout: int = 10) -> dict:
        """
        Internal helper to standardize POST requests & error handling.
        """
        try:
            response = requests.post(
                url=url,
                headers=self._api_headers,
                data=json.dumps(payload),
                timeout=timeout,
            )
            try:
                body = json.loads(response.text)
            except Exception:
                body = {"raw": response.text}

            if response.status_code == 200:
                return {"status": "success", "message": "success", "data": body}
            else:
                return {
                    "status": "error",
                    "message": body if isinstance(body, dict) else {"error": body},
                    "status_code": response.status_code,
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_content(
            self,
            items: list,
        message_tag: str | None = None,
            channel_subtype: str | None = None,
        ) -> dict:
        """
        Send ManyChat v2 content to a subscriber.

        Args:
            items: list of messages. Each item can be:
                - str (sent as a 'text' message),
                - dict already in ManyChat message format (must include a 'type' key),
                - special dicts like {'type': 'image', 'url': '...'} or full 'cards' payloads.
            message_tag: Optional FB message tag (e.g., 'ACCOUNT_UPDATE').

        Returns:
            dict with 'status' and 'data' (raw ManyChat response)
        """
        if not self.user_id:
            return {"status": "error", "message": "subscriber_id cannot be blank.", "status_code": 400}
        # Normalize items into ManyChat v2 "messages" array
        normalized_messages = []
        for item in items:
            if isinstance(item, str):
                normalized_messages.append({"type": "text", "text": item})
            elif isinstance(item, dict):
                if "type" not in item:
                    # Assume text if not specified
                    normalized_messages.append({"type": "text", "text": json.dumps(item)})
                else:
                    normalized_messages.append(item)
            else:
                # Fallback: stringify unknown objects as text
                normalized_messages.append({"type": "text", "text": str(item)})

        content: dict = {
            "messages": normalized_messages,
        }
        subtype = (channel_subtype or "").strip().lower()
        if subtype in {"instagram", "whatsapp", "telegram", "tiktok"}:
            content["type"] = subtype

        payload = {
            "subscriber_id": self.user_id,
            "data": {
                "version": "v2",
                "content": content,
            },
        }
        # Message tags are no longer supported by FB Messenger for ManyChat.
        if message_tag:
            payload["message_tag"] = message_tag

        return self._safe_post(
            url=f"{self._api_base_url}/sending/sendContent",
            payload=payload,
            timeout=15,
        )
    
    def send_flow(self, flow_ns: str, source: str | None = None) -> dict:
        """
        Trigger a ManyChat flow for the subscriber.

        Args:
            flow_ns: The Namespace of the flow (e.g., 'content.XXXXX').
            source: Optional source string.

        Returns:
            dict with 'status' and 'data'
        """
        missing = self._require_user_id()
        if missing:
            return missing
        payload = {
            "subscriber_id": self.user_id,
            "flow_ns": flow_ns,
        }
        if source:
            payload["source"] = source

        return self._safe_post(
            url=f"{self._api_base_url}/sending/sendFlow",
            payload=payload,
            timeout=10,
        )


    def add_tag(self, tag_name: str) -> dict:
        """
        Add a tag to the subscriber by tag name.

        Args:
            tag_name: The ManyChat tag name.

        Returns:
            dict with 'status' and 'data'
        """
        missing = self._require_user_id()
        if missing:
            return missing
        payload = {"subscriber_id": self.user_id, "tag_name": tag_name}
        return self._safe_post(
            url=f"{self._api_base_url}/subscriber/addTagByName",
            payload=payload,
            timeout=8,
        )

    def delete_tag(self, tag: int | str) -> dict:
        """
        Remove a tag from the subscriber. Accepts either tag_id (int) or tag_name (str).

        Args:
            tag: tag_id (int) or tag_name (str)

        Returns:
            dict with 'status' and 'data'
        """
        missing = self._require_user_id()
        if missing:
            return missing
        # Prefer by name when a string is provided
        if isinstance(tag, str):
            payload = {"subscriber_id": self.user_id, "tag_name": tag}
            # ManyChat supports removeTagByName in newer endpoints; if your workspace doesn't, fallback to id.
            result = self._safe_post(
                url=f"{self._api_base_url}subscriber/removeTagByName",
                payload=payload,
                timeout=8,
            )
            # Fallback if endpoint is unavailable
            if result.get("status") == "error":
                result["hint"] = "If removeTagByName is not enabled, pass a numeric tag_id instead."
            return result
        else:
            payload = {"subscriber_id": self.user_id, "tag_id": int(tag)}
            return self._safe_post(
                url=f"{self._api_base_url}/subscriber/removeTag",
                payload=payload,
                timeout=8,
            )

    def clear_cfs(self, field_names: list[str]) -> dict:
        """
        Clear (reset) multiple custom fields by name.

        Strategy:
        - Strings -> ''
        - Numbers -> 0
        - Booleans -> False
        - Datetime/Date -> null (empty string also acceptable depending on workspace rules)

        If the type can't be discovered from current user info, defaults to ''.

        Args:
            field_names: list of custom field names to reset.

        Returns:
            dict with 'status' and 'data' (per-field results)
        """
        user = self.get_user_info()
        if user.get("status") != "success":
            return {
                "status": "error",
                "message": f"Failed to fetch user info for {self.user_id}: {user.get('message')}",
            }

        cf_list = (user.get("data") or {}).get("custom_fields", []) or []
        type_map = {cf.get("name"): cf.get("type") for cf in cf_list}

        results = {}
        for name in field_names:
            cftype = (type_map.get(name) or "").lower()
            empty_val: Union[str, int, bool, List] = ""
            if cftype in ("number", "numeric", "float", "integer", "int"):
                empty_val = 0
            elif cftype in ("boolean", "bool"):
                empty_val = False
            elif cftype in ("datetime", "date"):
                # For ManyChat, unset by sending an empty string is typically fine
                empty_val = ""
            elif "array" in cftype:
                empty_val = []
            else:
                # default to empty string
                empty_val = ""

            # Reuse your existing endpoint/casing convention
            payload = {
                "subscriber_id": self.user_id,
                "field_name": name,
                "field_value": empty_val,
            }
            res = self._safe_post(
                url=f"{self._api_base_url}/subscriber/setCustomFieldByName",
                payload=payload,
                timeout=6,
            )
            results[name] = res

        # Aggregate status
        errors = {k: v for k, v in results.items() if v.get("status") != "success"}
        if errors:
            return {
                "status": "error",
                "message": f"Failed to clear some fields: {list(errors.keys())}",
                "data": results,
            }
        return {"status": "success", "message": "Custom fields cleared.", "data": results}

    def create_note(self,
                   note_content : str = 'Test Note') -> dict:
        """
        Create a note for the user in ManyChat.

        Args:
            note_content (str): The content of the note to be created.
        """
        missing = self._require_user_id()
        if missing:
            return missing
        try:
            payload = {
                "user_id": self.user_id,         # Conversation/User ID
                "page_id": self._page_id,           # Page ID
                "text": note_content,          # The note content
                "type": "text"
            }

            response = requests.post(
                self._build_app_page_url("im/createNote"),
                json = payload,
                headers = self._app_headers,
                cookies = self._cookies
            )

            if response.status_code != 200:

                error_response = {"text" : response.text,
                                  "status_code" : response.status_code}
                raise Exception(str(error_response))

            return {
                "status": "success",
                "status_code": response.status_code,
                "message": "Note created successfully.",
                "data": response.json()
                }
        
        except Exception as e:
            return self._handle_error(e, 'creating note')

    def filter_recent_users(self) -> dict:
        """
        Fetch subscribers who interacted within the last ~15 minutes (FB/IG/TT),
        paginate until the server stops returning results, then return a
        de-duplicated list with Manila-timezone timestamps.

        This calls the ManyChat web endpoint
        `https://app.manychat.com/<page>/subscribers/search` with a compound
        filter that matches any subscriber whose
        `last_interaction`, `last_ig_interaction`, or `last_tt_interaction`
        occurred after "now - 900 seconds" (~15 minutes). Results are aggregated
        across pages (using the response `limiter` signal), de-duplicated by
        `user_id`, and date fields are converted to Manila time and formatted as
        strings.

        Dependencies:
            - `self._cookies` (requests-compatible cookie jar/dict) with a valid
            ManyChat session.
            - `self.app_headers` containing auth and `Content-Type: application/json`.
            - Globals/utilities: `logger`, `pd` (pandas), `datetime`, `manila_tz`.

        Returns:
            list[dict]: A list of user records with the following keys:
                - `user_id` (str)
                - `user_name` (str)
                - `subscribed` (str | None)  # '%Y-%m-%d %H:%M:%S' in Asia/Manila
                - `last_user_interaction` (str | None)
                - `last_ig_user_interaction` (str | None)
                - `last_tt_user_interaction` (str | None)

            Note: The function signature annotates `-> dict`, but the actual
            return value is a `list[dict]`.

        Exceptions:
            - This function does not raise on HTTP errors. Non-200 responses are
            logged via `logger.error(...)` and the loop terminates early.
            A (possibly partial) list accumulated so far is returned.
            - JSON decoding issues are not explicitly caught; they will raise from
            `response.json()` if the endpoint returns non-JSON.

        Side Effects:
            - Performs one or more HTTP POST requests to ManyChat.
            - Writes progress logs (`info` for page sizes, `error` on non-200).

        Example:
            >>> api = ManyChatAPI(...)
            >>> recent = api.filter_recent_users()
            >>> # recent -> [{'user_id': '...', 'user_name': '...', 'subscribed': '2025-09-04 10:20:00', ...}, ...]

        Logging & Debugging:
            - Each page fetch logs: number of new users, running total, and the
            current `limiter` value.
            - If you suspect pagination issues, enable DEBUG and inspect the raw
            response or verify whether your backend requires passing the received
            `limiter` back on subsequent requests.

        Notes:
            - The 15-minute window is controlled by `value: -900` with the
            `DATETIME_INTERVAL_AFTER` operator. Adjust `value`/`unit` to widen
            or narrow the window.
            - The function de-duplicates by `user_id` and then renames/normalizes
            timestamp fields by stripping the `ts_` prefix and converting to
            Manila time as strings.
        """
        users = []
        limiter = None
        while True:

            json_data = {
                'q': '',
                'filter': {
                    'operator': 'AND',
                    'groups': [
                        {
                            'operator': 'OR',
                            'items': [
                                {
                                    '_oid': 'd4007c22-be03-4a5f-aa2c-4d4cda8b299a',
                                    'type': 'suf',
                                    'field': 'last_interaction',
                                    'operator': 'DATETIME_INTERVAL_AFTER',
                                    'value': -900,
                                    'unit': 'seconds',
                                },
                                {
                                    '_oid': '06417a0d-ad76-412d-bbda-d22684d4e643',
                                    'type': 'suf',
                                    'field': 'last_ig_interaction',
                                    'operator': 'DATETIME_INTERVAL_AFTER',
                                    'value': -900,
                                    'unit': 'seconds',
                                },
                                {
                                    '_oid': 'b10aed4f-8d54-4587-9a73-dce7a1bdad20',
                                    'type': 'suf',
                                    'field': 'last_tt_interaction',
                                    'operator': 'DATETIME_INTERVAL_AFTER',
                                    'value': -900,
                                    'unit': 'seconds',
                                },
                            ],
                        },
                    ],
                },
            }
        
            response = requests.post(
                self._build_app_page_url("subscribers/search"),
                cookies=self._cookies,
                headers=self._app_headers,
                json=json_data,
            )

            # update limiter
            limiter = response.json()['limiter']
            # extend users list with new users
            new_users = response.json()['users']
            users.extend(new_users)
            logger.info(f"Fetched {len(new_users)} users, total: {len(users)}")

            if response.status_code != 200:
                logger.error(f"Error: {response.status_code} - {response.text}")
                break

            if (not response.json()['limiter']) or (not response.json()['users']):
                break
        
        def convert_ts_to_str(ts):
            return datetime.fromtimestamp(ts).astimezone(manila_tz).strftime('%Y-%m-%d %H:%M:%S') if ts else None

        if users:
            # Remove duplicates based on 'id'
            df_users = pd.DataFrame(users).drop_duplicates(subset=['user_id'])

            # Convert datetime fields to Manila timezone strings
            datetime_fields = ["ts_subscribed", "ts_last_user_interaction", "ts_last_ig_user_interaction", 
                               "ts_last_tt_user_interaction"]
            for field in datetime_fields:
                if field in df_users.columns:
                    df_users[field.split("ts_")[-1]] = df_users[field].apply(convert_ts_to_str)
            
            # Change column names
            df_users.rename(columns={"name" : "user_name"}, inplace = True)

            new_cols = ['user_id', 'user_name'] + [col.split('ts_')[-1] for col in datetime_fields]

            # Convert back to list[dict]
            users = df_users[new_cols].to_dict(orient='records')

        return {
            "status": "success",
            "status_code": 200,
            "message": f"Fetched {len(users)} recent users.",
            "data": users
        }

    def send_load_messages_request(
        self,
        limit: int = 500,
        request_timeout: Optional[float] = None,
    ) -> dict:
        """
        Send a request to load messages for the user.
        This method constructs the request parameters and sends it to the ManyChat API. 
        
        Returns:
            dict: The response data from the ManyChat API.
        """
        params = None
        if self.user_id:
            params = {
                'limit': limit if limit else 500,
                'user_id': self.user_id,
                'type': 'facebook',
                'limiter' : self.limiter,
            }

        if not params:
            # If no user_id is provided, raise an exception
            raise Exception(str({'text' : 'User ID is required for loading messages.',
                                 'status_code' : None}))
        
        try:
            target_url = self._build_app_page_url("im/loadMessages")
            response = requests.get(
                target_url,
                params=params,
                cookies=self._cookies,
                headers=self._app_headers,
                timeout=request_timeout,
            )
            
            if response.status_code != 200:
                error_response = {
                    "text": response.text,
                    "status_code": response.status_code,
                    "url": target_url,
                }
                raise Exception(str(error_response))
            try:
                body = response.json()
            except Exception:
                body_text = (response.text or "").lstrip().lower()
                content_type = str(response.headers.get("content-type") or "").lower()
                if body_text.startswith("<!doctype html") or "text/html" in content_type:
                    error_response = {
                        "text": (
                            "ManyChat app endpoint returned HTML instead of JSON. "
                            "Likely expired/invalid MANYCHAT_COOKIES or MANYCHAT_APP_HEADERS."
                        ),
                        "status_code": response.status_code,
                        "url": target_url,
                    }
                    raise Exception(str(error_response))
                error_response = {
                    "text": response.text,
                    "status_code": response.status_code,
                    "url": target_url,
                }
                raise Exception(str(error_response))

            return {
                "status": "success",
                "status_code": response.status_code,
                "message": "loadMessages request successful.",
                "data": body
                }
                
        except Exception as e:
            return self._handle_error(e, 'sending loadMessages request')
    
    def _get_message_participants(self, 
                                  message_type: str, 
                                  message_model: Optional[dict] = None, 
                                  last_agent: str = 'Taira') -> tuple:
        """
        Determine message role and participants based on message type.
        
        Args:
            message_type (str): Type of message ('msgout_api', 'msgin', 'msgout_lc', etc.)
            message_model (dict): Message model containing sender information
            last_agent (str): Name of the last agent who sent a message
            
        Returns:
            tuple: (role, sender, receiver, updated_last_agent)
        """
        if message_type in ['msgout_api', 'msgout_api_tiktok']:
            return 'chatbot', 'Taira', self.user_info['user_name'], 'Taira'
            
        elif message_type in ['msgin', 'msgin_tiktok']:
            return 'user', self.user_info['user_name'], last_agent, last_agent
            
        elif message_type in ['msgout_lc', 'msgout_lc_tiktok']:
            new_agent = None
            if message_model and isinstance(message_model, dict):
                sender = message_model.get('sender')
                if sender and isinstance(sender, dict):
                    new_agent = sender.get('user_name')
            return 'agent', new_agent, self.user_info['user_name'], new_agent
            
        else:
            return 'system', None, None, last_agent


    def load_messages(self, 
                     limit : Optional[int] = DEFAULT_LIMIT,
                     date_start : Optional[Union[str, datetime]] = None,
                     date_end : Optional[Union[str, datetime]] = None,
                     message_age_filter : Optional[int] = DEFAULT_MESSAGE_AGE,
                     timeout : Optional[int] = DEFAULT_TIMEOUT,
                     per_message_sleep_s: Optional[float] = 0.25,
                     message_types : Optional[list[str]] = DEFAULT_MESSAGE_TYPES
                     ) -> dict:
        """
        Retrieves all messages from the Manychat hidden API for a specific user ID.
        
        Args:
            limit (int): The maximum number of messages to retrieve. Default is 10.
            date_start (str): The start date for filtering messages in 'YYYY-MM-DD' format. Default is None.
            date_end (str): The end date for filtering messages in 'YYYY-MM-DD'
            message_age_filter (int): The number of days to filter messages by age. Default is 60.
            timeout (int): The maximum time to wait for the request in seconds. Default is 60. 
        
        Returns:
            dict: A dictionary containing the loaded messages and their status.
        """
        missing = self._require_user_id()
        if missing:
            return missing
        all_messages = []
        last_agent = 'Taira'
        message_age_filter = message_age_filter
        date_start_dt = pd.to_datetime(date_start).tz_localize(manila_tz) if date_start else None
        date_end_dt = pd.to_datetime(date_end).tz_localize(manila_tz) if date_end else datetime.now(manila_tz)

        try:
            start_time = time.time()
            while True:
                # Send the request to load messages
                response = self.send_load_messages_request(limit=limit or 100, request_timeout=timeout)
                
                # Ensure response is a dict (handle legacy returns)
                if isinstance(response, requests.Response):
                    try:
                        response = response.json()
                    except Exception:
                        response = {"status_code": response.status_code, "data": None, "message": response.text}
                if not isinstance(response, dict):
                    payload = {
                        "status": "error",
                        "status_code": None,
                        "data": [],
                        "message": "loadMessages request returned an invalid response shape.",
                    }
                    self._messages_data = payload
                    return payload
                if response.get("status_code") != 200:
                    payload = {
                        "status": response.get("status") or "error",
                        "status_code": response.get("status_code"),
                        "data": [],
                        "message": response.get("message") or response.get("error") or "loadMessages request failed.",
                    }
                    self._messages_data = payload
                    return payload

                if response.get('status_code') == 200:
                    r = response['data']
                    if not isinstance(r, dict):
                        payload = {
                            "status": "error",
                            "status_code": response.get("status_code"),
                            "data": [],
                            "message": "loadMessages response data was not a JSON object.",
                        }
                        self._messages_data = payload
                        return payload
                
                    # Get user info
                    if not self.user_info:
                        user_info_response = self.get_user_info()
                        if user_info_response['status'] == 'success':
                            self.user_info = user_info_response['data']
                    
                    self.limiter = r.get('limiter', None)
                    messages = r.get('messages', [])
                    
                    if messages:
                        logger.debug(f'Processing {len(messages)} messages...')
                        messages = sorted(messages, key=lambda x: x['timestamp'], reverse=True)

                        for m in messages:
                            # Check if the request has timed out
                            if timeout is not None and (time.time() - start_time) > timeout:
                                logger.debug("Timeout reached while loading messages.")
                                if not all_messages:
                                    payload = {
                                        'status': 'warning',
                                        'status_code': 404,
                                        'data': [],
                                        'message': 'No messages processed.'
                                    }
                                    self._messages_data = payload          # 🔧 cache even warnings/errors
                                    return payload
                                
                                payload = {
                                    'status': 'success',
                                    'status_code': 200,
                                    'data': sorted(all_messages, key=lambda x: x['datetime']),
                                    'message': 'Timeout reached while loading messages.'
                                }
                                self._messages_data = payload
                                return payload

                            # Check if the message is within the specified date range
                            message_time = datetime.fromtimestamp(m['timestamp']).astimezone(manila_tz)
                            if date_start_dt:
                                if not (date_start_dt <= message_time <= date_end_dt):
                                    logger.debug(f"Message {m['message_id']} is outside the date range {date_start_dt} to {date_end_dt}. Skipping...")
                                    continue
                            else:
                                if not (message_time <= date_end_dt):
                                    logger.debug(f"Message {m['message_id']} is after the end date {date_end_dt}. Skipping...")
                                    continue
                            
                            if message_age_filter and all_messages:
                                # Check if the message is more than {message_age_filter} days from the earliest message
                                earliest_message = sorted(all_messages, key=lambda x: x['datetime'])[0]
                                earliest_message_time = pd.to_datetime(earliest_message['datetime']).tz_localize(manila_tz)
                                
                                # If the difference is more than the message_age_filter, stop processing further messages
                                if (earliest_message_time - message_time).days > message_age_filter:
                                    logger.debug(f"Remaining messages are more than {message_age_filter} days apart from the earliest message group date.")
                                    if not all_messages:
                                        payload = {
                                            'status': 'error',
                                            'status_code': 404,
                                            'data': [],
                                            'message': 'No messages processed.'
                                        }
                                        self._messages_data = payload
                                        return payload
                                    
                                    unique_messages = {msg['message_id']: msg for msg in all_messages}.values()
                                    payload = {
                                        'status': 'success',
                                        'status_code': 200,
                                        'data': sorted(unique_messages, key=lambda x: x['datetime']),
                                        'message': 'Message group age limit reached.'
                                    }
                                    self._messages_data = payload
                                    return payload
                                
                            try:
                                if m['type'] in message_types:
                                    # Determine the role and participants based on message type
                                    role, sender, receiver, last_agent = self._get_message_participants(
                                            message_type=m['type'],
                                            message_model=m['model'],
                                            last_agent=last_agent
                                        )
                                        
                                    base_msg = {
                                    'datetime': datetime.fromtimestamp(m['timestamp']).astimezone(manila_tz).strftime('%Y-%m-%d %H:%M:%S'),
                                    'type' : m['type'],
                                    'user_id' : str(self.user_id),
                                    'user_name' : str(self.user_name),
                                    'sender' : sender,
                                    'receiver' : receiver,
                                    'role' : role,
                                    'message_id': m['message_id'],
                                    'content' : m['model'],
                                    }

                                    all_messages.append(base_msg)
                                    if per_message_sleep_s:
                                        time.sleep(max(0.0, float(per_message_sleep_s)))

                            except Exception as e:
                                logger.error(f"Error processing message {m['message_id']}: {str(e)}")
                                continue

                            if limit:
                                if len(all_messages) >= limit:
                                    logger.debug('Limit reached')
                                    unique_messages = {msg['message_id']: msg for msg in all_messages}.values()
                                    
                                    self._messages_data = {
                                        'status' : 'success',
                                        'status_code' : 200,
                                        'message' : f'Successfully loaded {len(unique_messages)} messages.',
                                        'data' : sorted(unique_messages, key = lambda x: x['datetime']),  
                                    }
                                    return self._messages_data
                                
                        if (not r.get('limiter', None)):
                            logger.debug('No more messages to load.')
                            if not all_messages:
                                return {
                                    'status' : 'error',
                                    'status_code' : 404,
                                    'data' : [],
                                    'message' : 'No messages processed.'
                                }
                            unique_messages = {msg['message_id']: msg for msg in all_messages}.values()
                            payload = {
                                'status': 'success',
                                'status_code': 200,
                                'message': f'Successfully loaded {len(unique_messages)} messages.',
                                'data': sorted(unique_messages, key=lambda x: x['datetime']),
                            }
                            self._messages_data = payload 
                            return payload
                        
        except Exception as e:
            return self._handle_error(e, 'load messages')

    def _create_message_id(self,
                          user_id: Optional[str] = None) -> str:
        s = str(user_id if user_id else self.user_id)
        h = hashlib.sha1(s.encode()).hexdigest()           # stable hash
        return f"{int(h, 16) % 10**11:011d}"

    def _revise_agent_history(self,
                              hist : dict[str, str],
                              agent_messages: dict[str, str]) -> dict:
        new_hist = {}

        # Ensure hist and its 'content' are dicts to avoid AttributeError when accessing .get
        if not isinstance(hist, dict):
            hist = {}
        content = hist.get('content') or {}
        if not isinstance(content, dict):
            content = {}

        new_hist['assigned_datetime'] = hist.get('datetime')
        new_hist['agent_assigned'] = content.get('to_user_name')
        new_hist['agent_last_sender_datetime'] = None
        new_hist['agent_last_sender'] = None
        new_hist['previous_agent_assigned'] = content.get('from_user_name')
        new_hist['type'] = hist.get('type')
        new_hist['message_id'] = hist.get('message_id')
        new_hist['updated_datetime'] = datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S")

        return new_hist

    def get_agent_data(self,
                       timeout : Optional[int] = DEFAULT_TIMEOUT,
                       message_age: Optional[int] = None,
                       limit: Optional[int] = None) -> dict:
        """Return agent assignment + last agent sender using existing messages when possible.

        Uses self._messages_data if it already contains the required types; otherwise
        loads only the minimal types needed ('assign', 'reassign', 'msgout_lc').
        message_age/limit let us avoid crawling the full history (defaults: 45 days, 200 msgs)."""
        def _parse_dt(s: Optional[str]) -> Optional[datetime]:
            if not s:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

        try:
            if getattr(self, "agent_data", None):
                return {
                    "status": "success",
                    "status_code": 200,
                    "data": self.agent_data,
                    "message": "Successfully fetched agent data (cached).",
                }
            
            # Prefer existing messages if they already include what we need
            required = {'assign', 'reassign', 'msgout_lc',
                        'msgout_lc_tiktok', 'msgout_api',
                        'msgout_api_tiktok', 'msgout_lc_instagram',
                        'msgout_api_instagram'}

            messages_data = None
            if isinstance(self._messages_data, dict) and self._messages_data.get("status") == "success":
                have_types = {m.get("type") for m in (self._messages_data.get("data") or [])}
                if have_types & required:
                    logger.debug("Using cached messages for agent data of %s", self.user_name or self.user_id)
                    messages_data = self._messages_data

            if messages_data is None:
                logger.debug(
                    "Fetching messages for agent data of %s (age=%s days, limit=%s, timeout=%s)",
                    self.user_name or self.user_id,
                    message_age if message_age is not None else AGENT_DATA_MESSAGE_AGE,
                    limit if limit is not None else AGENT_DATA_LIMIT,
                    timeout if timeout else self.DEFAULT_TIMEOUT,
                )
                messages_data = self.load_messages(
                    message_age_filter=message_age if message_age is not None else AGENT_DATA_MESSAGE_AGE,
                    timeout=timeout if timeout else self.DEFAULT_TIMEOUT,
                    message_types=list(required),
                    limit=limit if limit is not None else AGENT_DATA_LIMIT,
                )
    
            if messages_data.get("status") != "success":
                msg = messages_data.get("message", "Failed to load messages")
                if "No messages processed" in str(msg):
                    logger.debug("No agent messages found for %s; returning empty agent data", self.user_name)
                    self.agent_data = {
                        "agent_assigned": None,
                        "assigned_datetime": None,
                        "agent_last_sender": None,
                        "agent_last_sender_datetime": None,
                        "history": [],
                    }
                    return {
                        "status": "success",
                        "status_code": 200,
                        "data": self.agent_data,
                        "message": "No agent messages; returning empty agent data.",
                    }
                return self._handle_error(
                    RuntimeError(msg),
                    "fetching agent data",
                )
            self._messages_data = messages_data

            # Process
            data_list = messages_data.get('data') or []

            # All assignment events (latest first)
            assignments = sorted(
                (m for m in data_list if m.get("type") in ("assign", "reassign")),
                key=lambda x: (x.get("datetime") or "", x.get("message_id") or ""),
                reverse=False,
            )

            # All agent outbound messages (latest first)
            agent_msgs = sorted(
                (m for m in data_list if m.get("type") in ["msgout_lc", "msgout_lc_tiktok",
                                                           "msgout_api", "msgout_api_tiktok"]),
                key=lambda x: (x.get("datetime") or "", x.get("message_id") or ""),
                reverse=False,
            )

            def _pick_sender(start_dt: Optional[datetime],
                 end_dt: Optional[datetime] = None) -> tuple[Optional[str], Optional[str]]:
                """
                Return (sender, datetime_str) of the last agent outbound within [start_dt, end_dt).
                If none exists inside the window, return the most recent agent message *before* start_dt.
                Scans oldest->newest.
                """
                last_in_window: Optional[tuple[str, str]] = None
                prior_candidate: Optional[tuple[str, str]] = None  # most recent before start_dt
                end_dt = end_dt if end_dt != start_dt else None

                for m in agent_msgs:  # oldest-first scan (ASC by datetime)
                    md = _parse_dt(m.get("datetime"))
                    if md is None:
                        continue

                    # If we've reached or passed end_dt, future items are also >= end_dt (ASC), so stop.
                    if end_dt and md >= end_dt:
                        break

                    # Track the most recent message strictly before start_dt
                    if start_dt and md < start_dt:
                        prior_candidate = (m.get("sender"), m.get("datetime"))
                        continue

                    # Inside the window if md >= start_dt (or start_dt is None) AND md < end_dt (or end_dt is None)
                    in_window = (start_dt is None or md >= start_dt) and (end_dt is None or md < end_dt)
                    if in_window:
                        # Because we're scanning ASC, keep updating; the last assignment will be the latest within the window.
                        last_in_window = (m.get("sender"), m.get("datetime"))

                # Prefer the latest in-window message; otherwise fall back to the most recent prior.
                if last_in_window is not None:
                    return last_in_window
                if prior_candidate is not None:
                    return prior_candidate
                return (None, None)

            history_records: list[dict] = []
            for i, assign in enumerate(assignments):
                assigned_datetime = assign.get("datetime")
                start_dt = _parse_dt(assignments[i-1]['datetime']) if i-1 >= 0 else _parse_dt(assigned_datetime)
                end_dt = _parse_dt(assignments[i+1]['datetime']) if i+1 < len(assignments) else None
                agent_assigned = (assign.get("content") or {}).get("to_user_name")
                previous_agent_assigned = (assign.get("content") or {}).get("from_user_name")

                agent_last_sender, agent_last_sender_datetime = _pick_sender(start_dt,
                                                                             end_dt)

                record = {
                    "updated_datetime": datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S"),
                    "user_id": str(self.user_id),
                    "user_name": self.user_name,
                    "assigned_datetime": assigned_datetime,
                    "agent_assigned": agent_assigned,
                    "previous_agent_assigned": previous_agent_assigned,
                    "agent_last_sender_datetime": agent_last_sender_datetime,
                    "agent_last_sender": agent_last_sender,
                    "type": assign.get("type"),
                    "message_id": assign.get("message_id"),
                }
                history_records.append(record)

            if history_records:
                latest = sorted(history_records, key = lambda x: (x['assigned_datetime'],
                                                                  x['message_id']),
                                reverse = True)[0]
                self.agent_data = {
                    "agent_assigned": latest["agent_assigned"],
                    "assigned_datetime": latest["assigned_datetime"],
                    "agent_last_sender": latest["agent_last_sender"],
                    "agent_last_sender_datetime": latest["agent_last_sender_datetime"],
                    "history": history_records,
                }
            else:
                # No assignments at all → fallback stub
                agent_last_sender, agent_last_sender_datetime = _pick_sender(None)
                self.agent_data = {
                    "agent_assigned": None,
                    "assigned_datetime": None,
                    "agent_last_sender": agent_last_sender,
                    "agent_last_sender_datetime": agent_last_sender_datetime,
                    "history": [
                        {
                            "updated_datetime": datetime.now(manila_tz).strftime("%Y-%m-%d %H:%M:%S"),
                            "user_id": str(self.user_id),
                            "user_name": self.user_name,
                            "assigned_datetime": None,
                            "agent_assigned": None,
                            "previous_agent_assigned": None,
                            "agent_last_sender_datetime": agent_last_sender_datetime,
                            "agent_last_sender": agent_last_sender,
                            "type": "unassigned",
                            "message_id": f"derived:{(agent_last_sender_datetime or 'NA')}:{(agent_last_sender or 'NA')}",
                        }
                    ],
                }

            return {
                "status": "success",
                "status_code": 200,
                "data": self.agent_data,
                "message": "Successfully built agent snapshot.",
            }
            
        except Exception as e:
            return self._handle_error(e, "fetching agent data")
    
    def get_tags_data(self,
                      message_age : Optional[int] = DEFAULT_MESSAGE_AGE,
                      timeout : Optional[int] = DEFAULT_TIMEOUT) -> dict:
        """
        Get the tags for the user.
        
        Returns:
            dict: A dictionary containing the tags.
        """
        try:
            missing = self._require_user_id()
            if missing:
                return missing
            if getattr(self, "tags_data", None):
                return {
                    "status": "success",
                    "status_code": 200,
                    "data": self.tags_data,
                    "message": "Successfully fetched tags data (cached).",
                }
            
            required = {'tag_added', 'tag_removed'} 
            
            messages_data = self.load_messages(
                message_age_filter=message_age,
                timeout=timeout if timeout else self.DEFAULT_TIMEOUT,
                message_types=list(required),
            )
                
            if messages_data.get("status") != "success":
                return self._handle_error(
                    RuntimeError(messages_data.get("message", "Failed to load messages")),
                    "fetching tags data",
                )
            self._messages_data = messages_data
            
            tags_messages = messages_data.get('data') or []
            if tags_messages:
                self.tags_data = sorted(tags_messages, key = lambda x: x['datetime'], reverse = True)
            
                return {'status' : 'success',
                        'status_code' : 200,
                        'data' : self.tags_data,
                        'message' : 'Successfully fetched tags data.'}
            
            return {'status' : 'success',
                    'status_code' : 200,
                    'data' : None,
                    'message' : 'No tags data found.'}

        
        except Exception as e:
            return self._handle_error(e, 'fetching tags data')
    
    def get_cfs_data(self,
                     message_age : Optional[int] = DEFAULT_MESSAGE_AGE,
                     timeout : Optional[int] = DEFAULT_TIMEOUT
                    ) -> dict:
        """
        Get the custom fields for the user.
        
        Returns:
            dict: A dictionary containing the custom fields.
        """

        try:
            missing = self._require_user_id()
            if missing:
                return missing
            if getattr(self, "cfs_data", None):
                return {
                    "status": "success",
                    "status_code": 200,
                    "data": self.cfs_data,
                    "message": "Successfully fetched cfs data (cached).",
                }
            
            required = {'user_cuf_set'}
      
            messages_data = self.load_messages(
                message_age_filter=message_age,
                timeout=timeout if timeout else self.DEFAULT_TIMEOUT,
                message_types=list(required),
            )
                
            if messages_data.get("status") != "success":
                return self._handle_error(
                    RuntimeError(messages_data.get("message", "Failed to load messages")),
                    "fetching cfs data",
                )
            self._messages_data = messages_data

            cfs_messages = messages_data.get('data') or []
            if cfs_messages:
                self.cfs_data = sorted(cfs_messages, key = lambda x: x['datetime'], reverse = True)

                return {'status' : 'success',
                        'status_code' : 200,
                        'data' : self.cfs_data,
                        'message' : 'Successfully fetched custom fields data.'}
            
            return {'status' : 'success',
                        'status_code' : 200,
                        'data' : None,
                        'message' : 'No custom fields data found.'}
        
        except Exception as e:
            return self._handle_error(e, 'fetching custom fields data')
        
    def set_cf_by_name(self,
                        field_name: str,
                        field_value: Union[str, int, bool]) -> dict:
        """
        Set a custom field for the user by name.
        
        Args:
            field_name (str): The name of the custom field to set.
            field_value (Union[str, int, bool]): The value to set for the custom field.
        """

        try:
            missing = self._require_user_id()
            if missing:
                return missing
                         
            params = {
                'subscriber_id': self.user_id,
                'field_name': field_name,
                'field_value': field_value,
            }

            response = requests.post(f"{self._api_base_url}/subscriber/setCustomFieldByName",
                                        json = params,
                                        headers = self._api_headers)
            if response.status_code != 200:
                error_response = {
                    'text': response.text,
                    'status_code': response.status_code
                }
                raise Exception(str(error_response))
                
            return {"status" : "success",
                    "status_code" : response.status_code,
                    "message" : f"Successfully set custom field '{field_name}' for user {self.user_id}.",
                    "data": response.json()}
        
        except Exception as e:
            return self._handle_error(e, 'setting custom field by name')
        
    def update_tokens(self, add_tokens: int = 0) -> dict:
        """
        Increment the 'tokens' custom field by the provided amount (can be negative).
        Safely defaults to 0 if field missing.
        """
        try:
            user_info = self.get_user_info()
            if user_info.get("status") != "success":
                return user_info
            cfs = (user_info.get("data") or {}).get("custom_fields", []) or []
            tokens_list = [cf.get("value") for cf in cfs if cf.get("name") == "tokens"]
            tokens = tokens_list[0] if tokens_list else 0
            new_tokens = (tokens or 0) + add_tokens
            return self.set_cf_by_name("tokens", new_tokens)
        except Exception as e:
            return self._handle_error(e, "updating tokens")

def test_func():

    def _parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    mcutils = ManychatUtils(user_name =  "Noel Compuesto Lasconia",
                           user_id = "4429026440471414"
    )
    timeout = 60
    # Prefer existing messages if they already include what we need
    required = {'tag_added', 'tag_removed'} 
    messages_data = None

    # Reuse existing messages if possible
    if isinstance(mcutils._messages_data, dict) and mcutils._messages_data.get("status") == "success":
        have_types = {m.get("type") for m in (mcutils._messages_data.get("data") or [])}
        if required & have_types:
            messages_data = mcutils._messages_data

    if messages_data is None:
        messages_data = mcutils.load_messages(
            message_age_filter=60,
            timeout=timeout if timeout else mcutils.DEFAULT_TIMEOUT,
            message_types=list(required),
        )
        mcutils._messages_data = messages_data

    
