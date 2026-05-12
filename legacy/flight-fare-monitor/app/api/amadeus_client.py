import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

TEST_BASE_URL = "https://test.api.amadeus.com"
PRODUCTION_BASE_URL = "https://api.amadeus.com"


class AmadeusAPIError(RuntimeError):
    pass

class AmadeusClient:

    def __init__(self):
        self.api_key = os.getenv("AMADEUS_API_KEY")
        self.api_secret = os.getenv("AMADEUS_API_SECRET")
        env = os.getenv("AMADEUS_ENV", "test").strip().lower()
        default_base_url = PRODUCTION_BASE_URL if env == "production" else TEST_BASE_URL
        self.base_url = os.getenv("AMADEUS_BASE_URL", default_base_url).rstrip("/")
        self.token_url = f"{self.base_url}/v1/security/oauth2/token"
        self.search_url = f"{self.base_url}/v2/shopping/flight-offers"
        self.retries = int(os.getenv("AMADEUS_RETRIES", "2"))
        if not self.api_key or not self.api_secret:
            raise ValueError("AMADEUS_API_KEY and AMADEUS_API_SECRET must be set in your .env file.")

    def get_access_token(self) -> str:
        try:
            response = requests.post(
                self.token_url,
                data={"grant_type": "client_credentials", "client_id": self.api_key, "client_secret": self.api_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        except requests.exceptions.ConnectionError:
            raise ConnectionError("Could not reach Amadeus. Check your internet connection.")
        except requests.exceptions.Timeout:
            raise TimeoutError("Amadeus auth request timed out.")
        if response.status_code != 200:
            raise RuntimeError(f"Auth failed ({response.status_code}): {response.text}")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("Auth response did not contain an access_token.")
        return token

    def search_flights(self, origin, destination, departure_date, adults=1, travel_class="ECONOMY", currency_code="GBP", non_stop=False, max_offers=10) -> list[dict]:
        token = self.get_access_token()
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "travelClass": travel_class,
            "currencyCode": currency_code,
            "nonStop": str(non_stop).lower(),
            "max": max_offers,
        }
        response = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.get(
                    self.search_url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=15,
                )
            except requests.exceptions.ConnectionError:
                raise ConnectionError("Could not reach Amadeus search API.")
            except requests.exceptions.Timeout:
                if attempt >= self.retries:
                    raise TimeoutError("Flight search request timed out.")
                time.sleep(1 + attempt)
                continue

            if response.status_code not in {500, 502, 503, 504} or attempt >= self.retries:
                break
            time.sleep(1 + attempt)

        if response.status_code != 200:
            raise AmadeusAPIError(self._format_error(response))
        return response.json().get("data", [])

    def _format_error(self, response: requests.Response) -> str:
        hint = ""
        try:
            error = response.json().get("errors", [{}])[0]
        except ValueError:
            error = {}

        code = str(error.get("code", ""))
        title = error.get("title")
        detail = error.get("detail")

        if response.status_code >= 500:
            hint = (
                " Amadeus returned a server-side error. If this happens on the test API, "
                "retry later or set AMADEUS_ENV=production with production Amadeus credentials."
            )

        parts = [f"Search failed ({response.status_code})"]
        if code:
            parts.append(f"code={code}")
        if title:
            parts.append(f"title={title}")
        if detail:
            parts.append(f"detail={detail}")
        return "; ".join(parts) + hint

if __name__ == "__main__":
    try:
        client = AmadeusClient()
        token = client.get_access_token()
        print("Authentication successful.")
        print(f"Token: {token[:20]}...")
    except Exception as e:
        print(f"Error: {e}")
