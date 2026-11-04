"""Tests for the M-Pesa reservation flow (demo mode and the callback)."""

from datetime import timedelta

from app.extensions import db
from app.models import Payment, Property, utcnow
from app.payments import mpesa
from tests.conftest import login, make_user
from tests.test_units import add_unit


class TestPhoneNumbers:
    def test_local_formats_are_normalised(self):
        assert mpesa.normalise_phone("0712 345 678") == "254712345678"
        assert mpesa.normalise_phone("+254 712-345-678") == "254712345678"
        assert mpesa.normalise_phone("712345678") == "254712345678"
        assert mpesa.normalise_phone("0112345678") == "254112345678"

    def test_bad_numbers_are_refused(self):
        assert mpesa.normalise_phone("12345") is None
        assert mpesa.normalise_phone("0612345678") is None
        assert mpesa.normalise_phone("") is None


def start_payment(client, unit, phone="0712345678"):
    return client.post(f"/payments/pay/{unit.listing_id}", data={"phone": phone})


class TestDemoPayment:
    def test_the_page_says_it_is_demo_mode(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        assert "Demo mode" in client.get(f"/payments/pay/{unit.listing_id}").get_data(as_text=True)

    def test_a_deposit_is_ten_percent_of_the_rent(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A", rentamount=60000)
        start_payment(client, unit)
        payment = Payment.query.one()
        assert float(payment.amount) == 6000
        assert payment.status == "pending"
        assert payment.phone == "254712345678"
        assert payment.simulated is True

    def test_an_invalid_number_creates_no_payment(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        response = start_payment(client, unit, phone="123")
        assert response.status_code == 400
        assert Payment.query.count() == 0

    def test_the_payment_is_confirmed_and_the_unit_reserved(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        start_payment(client, unit)
        payment = Payment.query.one()

        # not yet: the demo waits a few seconds
        assert client.get(f"/payments/{payment.payment_id}/status.json").get_json()["status"] == "pending"

        payment.created_at = utcnow() - timedelta(seconds=30)
        db.session.commit()
        data = client.get(f"/payments/{payment.payment_id}/status.json").get_json()

        assert data["status"] == "paid"
        assert data["receipt"].startswith("DEMO")
        assert db.session.get(Property, unit.listing_id).availability_status == "reserved"

    def test_a_paid_reservation_sends_one_confirmation_email(self, client, app, areas, monkeypatch):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        sent = []
        monkeypatch.setattr(
            "app.payments.routes.send_reservation_confirmation",
            lambda payment: sent.append(payment.payment_id),
        )

        start_payment(client, unit)
        payment = Payment.query.one()
        payment.created_at = utcnow() - timedelta(seconds=30)
        db.session.commit()
        client.get(f"/payments/{payment.payment_id}/status.json")
        client.get(f"/payments/{payment.payment_id}/status.json")

        assert sent == [payment.payment_id]
        assert db.session.get(Payment, payment.payment_id).confirmation_email_sent_at is not None

    def test_a_reserved_unit_cannot_be_paid_for_again(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A", availability_status="reserved")
        response = client.get(f"/payments/pay/{unit.listing_id}", follow_redirects=True)
        assert "no longer open" in response.get_data(as_text=True)
        assert Payment.query.count() == 0

    def test_landlords_cannot_pay(self, client, app, areas):
        make_user("l@example.com", "Landlord")
        login(client, "l@example.com")
        unit = add_unit(room_number="1A")
        start_payment(client, unit)
        assert Payment.query.count() == 0

    def test_someone_else_cannot_read_my_payment(self, client, app, areas):
        make_user("r@example.com", "Renter")
        make_user("other@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        start_payment(client, unit)
        payment_id = Payment.query.one().payment_id
        client.post("/logout")
        login(client, "other@example.com")
        assert client.get(f"/payments/{payment_id}").status_code == 403

    def test_the_landlord_sees_the_payment_for_their_unit(self, client, app, areas):
        renter = make_user("r@example.com", "Renter")
        landlord = make_user("l@example.com", "Landlord")
        unit = add_unit(landlord_id=landlord.user_id, room_number="1A")
        login(client, "r@example.com")
        start_payment(client, unit)
        client.post("/logout")
        login(client, "l@example.com")
        assert "Riverside Towers" in client.get("/payments/").get_data(as_text=True)


class TestCallback:
    def make_pending(self, client, app):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A", rentamount=50000)
        payment = Payment(
            renter_id=db.session.execute(db.text("select min(renter_id) from renter_details")).scalar(),
            listing_id=unit.listing_id, amount=5000, status="pending", phone="254712345678",
            checkout_request_id="ws_CO_123", simulated=False,
        )
        db.session.add(payment)
        db.session.commit()
        return payment, unit

    def body(self, code=0, amount=5000):
        stk = {"MerchantRequestID": "m1", "CheckoutRequestID": "ws_CO_123",
               "ResultCode": code, "ResultDesc": "The service request is processed successfully."}
        if code == 0:
            stk["CallbackMetadata"] = {"Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": "QGH7XYZ123"},
                {"Name": "PhoneNumber", "Value": 254712345678},
            ]}
        return {"Body": {"stkCallback": stk}}

    def url(self, app):
        return f"/payments/mpesa/callback/{mpesa.callback_token(app.config)}"

    def test_a_successful_callback_marks_the_payment_paid(self, client, app, areas):
        payment, unit = self.make_pending(client, app)
        response = client.post(self.url(app), json=self.body())
        assert response.get_json()["ResultCode"] == 0
        db.session.refresh(payment)
        assert payment.status == "paid"
        assert payment.mpesa_receipt == "QGH7XYZ123"
        assert db.session.get(Property, unit.listing_id).availability_status == "reserved"

    def test_a_cancelled_prompt_is_recorded(self, client, app, areas):
        payment, unit = self.make_pending(client, app)
        client.post(self.url(app), json=self.body(code=1032))
        db.session.refresh(payment)
        assert payment.status == "cancelled"
        assert db.session.get(Property, unit.listing_id).availability_status == "vacant"

    def test_a_forged_callback_without_the_secret_is_rejected(self, client, app, areas):
        payment, unit = self.make_pending(client, app)
        assert client.post("/payments/mpesa/callback/not-the-secret", json=self.body()).status_code == 404
        db.session.refresh(payment)
        assert payment.status == "pending"

    def test_an_underpayment_does_not_reserve_the_unit(self, client, app, areas):
        payment, unit = self.make_pending(client, app)
        client.post(self.url(app), json=self.body(amount=10))
        db.session.refresh(payment)
        assert payment.status == "failed"
        assert db.session.get(Property, unit.listing_id).availability_status == "vacant"

    def test_a_repeated_callback_changes_nothing(self, client, app, areas):
        payment, unit = self.make_pending(client, app)
        client.post(self.url(app), json=self.body())
        client.post(self.url(app), json=self.body(code=1032))
        db.session.refresh(payment)
        assert payment.status == "paid"

    def test_garbage_is_accepted_quietly(self, client, app, areas):
        response = client.post(self.url(app), json={"hello": "world"})
        assert response.get_json()["ResultCode"] == 0


class TestProofEmail:
    def _paid(self, client):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        start_payment(client, unit)
        payment = Payment.query.one()
        payment.created_at = utcnow() - timedelta(seconds=30)
        db.session.commit()
        client.get(f"/payments/{payment.payment_id}/status.json")
        return payment

    def test_the_email_is_a_receipt_with_the_unit_and_receipt(self, client, app, areas, monkeypatch):
        sent = []
        monkeypatch.setattr("app.email.deliver", lambda message, config=None: sent.append(message))
        app.config.update(SMTP_HOST="smtp.example.com", MAIL_SENDER="noreply@example.com")
        payment = self._paid(client)

        assert len(sent) == 1
        message = sent[0]
        assert message["To"] == "r@example.com"
        text = message.get_body(("plain",)).get_content()
        assert db.session.get(Payment, payment.payment_id).mpesa_receipt in text
        assert "1A" in text
        assert message.get_body(("html",)) is not None

    def test_the_renter_can_ask_for_the_proof_again(self, client, app, areas, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "app.payments.routes.send_reservation_confirmation",
            lambda payment: sent.append(payment.payment_id),
        )
        payment = self._paid(client)
        response = client.post(f"/payments/{payment.payment_id}/resend-email", follow_redirects=True)

        assert sent == [payment.payment_id, payment.payment_id]
        assert "was sent to r@example.com" in response.get_data(as_text=True)

    def test_without_smtp_the_reason_is_recorded(self, client, app, areas):
        app.config.update(SMTP_HOST="", MAIL_SENDER="")
        payment = self._paid(client)
        assert "not configured" in db.session.get(Payment, payment.payment_id).confirmation_email_error


class TestCustomAmount:
    def test_a_renter_can_pay_an_amount_of_their_choice(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        client.post(f"/payments/pay/{unit.listing_id}", data={
            "phone": "0712345678", "amount_choice": "custom", "custom_amount": "1",
        })
        payment = Payment.query.one()
        assert float(payment.amount) == 1
        assert payment.is_custom_amount

        page = client.get(f"/payments/{payment.payment_id}").get_data(as_text=True)
        assert "not the real reservation price" in page

    def test_the_pay_page_explains_the_custom_amount(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        page = client.get(f"/payments/pay/{unit.listing_id}").get_data(as_text=True)
        assert "This is not the real reservation price yet" in page

    def test_a_bad_amount_is_refused(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        for bad in ("0", "abc", "300000"):
            response = client.post(f"/payments/pay/{unit.listing_id}", data={
                "phone": "0712345678", "amount_choice": "custom", "custom_amount": bad,
            })
            assert response.status_code == 400
        assert Payment.query.count() == 0

    def test_the_proof_can_go_to_another_email(self, client, app, areas, monkeypatch):
        sent = []
        monkeypatch.setattr("app.email.deliver", lambda message, config=None: sent.append(message))
        app.config.update(SMTP_HOST="smtp.example.com", MAIL_SENDER="noreply@example.com")
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        client.post(f"/payments/pay/{unit.listing_id}", data={
            "phone": "0712345678", "amount_choice": "custom", "custom_amount": "5",
            "receipt_email": "someone@gmail.com, other@gmail.com; R@example.com",
        })
        payment = Payment.query.one()
        payment.created_at = utcnow() - timedelta(seconds=30)
        db.session.commit()
        client.get(f"/payments/{payment.payment_id}/status.json")

        # the account's own email always comes first, and no address is repeated
        assert sent[0]["To"] == "r@example.com, someone@gmail.com, other@gmail.com"
        assert "not the real reservation price" in sent[0].get_body(("plain",)).get_content()

    def test_a_bad_extra_email_is_refused(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit(room_number="1A")
        response = client.post(f"/payments/pay/{unit.listing_id}", data={
            "phone": "0712345678", "receipt_email": "good@gmail.com, not-an-email",
        })
        assert response.status_code == 400
        assert Payment.query.count() == 0


class TestDarajaSettings:
    def test_the_callback_is_always_https(self):
        config = {"SECRET_KEY": "x", "MPESA_CALLBACK_BASE_URL": ""}
        assert mpesa.callback_url(config).startswith("https://")
        config["MPESA_CALLBACK_BASE_URL"] = "https://abc.ngrok-free.app"
        assert mpesa.callback_url(config).startswith(
            "https://abc.ngrok-free.app/payments/mpesa/callback/"
        )

    def test_the_sandbox_passkey_is_used_when_none_is_set(self):
        assert mpesa._passkey({"MPESA_ENV": "sandbox", "MPESA_PASSKEY": ""}) == mpesa.SANDBOX_PASSKEY
        assert mpesa._passkey({"MPESA_ENV": "production", "MPESA_PASSKEY": ""}) == ""
        assert mpesa._passkey({"MPESA_ENV": "sandbox", "MPESA_PASSKEY": "mine"}) == "mine"

    def test_the_stk_push_matches_the_daraja_request(self, monkeypatch):
        captured = {}

        def fake_post(config, path, payload):
            captured.update(path=path, payload=payload)
            return {"ResponseCode": "0", "MerchantRequestID": "M1", "CheckoutRequestID": "C1"}

        monkeypatch.setattr(mpesa, "_post", fake_post)
        config = {"SECRET_KEY": "x", "MPESA_SHORTCODE": "174379", "MPESA_ENV": "sandbox"}
        result = mpesa.stk_push(config, "254708374149", 1.0, "UNIT1", "Reservation")

        assert result == {"merchant_request_id": "M1", "checkout_request_id": "C1"}
        assert captured["path"] == "/mpesa/stkpush/v1/processrequest"
        body = captured["payload"]
        assert body["TransactionType"] == "CustomerPayBillOnline"
        assert body["PartyA"] == body["PhoneNumber"] == "254708374149"
        assert body["PartyB"] == body["BusinessShortCode"] == "174379"
        assert body["Amount"] == 1
        assert body["CallBackURL"].startswith("https://")
