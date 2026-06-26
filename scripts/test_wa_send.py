"""Quick WhatsApp send test — usage: python scripts/test_wa_send.py [to_number]"""
import asyncio
import sys

import httpx

from app.config.settings import settings


async def main() -> None:
    to = sys.argv[1] if len(sys.argv) > 1 else "0000000000"
    pid = settings.whatsapp_phone_number_id
    url = f"https://graph.facebook.com/v25.0/{pid}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": "Test ping from agent"},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers=headers, json=payload)
        print("status", r.status_code)
        print(r.text[:500])


if __name__ == "__main__":
    asyncio.run(main())
