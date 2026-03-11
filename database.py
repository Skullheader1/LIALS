import string
from datetime import datetime
import random

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.String(64), primary_key=True)
    password_hash = db.Column(db.String(128), nullable=False)
    username = db.Column(db.String(64), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active_field = db.Column(db.Boolean, default=True)
    password_change_needed = db.Column(db.Boolean, default=False)
    totp_secret = db.Column(db.String(64), nullable=True)

    short_links = db.relationship('ShortLink', backref='owner', lazy='dynamic')

    @property
    def is_active(self):
        return self.is_active_field

    @is_active.setter
    def is_active(self, value):
        self.is_active_field = value

    def get_last_links(self):
        return (ShortLink.query
                .filter_by(user_uuid=self.id)
                .order_by(ShortLink.created_at.desc())
                .limit(5)
                .all())


class ShortLink(db.Model):
    __tablename__ = "short_links"

    short_link = db.Column(db.String(32), primary_key=True)
    redirect_url = db.Column(db.String(128), nullable=False)
    user_uuid = db.Column(db.String(64), db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.Integer, nullable=False)
    clicks = db.Column(db.Integer, default=0)
    expires_at = db.Column(db.Integer, nullable=True)
    max_clicks = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    def deactivate(self):
        self.is_active = False

    def activate(self):
        self.is_active = True

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expires_at is not None and self.expires_at != 0 and int(datetime.now().timestamp()) > self.expires_at:
            return False
        if self.max_clicks is not None and self.max_clicks != 0 and self.clicks >= self.max_clicks:
            return False
        return True

    def get_owner_name(self):
        user = db.session.get(User, self.user_uuid)
        return user.username if user else None

    def to_dict(self):
        return {
            "short_link": self.short_link,
            "redirect_url": self.redirect_url,
            "user_uuid": self.user_uuid,
            "created_at": self.created_at,
            "clicks": self.clicks,
            "expires_at": self.expires_at,
            "max_clicks": self.max_clicks,
            "is_active": self.is_active
        }

def generate_available_short_link(length=6):
    while True:
        candidate = ''.join(random.choices(string.ascii_letters+string.digits, k=length))
        if db.session.get(ShortLink, candidate) is None:
            return candidate
