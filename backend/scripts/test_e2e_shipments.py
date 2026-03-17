"""E2E test: create orders via checkout, create shipments, verify at providers."""
import asyncio
import secrets
import uuid
import httpx

API_BASE = "https://api.vkus.online/api/v1"
ADMIN_TOKEN = "s7Uja7F9cZTe-jCdrCrVfI8vfwlpJSBw5t4AhC5_Aug"

MAGNIT_PVZ_KEY = "63553"
MAGNIT_PVZ_NAME = "МСК 1"
FIVEPOST_PVZ_ID = "010f66ee-65cf-47d5-988d-9b20b2a43b95"
FIVEPOST_PVZ_NAME = "5254 - Пятёрочка"

MAGNIT_BASE = "https://b2b-api.magnit.ru"
MAGNIT_CLIENT_ID = "a3fc5459-781c-47e8-b9c9-b9d6622053ae"
MAGNIT_CLIENT_SECRET = "a6psDoI7cukJRCIG0vHx"

ADMIN_HEADERS = {"Authorization": "Bearer " + ADMIN_TOKEN, "Content-Type": "application/json"}

RESULTS = {}


async def create_guest_session(http):
    """Create a guest session via bootstrap endpoint."""
    session_uuid = str(uuid.uuid4())
    r = await http.post(
        API_BASE + "/guest/session/bootstrap",
        json={"guest_session_id": session_uuid},
        headers={"Content-Type": "application/json"},
    )
    if r.status_code in (200, 201):
        data = r.json().get("data", r.json())
        sid = data.get("guest_session_id", "")
        return sid
    print("  Guest session bootstrap: HTTP " + str(r.status_code) + " " + r.text[:200])
    return None


async def create_order(http, payment_method, delivery_provider, pvz_id, pvz_name, guest_sid):
    """Create an order via checkout API."""
    label = payment_method.upper() + "_" + delivery_provider.upper().replace("5POST", "5POST")
    idem_key = "e2e-test-" + secrets.token_hex(8)
    body = {
        "items": [{"sku": "701", "quantity": 1}],
        "customer_email": "test-e2e@vkus.online",
        "customer_phone": "+79165640299",
        "customer_name": "Тестов Тест Тестович",
        "delivery_provider": delivery_provider,
        "delivery_city": "Москва",
        "pickup_point_id": pvz_id,
        "pickup_point_name": pvz_name,
        "payment_method": payment_method,
        "delivery_price": 183.0,
        "idempotency_key": idem_key,
    }
    headers = {"X-Guest-Session-ID": guest_sid, "Content-Type": "application/json"}
    r = await http.post(API_BASE + "/guest/checkout/create-order", json=body, headers=headers)
    if r.status_code not in (200, 201):
        print("  FAIL create " + label + ": HTTP " + str(r.status_code) + " " + r.text[:300])
        return None
    data = r.json().get("data", r.json())
    order_number = data.get("order_number", "")
    public_token = data.get("public_token", data.get("guest_order_token", ""))
    order_status = data.get("status", "")
    print("  OK " + label + ": " + order_number + " status=" + order_status)
    RESULTS[label] = {"order_number": order_number, "public_token": public_token, "status": order_status}
    return order_number


async def admin_set_status(http, order_number, new_status):
    """Change order status via admin API."""
    r = await http.post(
        API_BASE + "/admin/orders/" + order_number + "/set-status",
        json={"new_status": new_status},
        headers=ADMIN_HEADERS,
    )
    if r.status_code != 200:
        print("    FAIL set-status " + new_status + ": " + r.text[:300])
        return False
    data = r.json().get("data", {})
    print("    OK set-status -> " + data.get("status", new_status))
    return True


async def confirm_cod(http, public_token):
    """Confirm a COD order via public API."""
    r = await http.post(API_BASE + "/orders/" + public_token + "/confirm")
    if r.status_code != 200:
        print("    FAIL confirm COD: " + r.text[:300])
        return False
    print("    OK confirm COD -> confirmed")
    return True


async def create_shipment(http, order_number):
    """Create shipment via admin API."""
    r = await http.post(
        API_BASE + "/admin/orders/" + order_number + "/create-shipment",
        headers=ADMIN_HEADERS,
    )
    if r.status_code != 200:
        err = r.json().get("error", {}).get("message", r.text[:300])
        print("    FAIL create-shipment: " + err[:200])
        return None
    data = r.json().get("data", {})
    provider_id = data.get("provider_shipment_id", "")
    print("    OK shipment: provider_id=" + provider_id + " size=" + str(data.get("parcel_size", "")))
    return provider_id


async def verify_magnit_order(magnit_http, token, provider_id, label):
    """Verify order exists in Magnit system."""
    r = await magnit_http.get(
        "/api/v2/magnit-post/orders/" + provider_id,
        headers={"Authorization": "Bearer " + token},
    )
    if r.status_code == 200:
        d = r.json()
        print("    VERIFIED in Magnit: tracking=" + str(d.get("tracking_number", "")))
        return True
    else:
        print("    FAIL verify in Magnit: HTTP " + str(r.status_code))
        return False


async def cancel_magnit_order(magnit_http, token, provider_id):
    """Cancel order in Magnit (cleanup)."""
    r = await magnit_http.delete(
        "/api/v1/magnit-post/orders/" + provider_id,
        headers={"Authorization": "Bearer " + token},
    )
    return r.status_code == 204


async def main():
    print("=" * 60)
    print("E2E SHIPMENT TEST")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30) as http:
        # Step 0: Create guest session
        print("\n[0] Creating guest session...")
        guest_sid = await create_guest_session(http)
        if not guest_sid:
            print("  FAIL: could not create guest session, aborting.")
            return
        print("  Session ID: " + guest_sid)

        # Step 1: Create 4 orders
        print("\n[1] Creating orders...")
        orders = []

        for payment, provider, pvz_id, pvz_name in [
            ("card", "magnit", MAGNIT_PVZ_KEY, MAGNIT_PVZ_NAME),
            ("cod", "magnit", MAGNIT_PVZ_KEY, MAGNIT_PVZ_NAME),
            ("card", "5post", FIVEPOST_PVZ_ID, FIVEPOST_PVZ_NAME),
            ("cod", "5post", FIVEPOST_PVZ_ID, FIVEPOST_PVZ_NAME),
        ]:
            on = await create_order(http, payment, provider, pvz_id, pvz_name, guest_sid)
            if on:
                label = payment.upper() + "_" + provider.upper()
                orders.append((label, on))

        if not orders:
            print("\nNo orders created, aborting.")
            return

        # Step 2: Move orders to CONFIRMED
        print("\n[2] Moving orders to CONFIRMED status...")
        for label, order_number in orders:
            info = RESULTS.get(label, {})
            print("  " + label + " (" + order_number + "):")

            if "COD" in label:
                public_token = info.get("public_token", "")
                if public_token:
                    await confirm_cod(http, public_token)
            else:
                # PREPAID: pending_payment -> paid -> confirmed
                await admin_set_status(http, order_number, "paid")
                await admin_set_status(http, order_number, "confirmed")

        # Step 3: Create shipments
        print("\n[3] Creating shipments at providers...")
        magnit_provider_ids = []
        for label, order_number in orders:
            print("  " + label + " (" + order_number + "):")
            provider_id = await create_shipment(http, order_number)
            if provider_id:
                RESULTS[label]["provider_id"] = provider_id
                if "MAGNIT" in label:
                    magnit_provider_ids.append((label, provider_id))

    # Step 4: Verify in Magnit system
    if magnit_provider_ids:
        print("\n[4] Verifying orders in Magnit API...")
        async with httpx.AsyncClient(base_url=MAGNIT_BASE, timeout=60) as magnit_http:
            r = await magnit_http.post("/api/v2/oauth/token", data={
                "client_id": MAGNIT_CLIENT_ID, "client_secret": MAGNIT_CLIENT_SECRET,
                "scope": "openid", "grant_type": "client_credentials"
            }, headers={"Content-Type": "application/x-www-form-urlencoded"})
            magnit_token = r.json()["access_token"]

            for label, pid in magnit_provider_ids:
                print("  " + label + ":")
                await verify_magnit_order(magnit_http, magnit_token, pid, label)

            # Step 5: Cleanup - cancel Magnit orders
            print("\n[5] Cleanup - cancelling Magnit test orders...")
            for label, pid in magnit_provider_ids:
                ok = await cancel_magnit_order(magnit_http, magnit_token, pid)
                print("  Cancel " + label + ": " + ("OK" if ok else "FAIL"))

    # Step 6: Delete test orders from our DB
    print("\n[6] Cleanup - deleting test orders from DB...")
    async with httpx.AsyncClient(timeout=30) as http:
        for label, order_number in orders:
            r = await http.delete(
                API_BASE + "/admin/orders/" + order_number,
                headers=ADMIN_HEADERS,
            )
            result = "OK" if r.status_code == 200 else "FAIL(" + str(r.status_code) + ")"
            print("  Delete " + label + " (" + order_number + "): " + result)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for label in ["CARD_MAGNIT", "COD_MAGNIT", "CARD_5POST", "COD_5POST"]:
        info = RESULTS.get(label, {})
        pid = info.get("provider_id", "")
        if pid:
            print("  " + label + ": PASS (provider_id=" + pid + ")")
        elif info.get("order_number"):
            print("  " + label + ": SHIPMENT_FAILED (order created, shipment rejected)")
        else:
            print("  " + label + ": ORDER_FAILED")


if __name__ == "__main__":
    asyncio.run(main())
