

import logging
import json

logger = logging.getLogger(__name__)
import requests


def get_andreani_config(instance):
    return instance.andreani_base_url, instance.andreani_key


def login(instance):
    andreani_base_url, andreani_key = get_andreani_config(instance)
    if not andreani_key:
        return None
    # Implement the logic to login to Andreani using the andreani_key
    # This is a placeholder for the actual API call or logic
    session = f"Session for Andreani key: {andreani_key}"
    headers = {
        "Authorization": f"{andreani_key}",
        "Content-Type": "application/json"
    }
    response = requests.post(
        f"{andreani_base_url}/api/v1/login",
        headers=headers
    )
    if response.status_code != 200:
        return None
    session = response.json().get("response").get("accessToken")
    return session
def get_ticket_from_andreani(instance,trancking_number):
    andreani_base_url, andreani_key = get_andreani_config(instance)
    if not andreani_key:
        return None
    logger.info(f"credentials: {andreani_base_url}")
    # Implement the logic to get the ticket from Andreani using the andreani_key
    # This is a placeholder for the actual API call or logic
    session = login(instance)
    if not session:
        return None
    ticket = f"Ticket for Andreani key: {andreani_key}"
    payload = {
        "trackingNumbers": [trancking_number]
    }
    logger.info(f"andreani request payload: {payload}, base_url: {andreani_base_url}")
    response = requests.request("POST",
        f"{andreani_base_url}/api/v1/Pyme/ticket",
        headers={
            "X-Auth-Token": f"{session}",
            "Content-Type": "application/json"
        },
        data=json.dumps(payload)
    )
    if response.status_code != 200:
        return None
    ticket = response
    logger.info(f"Ticket response: {ticket}")
    
    return ticket