import os
from datetime import datetime, timedelta

import pytest

from web.flask_server import app, hash_password, verify_password, check_password_strength
from database import db, User, ShortLink, generate_available_short_link

_db_initialised = False

@pytest.fixture
def test_app():
    global _db_initialised
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    if not _db_initialised:
        db.init_app(app)
        _db_initialised = True

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(test_app):
    return test_app.test_client()

@pytest.fixture
def sample_user(test_app):
    with test_app.app_context():
        user = User(
            id=os.urandom(32).hex(),
            username="testuser",
            password_hash=hash_password("Test1234!"),
            is_admin=False,
            is_active_field=True,
            password_change_needed=False
        )
        db.session.add(user)
        db.session.commit()
        return user.id, "testuser", "Test1234!"

@pytest.fixture
def admin_user(test_app):
    with test_app.app_context():
        user = User(
            id=os.urandom(32).hex(),
            username="admin",
            password_hash=hash_password("Admin1234!"),
            is_admin=True,
            is_active_field=True,
            password_change_needed=False
        )
        db.session.add(user)
        db.session.commit()
        return user.id, "admin", "Admin1234!"

@pytest.fixture
def sample_link(test_app, sample_user):
    user_id, _, _ = sample_user
    with test_app.app_context():
        link = ShortLink(
            short_link="test01",
            redirect_url="https://example.com",
            user_uuid=user_id,
            created_at=int(datetime.now().timestamp()),
            clicks=0,
            max_clicks=0,
            expires_at=None,
            is_active=True
        )
        db.session.add(link)
        db.session.commit()
        return link.short_link


def login(client, username, password):
    return client.post("/login",
                       data={
                           "username": username,
                           "password": password
                       }, follow_redirects=True)


# Test models

class TestUserModel:
    def test_create_user(self, test_app):
        with test_app.app_context():
            user = User(
                id="test123",
                username="newuser",
                password_hash=hash_password("Pass1234!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(user)
            db.session.commit()

            fetched = db.session.get(User, "test123")

            assert fetched is not None
            assert fetched.username == "newuser"
            assert fetched.is_admin is False
            assert fetched.is_active is True

    def test_is_active(self, test_app):
        with test_app.app_context():
            user = User(
                id="active_test",
                username="activeuser",
                password_hash=hash_password("Pass1234!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(user)
            db.session.commit()

            assert user.is_active is True
            assert user.is_active_field is True

            user.is_active = False
            db.session.commit()
            refreshed = db.session.get(User, "active_test")
            assert refreshed.is_active is False
            assert refreshed.is_active_field is False


            user2 = User(
                id="inactive_test",
                username="inactiveuser",
                password_hash=hash_password("Pass1234!"),
                is_admin=False,
                is_active_field=False
            )

            db.session.add(user2)
            db.session.commit()

            assert user.is_active is False
            assert user.is_active_field is False

            user2.is_active = True
            db.session.commit()

            refreshed2 = db.session.get(User, "inactive_test")
            assert refreshed2.is_active is True
            assert refreshed2.is_active_field is True

    def test_get_last_links(self, test_app, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            for i in range(7):
                link = ShortLink(
                    short_link=f"link{i:03d}",
                    redirect_url=f"https://example.com/{i}",
                    user_uuid=user_id,
                    created_at=int(datetime.now().timestamp()) + i,
                    clicks=0,
                    is_active=True
                )
                db.session.add(link)
            db.session.commit()

            user = db.session.get(User, user_id)
            last_links = user.get_last_links()
            assert len(last_links) == 5

    def test_unique_username(self, test_app):
        with test_app.app_context():
            user1 = User(id="u1", username="duplicate", password_hash="hash1")
            db.session.add(user1)
            db.session.commit()

            user2 = User(id="u2", username="duplicate", password_hash="hash2")
            db.session.add(user2)

            with pytest.raises(Exception):
                db.session.commit()

            db.session.rollback()

class TestShortLinkModel:
    def test_create_link(self, test_app, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            link = ShortLink(
                short_link="test01",
                redirect_url="https://example.com",
                user_uuid=user_id,
                created_at=int(datetime.now().timestamp()),
                clicks=0,
                is_active=True
            )

            db.session.add(link)
            db.session.commit()

            fetched = db.session.get(ShortLink, "test01")
            assert fetched is not None
            assert fetched.redirect_url == "https://example.com"

    def test_is_valid_active_link(self, test_app, sample_link):
        with test_app.app_context():
            link = db.session.get(ShortLink, "test01")
            assert link.is_valid() is True

    def test_is_valid_inactive_link(self, test_app, sample_link):
        with test_app.app_context():
            link = db.session.get(ShortLink, "test01")
            link.deactivate()
            db.session.commit()

            assert link.is_valid() is False

    def test_is_valid_expired_link(self, test_app, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            link = ShortLink(
                short_link="expire01",
                redirect_url="https://example.com",
                user_uuid=user_id,
                created_at=int((datetime.now() - timedelta(days=2)).timestamp()),
                clicks=0,
                max_clicks=0,
                expires_at=int((datetime.now() - timedelta(days=1)).timestamp()),
                is_active=True
            )
            db.session.add(link)
            db.session.commit()

            fetched = db.session.get(ShortLink, "expire01")
            assert fetched.is_valid() is False

    def test_is_valid_max_clicks_reached(self, test_app, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            link = ShortLink(
                short_link="clicks01",
                redirect_url="https://example.com",
                user_uuid=user_id,
                created_at=int(datetime.now().timestamp()),
                clicks=5,
                max_clicks=5,
                is_active=True
            )
            db.session.add(link)
            db.session.commit()

            fetched = db.session.get(ShortLink, "clicks01")
            assert fetched.is_valid() is False

    def test_is_valid_below_max_clicks(self, test_app, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            link = ShortLink(
                short_link="clicks02",
                redirect_url="https://example.com",
                user_uuid=user_id,
                created_at=int(datetime.now().timestamp()),
                clicks=3,
                max_clicks=5,
                is_active=True
            )
            db.session.add(link)
            db.session.commit()

            fetched = db.session.get(ShortLink, "clicks02")
            assert fetched.is_valid() is True

    def test_activate_deactivate(self, test_app, sample_link):
        with test_app.app_context():
            link = db.session.get(ShortLink, sample_link)
            assert link.is_active is True

            link.deactivate()
            db.session.commit()

            refreshed = db.session.get(ShortLink, sample_link)
            assert refreshed.is_active is False

            refreshed.activate()
            db.session.commit()

            refreshed2 = db.session.get(ShortLink, sample_link)
            assert refreshed2.is_active is True

    def test_get_owner_name(self, test_app, sample_link):
        with test_app.app_context():
            link = db.session.get(ShortLink, sample_link)
            owner_name = link.get_owner_name()
            assert owner_name == "testuser"

    def test_to_dict(self, test_app, sample_link):
        with test_app.app_context():
            link = db.session.get(ShortLink, sample_link)
            link_dict = link.to_dict()
            assert link_dict['short_link'] == "test01"
            assert link_dict['redirect_url'] == "https://example.com"
            assert link_dict['clicks'] == 0
            assert link_dict['is_active'] is True

    def test_generate_available_short_link(self, test_app):
        with test_app.app_context():
            code = generate_available_short_link()
            assert len(code) >= 6
            assert code.isalnum()

    def test_generate_available_short_link_custom_length(self, test_app):
        with test_app.app_context():
            code = generate_available_short_link(length=10)
            assert len(code) == 10

# Test password hashing
class TestPassword:
    def test_hash_and_verify(self):
        hashed = hash_password("TestPass1!")
        assert verify_password(hashed, "TestPass1!")

    def test_verify_wrong_password(self):
        hashed = hash_password("TestPass1!")
        assert verify_password(hashed, "WrongPass1!") is False

    def test_check_password_strength_valid(self):
        assert check_password_strength("Test1234!") is True

    def test_check_password_strength_too_short(self):
        assert check_password_strength("Te1!") is False

    def test_check_password_strength_no_uppercase(self):
        assert check_password_strength("test1234!") is False

    def test_check_password_strength_no_lowercase(self):
        assert check_password_strength("TEST1234!") is False

    def test_check_password_strength_no_digit(self):
        assert check_password_strength("TestTest!") is False

    def test_check_password_strength_no_special(self):
        assert check_password_strength("Test12345") is False

# Test routes
class TestAuthRoutes:
    def test_index_redirects_to_login(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_login_page_loads(self, client):
        response = client.get("/login")
        assert response.status_code == 200

    def test_register_page_loads(self, client):
        response = client.get("/register")
        assert response.status_code == 200

    def test_login_success(self, client, sample_user):
        _, username, password = sample_user
        response = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
        assert response.status_code == 302

    def test_login_wrong_password(self, client, sample_user):
        _, username, _ = sample_user
        response = client.post("/login", data={"username": username, "password": "WrongPass1!"}, follow_redirects=True)
        assert response.status_code == 200
        assert b"Invalid username or password" in response.data

    def test_login_nonexistent_user(self, client):
        response = login(client, "nouser", "SomePass1!")
        assert b"Invalid username or password" in response.data

    def test_login_inactive_user(self, test_app, client):
        with test_app.app_context():
            user = User(
                id="inactive_user",
                username="inactive",
                password_hash=hash_password("Inactive1!"),
                is_admin=False,
                is_active_field=False
            )
            db.session.add(user)
            db.session.commit()

        response = login(client, "inactive", "Inactive1!")
        assert b"Account is inactive" in response.data

    def test_register_success(self, client):
        response = client.post("/register", data={
            "username": "newuser",
            "password": "NewPass1!"
        }, follow_redirects=True)
        assert b"Registration successful" in response.data

    def test_register_duplicate_username(self, client, sample_user):
        _, username, _ = sample_user
        response = client.post("/register", data={
            "username": username,
            "password": "AnotherPass1!"
        }, follow_redirects=True)
        assert b"Username already exists" in response.data

    def test_register_weak_password(self, client):
        response = client.post("/register", data={
            "username": "weakpassuser",
            "password": "weak"
        }, follow_redirects=True)
        assert b"Password does not meet strength requirements" in response.data

    def test_logout(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/logout", follow_redirects=True)
        assert b"You have been logged out" in response.data

    def test_change_password_page_loads(self, client):
        response = client.get("/change_password")
        assert response.status_code == 200

    def test_change_password_page_prefills_username(self, client):
        response = client.get("/change_password?user_name=testuser")
        assert b"testuser" in response.data

    def test_login_redirects_change_password_with_username(self, test_app, client):
        with test_app.app_context():
            user = User(
                id="force_change_user2",
                username="forcechange2",
                password_hash=hash_password("OldPass1!"),
                is_admin=False,
                is_active_field=True,
                password_change_needed=True
            )
            db.session.add(user)
            db.session.commit()

        response = client.post("/login", data={
            "username": "forcechange2",
            "password": "OldPass1!"
        }, follow_redirects=False)
        assert "forcechange2" in response.headers["Location"]

    def test_login_after_change_succeeds(self, test_app, client):
        with test_app.app_context():
            user = User(
                id="force_change_user5",
                username="forcechange5",
                password_hash=hash_password("OldPass1!"),
                is_admin=False,
                is_active_field=True,
                password_change_needed=True
            )
            db.session.add(user)
            db.session.commit()

        client.post("/change_password", data={
            "user_name": "forcechange5",
            "current_password": "OldPass1!",
            "new_password": "NewPass1!",
            "new_password_confirm": "NewPass1!"
        }, follow_redirects=True)

        response = login(client, "forcechange5", "NewPass1!")
        assert b"Login successful" in response.data

    def test_login_change_password_wrong_password_stays_on_login(self, test_app, client):
        with test_app.app_context():
            user = User(
                id="force_change_user6",
                username="forcechange6",
                password_hash=hash_password("OldPass1!"),
                is_admin=False,
                is_active_field=True,
                password_change_needed=True
            )
            db.session.add(user)
            db.session.commit()

        response = login(client, "forcechange6", "WrongPass1!")
        assert b"Invalid username or password" in response.data

    def test_login_redirects_change_password(self, test_app, client):
        with test_app.app_context():
            user = User(
                id="force_change_user",
                username="forcechange",
                password_hash=hash_password("OldPass1!"),
                is_admin=False,
                is_active_field=True,
                password_change_needed=True
            )
            db.session.add(user)
            db.session.commit()

        response = client.post("/login", data={
            "username": "forcechange",
            "password": "OldPass1!"
        }, follow_redirects=False)
        assert response.status_code == 302
        assert "/change_password" in response.headers["Location"]
        assert "forcechange" in response.headers["Location"]

    def test_login_missing_username_and_password(self, client):
        response = client.post("/login", data={
            "username": "",
            "password": ""
        }, follow_redirects=True)
        assert b"Please enter username and password" in response.data

class TestLinkRoutes:
    def test_dashboard_requires_login(self, client):
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 302

    def test_dashboard_loads(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_create_link(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.post("/dashboard", data={
            "form_type": "create_link",
            "original_url": "https://example.com",
            "max_usages": "0",
            "timeout": "0"}, follow_redirects=True)
        assert b"Short link created successfully" in response.data

    def test_create_link_with_expiry(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.post("/dashboard", data={
            "form_type": "create_link",
            "original_url": "https://example.com",
            "max_usages": "0",
            "timeout": "60"}, follow_redirects=True)
        assert b"Short link created successfully" in response.data

    def test_create_no_url(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.post("/dashboard", data={
            "form_type": "create_link",
            "original_url": "",
            "max_usages": "0",
            "timeout": "0"}, follow_redirects=True)
        assert b"Please enter the Original URL" in response.data

    def test_redirect_short_link(self, client, sample_link):
        response = client.get(f"/s/{sample_link}", follow_redirects=False)
        assert response.status_code == 302
        assert "example.com" in response.headers["Location"]

    def test_redirect_nonexistent_link(self, client):
        response = client.get("/s/nonexistent", follow_redirects=False)
        assert response.status_code == 404

    def test_redirect_expired_link(self, test_app, client, sample_user):
        user_id, _, _ = sample_user
        with test_app.app_context():
            link = ShortLink(
                short_link="expired01",
                redirect_url="https://example.com",
                user_uuid=user_id,
                created_at=int((datetime.now() - timedelta(days=2)).timestamp()),
                expires_at=int((datetime.now() - timedelta(days=1)).timestamp()),
                clicks=0,
                is_active=True
            )
            db.session.add(link)
            db.session.commit()

        response = client.get("/s/expired01", follow_redirects=False)
        assert response.status_code == 410

    def test_redirect_increments_clicks(self, test_app, client, sample_link):
        client.get(f"/s/{sample_link}")
        client.get(f"/s/{sample_link}")
        with test_app.app_context():
            link = db.session.get(ShortLink, {sample_link})
            assert link.clicks == 2

    def test_my_links_requires_login(self, client):
        response = client.get("/my_links", follow_redirects=False)
        assert response.status_code == 302

    def test_my_links_loads(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/my_links")
        assert response.status_code == 200

    def test_links_stats_requires_login(self, client, sample_link):
        response = client.get(f"/link_stats/{sample_link}", follow_redirects=False)
        assert response.status_code == 302

    def test_link_stats_loads(self, client, sample_user, sample_link):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get(f"/link_stats/{sample_link}")
        assert response.status_code == 200

    def test_links_stats_other_user_denied(self, test_app, client, sample_user, sample_link):
        with test_app.app_context():
            other_user = User(
                id="other_user",
                username="other",
                password_hash=hash_password("OtherPass1!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(other_user)
            db.session.commit()

        login(client, "other", "OtherPass1!")
        response = client.get(f"/link_stats/{sample_link}", follow_redirects=True)
        assert b"You do not have permission" in response.data

    def test_toggle_link_active(self, test_app, client, sample_user, sample_link):
        _, username, password = sample_user
        login(client, username, password)

        response = client.post(f"/toggle_link_active/{sample_link}", follow_redirects=True)
        assert b"deactivated" in response.data

    def test_delete_link(self, test_app, client,sample_user, sample_link):
        _, username, password = sample_user
        login(client, username, password)

        response = client.post(f"/delete_link/{sample_link}",
                               headers={"Referer": "/my_links"},
                               follow_redirects=True)
        assert b"Link deleted successfully" in response.data

    def test_other_user_cannot_delete_link(self, test_app, client, sample_user, sample_link):
        with test_app.app_context():
            other_user = User(
                id="other_user2",
                username="other2",
                password_hash=hash_password("Other1234!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(other_user)
            db.session.commit()

        login(client, "other2", "Other1234!")
        response = client.post(f"/delete_link/{sample_link}",
                               headers={"Referer": "/my_links"},
                               follow_redirects=True)
        assert b"You do not have permission" in response.data

    def test_other_user_cannot_toggle_link(self, test_app, client, sample_user, sample_link):
        with test_app.app_context():
            other_user = User(
                id="other_user3",
                username="other3",
                password_hash=hash_password("Other1234!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(other_user)
            db.session.commit()

        login(client, "other3", "Other1234!")
        response = client.post(f"/toggle_link_active/{sample_link}", follow_redirects=True)
        assert b"You do not have permission" in response.data

class TestAdminRoutes:
    def test_all_links_requires_admin(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/all_links", follow_redirects=True)
        assert response.status_code == 403

    def test_all_links_loads_for_admin(self, client, admin_user):
        _, username, password = admin_user
        login(client, username, password)
        response = client.get("/all_links")
        assert response.status_code == 200

    def test_manage_users_requires_admin(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/manage_users", follow_redirects=True)
        assert response.status_code == 403

    def test_manage_users_loads_for_admin(self, client, admin_user):
        _, username, password = admin_user
        login(client, username, password)
        response = client.get("/manage_users")
        assert response.status_code == 200

    def test_toggle_user_active(self, test_app, client, admin_user, sample_user):
        user_id, _, _ = sample_user
        _, admin_name, admin_pass = admin_user
        login(client, admin_name, admin_pass)
        response = client.post(f"/toggle_user_active/{user_id}/false",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"not active" in response.data
        response = client.post(f"/toggle_user_active/{user_id}/true",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"active" in response.data

    def test_toggle_admin(self, test_app, client, admin_user, sample_user):
        user_id, _, _ = sample_user
        _, admin_name, admin_pass = admin_user
        login(client, admin_name, admin_pass)
        response = client.post(f"/toggle_admin/{user_id}/true",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"an admin" in response.data
        response = client.post(f"/toggle_admin/{user_id}/false",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"no longer an admin" in response.data

    def test_reset_user_password(self, test_app, client, admin_user, sample_user):
        user_id, _, user_pass = sample_user
        _, admin_name, admin_pass = admin_user
        login(client, admin_name, admin_pass)
        response = client.post(f"/reset_user_password/{user_id}",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert response.status_code == 200

    def test_delete_user(self, test_app, client, admin_user, sample_user):
        user_id, _, _ = sample_user
        _, admin_name, admin_pass = admin_user
        login(client, admin_name, admin_pass)
        response = client.post(f"/delete_user/{user_id}",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"User deleted successfully" in response.data

    def test_admin_can_view_other_user_stats(self, client, admin_user, sample_link):
        _, admin_name, admin_pass = admin_user
        login(client, admin_name, admin_pass)
        response = client.get(f"/link_stats/{sample_link}")
        assert response.status_code == 200

    def test_non_admin_cannot_delete_other_user(self, test_app, client, sample_user):
        _, username, password = sample_user
        with test_app.app_context():
            other_user = User(
                id="victim_user",
                username="victim",
                password_hash=hash_password("Victim1!"),
                is_admin=False,
                is_active_field=True
            )
            db.session.add(other_user)
            db.session.commit()

        login(client, username, password)
        response = client.post("/delete_user/victim_user",
                               headers={"Referer": "/manage_users"},
                               follow_redirects=True)
        assert b"You do not have permission" in response.data

# Some error handling
class TestErrorHandling:
    def test_404_page(self, client):
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_toggle_nonexisting_link(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.post("/toggle_link_active/nonexistent", follow_redirects=True)
        assert b"Link not found" in response.data

    def test_delete_nonexisting_link(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.post("/delete_link/nonexistent", follow_redirects=True)
        assert b"Link not found" in response.data

    def test_stats_nonexistent_link(self, client, sample_user):
        _, username, password = sample_user
        login(client, username, password)
        response = client.get("/link_stats/nonexist", follow_redirects=True)
        assert b"Link not found" in response.data


