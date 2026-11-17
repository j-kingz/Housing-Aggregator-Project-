from datetime import timedelta

from app.extensions import db
from app.models import Payment, PremiumSubscription, Property, VerificationRequest, utcnow
from app.payments.routes import _finish
from tests.conftest import login, make_user
from tests.test_units import add_unit


def test_premium_subscription_payment_activates_access(app):
    renter = make_user("premium@example.com", "Renter")
    payment = Payment(
        renter_id=renter.user_id,
        amount=500,
        purpose="premium_subscription",
        status="pending",
        simulated=True,
    )
    db.session.add(payment)
    db.session.commit()

    with app.test_request_context():
        _finish(payment, 0, "Payment received.", "PREMIUM123")

    subscription = PremiumSubscription.query.one()
    assert payment.status == "paid"
    assert subscription.renter_id == renter.user_id
    assert subscription.expires_at > utcnow()


def test_premium_request_is_assigned_and_verifier_contact_is_shown(client, app):
    renter = make_user("renter-premium@example.com", "Renter")
    verifier = make_user("checker@example.com", "Landlord")
    verifier.verifier_approved = True
    verifier.verifier_available = True
    verifier.phonenumber = "0712345678"
    subscription = PremiumSubscription(
        renter_id=renter.user_id,
        payment_id=1,
        starts_at=utcnow(),
        expires_at=utcnow() + timedelta(days=30),
    )
    payment = Payment(
        payment_id=1,
        renter_id=renter.user_id,
        amount=500,
        purpose="premium_subscription",
        status="paid",
    )
    unit = add_unit()
    db.session.add(payment)
    db.session.add(subscription)
    db.session.commit()

    login(client, renter.email)
    response = client.post(f"/premium/verify/{unit.listing_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "0712345678" in response.get_data(as_text=True)
    request_row = VerificationRequest.query.one()
    assert request_row.verifier_id == verifier.user_id
    assert request_row.status == "assigned"


def test_scraped_listing_has_no_external_listing_link(client, app):
    listing = add_unit(source_url="https://jiji.co.ke/listing/123", source_name="Jiji")
    response = client.get(f"/listings/{listing.listing_id}")
    assert response.status_code == 200
    assert b"See the original listing" not in response.data
    assert b"jiji.co.ke/listing/123" not in response.data


def test_premium_payment_sends_confirmation_email(app, monkeypatch):
    renter = make_user("premium-email@example.com", "Renter")
    payment = Payment(
        renter_id=renter.user_id,
        amount=500,
        purpose="premium_subscription",
        status="pending",
        simulated=True,
    )
    db.session.add(payment)
    db.session.commit()
    sent = []
    monkeypatch.setattr(
        "app.payments.routes.send_premium_subscription_confirmation",
        lambda user, paid_payment, expires_at: sent.append(
            (user.email, paid_payment.payment_id, expires_at)
        ),
    )

    with app.test_request_context():
        _finish(payment, 0, "Payment received.", "PREMIUM123")

    assert sent[0][0] == renter.email
    assert sent[0][1] == payment.payment_id
    assert payment.status == "paid"


def test_subscribe_page_offers_a_chosen_amount_and_no_demo_button(client):
    renter = make_user("premium-page@example.com", "Renter")
    login(client, renter.email)
    html = client.get("/premium/subscribe").get_data(as_text=True)
    assert 'id="demo_payment"' not in html
    assert 'name="custom_amount"' in html
    assert "An amount of my choice" in html
    assert "+254" in html


def test_a_renter_can_pay_an_amount_of_their_choice_with_mpesa(client, app, monkeypatch):
    from app.payments import mpesa
    app.config.update(MPESA_CONSUMER_KEY="live-key")
    sent = []
    monkeypatch.setattr(mpesa, "stk_push", lambda config, phone, amount, **k: sent.append((phone, amount))
                        or {"checkout_request_id": "ws_CO_P1", "merchant_request_id": "m1"})
    renter = make_user("premium-custom@example.com", "Renter")
    login(client, renter.email)
    response = client.post("/premium/subscribe", data={
        "amount_choice": "custom", "custom_amount": "200", "phone": "712345678"})
    assert response.status_code == 302
    assert sent == [("254712345678", 200)]
    payment = Payment.query.one()
    assert int(payment.amount) == 200
    assert payment.simulated is False
    assert payment.purpose == "premium_subscription"


def test_the_standard_amount_is_used_by_default(client, app, monkeypatch):
    from app.payments import mpesa
    app.config.update(MPESA_CONSUMER_KEY="live-key")
    sent = []
    monkeypatch.setattr(mpesa, "stk_push", lambda config, phone, amount, **k: sent.append(amount)
                        or {"checkout_request_id": "ws_CO_P2", "merchant_request_id": "m2"})
    renter = make_user("premium-standard@example.com", "Renter")
    login(client, renter.email)
    client.post("/premium/subscribe", data={"phone": "0712345678", "custom_amount": "5"})
    assert sent == [app.config["PREMIUM_SUBSCRIPTION_AMOUNT"]]


def test_a_bad_chosen_amount_is_refused(client, app):
    renter = make_user("premium-bad@example.com", "Renter")
    login(client, renter.email)
    for bad in ("0", "abc", "999999"):
        response = client.post("/premium/subscribe", data={
            "amount_choice": "custom", "custom_amount": bad, "phone": "712345678"})
        assert response.status_code == 400
    assert Payment.query.count() == 0


def test_a_demo_request_no_longer_skips_mpesa(client, app, monkeypatch):
    from app.payments import mpesa
    app.config.update(MPESA_CONSUMER_KEY="live-key")
    monkeypatch.setattr(mpesa, "stk_push", lambda *a, **k: {"checkout_request_id": "ws", "merchant_request_id": "m"})
    renter = make_user("premium-nodemo@example.com", "Renter")
    login(client, renter.email)
    client.post("/premium/subscribe", data={"demo_payment": "1", "phone": "712345678"})
    assert Payment.query.one().simulated is False


# -- a check updates the listing, and is never done on your own unit ---------
from scraper.scraper import _merged_availability  # noqa: E402


def _subscribed_renter(email, payment_id):
    renter = make_user(email, "Renter")
    db.session.add(Payment(payment_id=payment_id, renter_id=renter.user_id, amount=500,
                           purpose="premium_subscription", status="paid"))
    db.session.add(PremiumSubscription(renter_id=renter.user_id, payment_id=payment_id,
                                       starts_at=utcnow(),
                                       expires_at=utcnow() + timedelta(days=30)))
    db.session.commit()
    return renter


def _approved_verifier(email, role="Landlord"):
    user = make_user(email, role)
    user.verifier_approved = True
    user.verifier_available = True
    db.session.commit()
    return user


def _assigned_check(verifier, unit, renter_email="asker@example.com"):
    renter = _subscribed_renter(renter_email, 1)
    check = VerificationRequest(renter_id=renter.user_id, listing_id=unit.listing_id,
                                verifier_id=verifier.user_id, status="assigned",
                                assigned_at=utcnow())
    db.session.add(check)
    db.session.commit()
    return check


def _report(client, verifier, check, result, **extra):
    login(client, verifier.email)
    data = {"verified_status": result, "report": "Visited the caretaker.",
            "contact_phone": "+254 712 000 111", **extra}
    return client.post(f"/premium/verifier/{check.request_id}", data=data)


class TestCheckUpdatesTheListing:
    def test_a_vacant_finding_shows_on_the_listing(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        _report(client, verifier, _assigned_check(verifier, unit), "vacant")
        assert db.session.get(Property, unit.listing_id).availability_status == "vacant"

        page = client.get(f"/listings/{unit.listing_id}").get_data(as_text=True)
        assert "Confirmed by an approved checker on" in page

    def test_an_occupied_finding_shows_on_the_listing(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="vacant")
        _report(client, verifier, _assigned_check(verifier, unit), "occupied")
        assert db.session.get(Property, unit.listing_id).availability_status == "occupied"

    def test_only_vacant_or_not_vacant_is_accepted(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        _report(client, verifier, check, "unavailable")
        assert db.session.get(VerificationRequest, check.request_id).status == "assigned"
        assert db.session.get(Property, unit.listing_id).availability_status == "unknown"

    def test_a_report_needs_the_checkers_phone(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        _report(client, verifier, check, "vacant", contact_phone="")
        assert db.session.get(VerificationRequest, check.request_id).status == "assigned"

    def test_the_renter_sees_the_result_and_the_checkers_contact(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        _report(client, verifier, check, "occupied", contact_name="Jane Checker",
                contact_email="jane@example.com")
        saved = db.session.get(VerificationRequest, check.request_id)
        assert saved.verifier_contact_phone == "+254 712 000 111"
        assert saved.result_label == "Not vacant"
        client.post("/logout")
        login(client, "asker@example.com")
        page = client.get(f"/premium/requests/{check.request_id}").get_data(as_text=True)
        assert "NOT VACANT" in page
        assert "Jane Checker" in page
        assert "+254 712 000 111" in page
        assert "jane@example.com" in page
        assert "Visited the caretaker." in page

    def test_reports_are_due_within_24_hours(self, client, app):
        from app.premium import services
        with app.test_request_context():
            assert services.deadline_hours() == 24

    def test_a_reserved_unit_stays_reserved(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="reserved")
        _report(client, verifier, _assigned_check(verifier, unit), "vacant")
        assert db.session.get(Property, unit.listing_id).availability_status == "reserved"

    def test_an_old_check_is_not_shown_once_the_status_changes(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        _report(client, verifier, _assigned_check(verifier, unit), "vacant")
        db.session.get(Property, unit.listing_id).availability_status = "reserved"
        db.session.commit()
        page = client.get(f"/listings/{unit.listing_id}").get_data(as_text=True)
        assert "Confirmed by an approved checker" not in page

    def test_a_report_cannot_be_sent_twice(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        _report(client, verifier, check, "vacant")
        _report(client, verifier, check, "occupied")
        assert db.session.get(VerificationRequest, check.request_id).verified_status == "vacant"
        assert db.session.get(Property, unit.listing_id).availability_status == "vacant"


class TestNoCheckingYourOwnUnit:
    def test_a_landlord_is_never_assigned_their_own_unit(self, client, app):
        landlord = _approved_verifier("owner@example.com")
        unit = add_unit(landlord_id=landlord.user_id, availability_status="unknown")
        renter = _subscribed_renter("renter@example.com", 1)
        login(client, renter.email)
        client.post(f"/premium/verify/{unit.listing_id}")
        assert VerificationRequest.query.count() == 0   # nobody independent is free

        other = _approved_verifier("independent@example.com")
        client.post(f"/premium/verify/{unit.listing_id}")
        assert VerificationRequest.query.one().verifier_id == other.user_id

    def test_a_renter_is_never_assigned_their_own_request(self, client, app):
        renter = _subscribed_renter("renter@example.com", 1)
        renter.verifier_approved = renter.verifier_available = True
        db.session.commit()
        unit = add_unit(availability_status="unknown")
        login(client, renter.email)
        client.post(f"/premium/verify/{unit.listing_id}")
        assert VerificationRequest.query.count() == 0

    def test_a_landlord_cannot_report_on_their_own_unit(self, client, app):
        landlord = _approved_verifier("owner@example.com")
        unit = add_unit(landlord_id=landlord.user_id, availability_status="unknown")
        check = _assigned_check(landlord, unit)   # e.g. assigned before they owned it
        assert _report(client, landlord, check, "vacant").status_code == 403
        assert db.session.get(Property, unit.listing_id).availability_status == "unknown"


class TestScrapingKeepsKnownStatus:
    def test_a_reserved_unit_stays_reserved_after_a_scrape(self):
        assert _merged_availability("reserved", "vacant") == "reserved"
        assert _merged_availability("reserved", "unknown") == "reserved"

    def test_an_advert_that_does_not_say_keeps_the_known_status(self):
        assert _merged_availability("vacant", "unknown") == "vacant"
        assert _merged_availability("occupied", None) == "occupied"

    def test_an_advert_that_does_say_is_used(self):
        assert _merged_availability("vacant", "occupied") == "occupied"
        assert _merged_availability("unknown", "vacant") == "vacant"
        assert _merged_availability(None, "unknown") == "unknown"


# -- deadlines -----------------------------------------------------------------
from datetime import datetime  # noqa: E402

from app.models import Notification  # noqa: E402
from app.premium.services import enforce_deadlines  # noqa: E402


def _overdue(check, minutes=1):
    check.due_at = utcnow() - timedelta(minutes=minutes)
    db.session.commit()
    return check


class TestDeadlines:
    def test_a_new_check_gets_a_deadline(self, client, app):
        _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        renter = _subscribed_renter("renter@example.com", 1)
        login(client, renter.email)
        client.post(f"/premium/verify/{unit.listing_id}")
        check = VerificationRequest.query.one()
        expected = utcnow() + timedelta(hours=24)
        assert abs((check.due_at - expected).total_seconds()) < 60
        page = client.get(f"/premium/requests/{check.request_id}").get_data(as_text=True)
        assert "Report due by" in page and "EAT" in page

    def test_an_overdue_check_goes_to_another_verifier(self, app):
        late = _approved_verifier("late@example.com")
        other = _approved_verifier("other@example.com")
        unit = add_unit(availability_status="unknown")
        check = _overdue(_assigned_check(late, unit))

        assert enforce_deadlines() == {"reassigned": 1, "expired": 0}
        assert check.verifier_id == other.user_id
        assert check.status == "assigned"
        assert check.reassign_count == 1
        assert check.due_at > utcnow() + timedelta(hours=23)
        note = Notification.query.filter_by(renter_id=check.renter_id).one()
        assert "another checker" in note.message
        assert note.url == f"/premium/requests/{check.request_id}"

    def test_with_nobody_else_free_the_check_expires(self, client, app):
        late = _approved_verifier("late@example.com")
        unit = add_unit(availability_status="unknown")
        check = _overdue(_assigned_check(late, unit))

        assert enforce_deadlines() == {"reassigned": 0, "expired": 1}
        assert check.status == "expired"
        assert "closed" in Notification.query.one().message

        # the renter can ask again, and is told so
        login(client, "asker@example.com")
        page = client.get(f"/premium/requests/{check.request_id}").get_data(as_text=True)
        assert "Request a new check" in page

    def test_a_check_is_passed_on_at_most_the_configured_times(self, app):
        first = _approved_verifier("first@example.com")
        _approved_verifier("second@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(first, unit)
        app.config["VERIFICATION_MAX_REASSIGNMENTS"] = 2

        _overdue(check)
        enforce_deadlines()
        _overdue(check)
        enforce_deadlines()
        assert check.reassign_count == 2 and check.status == "assigned"

        _overdue(check)
        enforce_deadlines()
        assert check.status == "expired"

    def test_a_check_on_time_is_left_alone(self, app):
        verifier = _approved_verifier("checker@example.com")
        _approved_verifier("other@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        check.due_at = utcnow() + timedelta(hours=1)
        db.session.commit()
        assert enforce_deadlines() == {"reassigned": 0, "expired": 0}
        assert check.verifier_id == verifier.user_id

    def test_an_older_check_without_a_deadline_gets_one(self, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        check.due_at = None
        check.assigned_at = utcnow() - timedelta(hours=50)   # before deadlines existed
        db.session.commit()
        enforce_deadlines()
        assert check.status == "expired"

    def test_a_late_report_is_refused(self, client, app):
        late = _approved_verifier("late@example.com")
        other = _approved_verifier("other@example.com")
        unit = add_unit(availability_status="unknown")
        check = _overdue(_assigned_check(late, unit))

        response = _report(client, late, check, "vacant")
        assert response.status_code == 302
        assert check.verifier_id == other.user_id and check.status == "assigned"
        assert db.session.get(Property, unit.listing_id).availability_status == "unknown"
        page = client.get("/premium/verifier").get_data(as_text=True)
        assert "deadline for that check passed" in page

    def test_the_verifier_queue_shows_the_deadline(self, client, app):
        verifier = _approved_verifier("checker@example.com")
        unit = add_unit(availability_status="unknown")
        check = _assigned_check(verifier, unit)
        check.due_at = datetime(2030, 1, 5, 9, 30)   # 09:30 UTC
        db.session.commit()
        login(client, verifier.email)
        page = client.get("/premium/verifier").get_data(as_text=True)
        assert "Due 05 Jan 2030, 12:30 EAT" in page   # shown in Kenya time
