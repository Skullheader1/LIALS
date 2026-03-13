import os
from datetime import datetime, timedelta

from argon2.exceptions import VerifyMismatchError
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, current_user, login_user, login_required, logout_user
from argon2 import PasswordHasher
from sqlalchemy import or_

from database import User, db, ShortLink, generate_available_short_link
from wraps.admin_required import admin_required

import logging

ph = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16
)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=30)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@app.context_processor
def inject_datetime():
    return {"datetime": datetime}

@app.context_processor
def inject_base_redirect_url():
    return {"base_redirect_url": request.host_url+"s/"}

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password_hash: str, password: str) -> bool:
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False

def initialise():
    existing_root = User.query.filter_by(username="root").first()

    if existing_root is None:
        root_user = User(
            id=os.urandom(32).hex(),
            username="root",
            password_hash=hash_password("root"),
            is_admin=True,
            is_active_field=True,
            password_change_needed=True
        )

        db.session.add(root_user)
        db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/s/<short_link>")
def redirect_short_link(short_link):
    if not short_link:
        return render_template("404.html"), 404

    link = db.session.get(ShortLink, short_link)

    if link is None:
        return render_template("404.html"), 404

    if not link.is_valid():
        return render_template("404.html"), 410

    link.clicks += 1
    db.session.commit()

    return redirect(link.redirect_url)


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        form_type = request.form.get("form_type")
        if form_type == "create_link":
            if not request.form.get("original_url"):
                flash("Please enter the Original URL", "error")
                return render_template("dashboard.html", is_admin = current_user.is_admin, last_links = current_user.get_last_links()[::-1])
            else:
                original_url = request.form.get("original_url")

            if not request.form.get("max_usages"):
                max_usages = 0
            else:
                max_usages = int(request.form.get("max_usages"))

            if not request.form.get("timeout"):
                timeout = 0
            else:
                timeout = int(request.form.get("timeout"))

            if timeout == 0:
                time = None
            else:
                time = datetime.now()
                time = time + timedelta(days=timeout)
                time = int(time.timestamp())

            new_short_link = ShortLink(
                short_link=generate_available_short_link(),
                redirect_url=original_url,
                user_uuid= current_user.id,
                created_at=int(datetime.now().timestamp()),
                clicks=0,
                max_clicks=max_usages,
                expires_at=time,
                is_active=True
            )
            db.session.add(new_short_link)
            db.session.commit()
            flash("Short link created successfully: " + request.host_url + "s/" + new_short_link.short_link, "success")

    return render_template("dashboard.html", is_admin = current_user.is_admin, last_links = current_user.get_last_links()[::-1])

@app.route("/my_links", methods=["GET", "POST"])
@login_required
def my_links():
    pagecount = 10

    previous_page = False
    next_page = False

    search_query = request.args.get("search", "")
    if request.method == "POST":
        search_query = request.form.get("search", "")

    base_query = ShortLink.query.filter_by(user_uuid=current_user.id)
    if search_query:
        base_query = base_query.filter(or_(
            ShortLink.short_link.ilike(f"%{search_query}%"),
            ShortLink.redirect_url.ilike(f"%{search_query}%")
        ))

    entries = base_query.count()

    max_pages = entries // pagecount + (1 if entries % pagecount > 0 else 0)

    if request.method=="POST":
        current_page = int(request.form.get("current_page"))
        action = request.form.get("action")
        start = current_page * pagecount - pagecount
        end = current_page * pagecount

        if action == "next":
            if entries > end:
                start = current_page * pagecount
                end = start + pagecount
                previous_page = True
                current_page += 1
                if entries > current_page * pagecount:
                    next_page = True
            else:
                flash("No more pages available", "error")
        if action == "previous":
            if current_page > 1:
                end = (current_page -1) * pagecount
                start = end - pagecount
                current_page -= 1
                next_page = True
                if current_page > 1:
                    previous_page = True
            else:
                flash("You are already on the first page", "error")
            pass

        links = (base_query
                 .order_by(ShortLink.created_at.desc())
                 .offset(start)
                 .limit(end-start)
                 .all())

        return render_template("my_links.html",
                               is_admin=current_user.is_admin,
                               links=links,
                               current_page=current_page,
                               max_pages=max_pages,
                               previous_page=previous_page,
                               next_page=next_page,
                               search_query=search_query)



    links = (base_query
             .order_by(ShortLink.created_at.desc())
             .offset(0)
             .limit(pagecount)
             .all())

    if entries > pagecount:
        next_page = True

    return render_template("my_links.html",
                           is_admin = current_user.is_admin,
                           links=links,
                           current_page=1,
                           max_pages=max_pages,
                           previous_page=previous_page,
                           next_page=next_page,
                           search_query=search_query)

@app.route("/all_links", methods=["GET", "POST"])
@login_required
@admin_required
def all_links():

    pagecount = 10

    previous_page = False
    next_page = False

    search_query = request.args.get("search", "")
    if request.method == "POST":
        search_query = request.form.get("search", "")

    base_query = ShortLink.query
    if search_query:
        base_query = base_query.join(User, ShortLink.user_uuid == User.id).filter(or_(
            ShortLink.short_link.ilike(f"%{search_query}%"),
            ShortLink.redirect_url.ilike(f"%{search_query}%"),
            User.username.ilike(f"%{search_query}%")
        ))

    entries = base_query.count()

    max_pages = entries // pagecount + (1 if entries % pagecount > 0 else 0)

    if request.method=="POST":
        current_page = int(request.form.get("current_page"))
        action = request.form.get("action")
        start = current_page * pagecount - pagecount
        end = current_page * pagecount

        if action == "next":
            if entries > end:
                start = current_page * pagecount
                end = start + pagecount
                previous_page = True
                current_page += 1
                if entries > current_page * pagecount:
                    next_page = True
            else:
                flash("No more pages available", "error")
        if action == "previous":
            if current_page > 1:
                end = (current_page -1) * pagecount
                start = end - pagecount
                current_page -= 1
                next_page = True
                if current_page > 1:
                    previous_page = True
            else:
                flash("You are already on the first page", "error")
            pass

        links = (base_query
                 .order_by(ShortLink.created_at.desc())
                 .offset(start)
                 .limit(end-start)
                 .all())

        return render_template("all_links.html",
                               is_admin = current_user.is_admin,
                               links=links,
                               current_page=current_page,
                               max_pages=max_pages,
                               previous_page=previous_page,
                               next_page=next_page,
                               search_query=search_query)

    links = (base_query
                 .order_by(ShortLink.created_at.desc())
                 .offset(0)
                 .limit(pagecount)
                 .all())

    return render_template("all_links.html",
                            is_admin = current_user.is_admin,
                            links=links,
                            current_page=1,
                            max_pages=max_pages,
                            previous_page=previous_page,
                            next_page=True if entries > pagecount else False,
                            search_query=search_query)

@app.route("/manage_users", methods=["GET", "POST"])
@login_required
@admin_required
def manage_users():
    pagecount = 10

    search_query = request.args.get("search", "")
    if request.method == "POST":
        search_query = request.form.get("search", "")

    base_query = User.query
    if search_query:
        base_query = base_query.filter(or_(User.username.ilike(f"%{search_query}%"),
                                           User.id.ilike(f"%{search_query}%")))

    entries = base_query.count()

    previous_page = False
    next_page = False

    max_pages = entries // pagecount + (1 if entries % pagecount > 0 else 0)

    if request.method=="POST":

        current_page = int(request.form.get("current_page"))
        action = request.form.get("action")

        start = current_page * pagecount - pagecount
        end = current_page * pagecount

        if action == "next":
            if entries > end:
                start = current_page * pagecount
                end = start + pagecount
                previous_page = True
                current_page += 1
                if entries > current_page * pagecount:
                    next_page = True
            else:
                flash("No more pages available", "error")
        if action == "previous":
            if current_page > 1:
                end = (current_page -1) * pagecount
                start = end - pagecount
                current_page -= 1
                next_page = True
                if current_page > 1:
                    previous_page = True
            else:
                flash("You are already on the first page", "error")
            pass

        users = (base_query
                 .order_by(User.username)
                 .offset(start)
                 .limit(end-start)
                 .all())

        return render_template("manage_users.html",
                               is_admin=current_user.is_admin,
                               users=users,
                               current_page=current_page,
                               max_pages=max_pages,
                               previous_page=previous_page,
                               next_page=next_page,
                               search_query=search_query,)

    users = (base_query
             .order_by(User.username)
             .offset(0)
             .limit(pagecount)
             .all())

    return render_template("manage_users.html",
                           is_admin = current_user.is_admin,
                           users=users,
                           current_page=1,
                           max_pages=max_pages,
                           previous_page=False,
                           next_page=True if entries > pagecount else False,
                           search_query=search_query,)

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        session.permanent = True
        return redirect(url_for("index"))


    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if not username or not password:
            flash("Please enter username and password", "error")
            return render_template("login.html")

        user = User.query.filter_by(username=username).first()

        if user is None:
            flash("Invalid username or password", "error")
            return render_template("login.html")

        if not user.is_active:
            flash("Account is inactive. Please contact an administrator.", "error")
            return render_template("login.html")

        if not verify_password(user.password_hash, password):
            flash("Invalid username or password", "error")
            return render_template("login.html")

        if user.password_change_needed:
            flash("Password change needed", "error")
            return redirect(url_for("change_password", user_name=user.username))

        login_user(user)

        session.permanent = True

        flash("Login successful", "success")

        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/change_password", methods=["POST", "GET"])
def change_password():
    if request.method == "POST":
        username = request.form["user_name"]
        current_password = request.form["current_password"]
        new_password = request.form["new_password"]
        new_password_confirm = request.form["new_password_confirm"]

        if not username or not current_password or not new_password or not new_password_confirm:
            flash("Please fill in all fields", "error")
            return render_template("change_password.html")

        user = User.query.filter_by(username=username).first()

        if not user:
            flash("User not found", "error")
            return render_template("change_password.html")

        if not verify_password(user.password_hash, current_password):
            flash("Current password is incorrect", "error")
            return render_template("change_password.html")

        if new_password != new_password_confirm:
            flash("Confirmation password does not match", "error")
            return render_template("change_password.html")

        if current_password == new_password:
            flash("New password must be different from current password", "error")
            return render_template("change_password.html")

        if not check_password_strength(new_password):
            flash("New password does not meet strength requirements", "error")
            return render_template("change_password.html")

        user.password_hash = hash_password(new_password)
        user.password_change_needed = False
        db.session.commit()

        logout_user()

        flash("Password changed successfully. Please log in.", "success")
        return redirect(url_for("login"))

    user_name = request.args.get("user_name", default="")
    return render_template("change_password.html", user_name=user_name)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if not username or not password:
            flash("Please enter username and password", "error")
            return render_template("register.html")

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists", "error")
            return render_template("register.html")

        if not check_password_strength(password):
            flash("Password does not meet strength requirements", "error")
            return render_template("register.html")

        password_hash = hash_password(password)
        user_id = os.urandom(32).hex()

        new_user = User(
            id=user_id,
            username=username,
            password_hash=password_hash,
            is_admin=False,
            is_active_field=True,
            password_change_needed=False
        )

        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")



@app.route("/link_stats/<link_id>")
@login_required
def link_stats(link_id):
    link = db.session.get(ShortLink, link_id)

    if link is None:
        flash("Link not found", "error")
        return redirect(url_for("my_links"))

    if link.user_uuid != current_user.id and not current_user.is_admin:
        flash("You do not have permission to view this link's statistics", "error")
        return redirect(url_for("my_links"))

    return render_template("link_stats.html",
                           is_admin=current_user.is_admin,
                           link=link)

@app.route("/toggle_link_active/<link_id>", methods=["POST"])
@login_required
def toggle_link_active(link_id):
    link = db.session.get(ShortLink, link_id)

    if link is None:
        flash("Link not found", "error")
        return redirect(url_for("my_links"))

    if link.user_uuid != current_user.id and not current_user.is_admin:
        flash("You do not have permission to modify this link", "error")
        return redirect(url_for("my_links"))

    link.is_active = not link.is_active
    db.session.commit()

    flash(f"Link {'activated' if link.is_active else 'deactivated'} successfully", "success")
    return redirect(request.referrer or url_for("my_links"))

@app.route("/delete_link/<link_id>", methods=["POST"])
@login_required
def delete_link(link_id):
    link = db.session.get(ShortLink, link_id)

    if link is None:
        flash("Link not found", "error")
        return redirect(url_for("dashboard"))

    if link.user_uuid != current_user.id and not current_user.is_admin:
        flash("You do not have permission to delete this link", "error")
        return redirect(url_for("dashboard"))

    db.session.delete(link)
    db.session.commit()

    flash("Link deleted successfully", "success")
    return redirect(request.referrer)

@app.route("/delete_user/<uuid>", methods=["POST"])
@login_required
def delete_user(uuid):
    if not current_user.is_authenticated:
        return redirect(url_for("index"))

    if not current_user.id==uuid and not current_user.is_admin:
        flash("You do not have permission to delete this user", "error")
        return redirect(url_for("dashboard"))

    user = db.session.get(User, uuid)

    if user is None:
        flash("User not found", "error")
        return redirect(url_for("manage_users"))

    db.session.delete(user)
    db.session.commit()

    flash("User deleted successfully", "success")
    return redirect(request.referrer)

@app.route("/toggle_user_active/<uuid>/<active>", methods=["POST"])
@login_required
@admin_required
def toggle_user_active(uuid, active):
    #Todo root checks einbauen, damit root nicht deaktiviert werden kann
    active = active.lower() == "true"

    user = db.session.get(User, uuid)

    if user is None:
        flash("User not found", "error")
        return redirect(url_for("manage_users"))

    user.is_active = active
    db.session.commit()

    flash(f"User {user.username} is now {'active' if active else 'not active'}", "success")
    return redirect(request.referrer)

@app.route("/reset_user_password/<uuid>", methods=["POST"])
@login_required
@admin_required
def reset_user_password(uuid):
    user = db.session.get(User, uuid)

    if user is None:
        flash("User not found", "error")
        return redirect(url_for("manage_users"))

    new_password = os.urandom(8).hex()
    user.password_hash = hash_password(new_password)
    user.password_change_needed = True
    db.session.commit()

    flash({"message": f"Password for user {user.username} has been reset to: {new_password}", "password": new_password}, "pw-change")
    return redirect(request.referrer)

@app.route("/toggle_admin/<uuid>/<admin>", methods=["POST"])
@login_required
@admin_required
def toggle_admin(uuid, admin):
    admin = admin.lower() == "true"

    user = db.session.get(User, uuid)

    if user is None:
        flash("User not found", "error")
        return redirect(url_for("manage_users"))

    user.is_admin = admin
    db.session.commit()

    flash(f"User {user.username} is now {'an admin' if admin else 'no longer an admin'}", "success")
    return redirect(request.referrer)

def check_password_strength(password: str) -> bool:
    if len(password) < 8:
        return False
    if not any(char.isupper() for char in password):
        return False
    if not any(char.islower() for char in password):
        return False
    if not any(char.isdigit() for char in password):
        return False
    special_characters = "!@#$%^&*()-_=+[]{}|;:'\",.<>?/`~"
    if not any(char in special_characters for char in password):
        return False
    return True

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))