import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "community-lending-secret-key")

# =========================================================
# FILE UPLOAD CONFIGURATION
# =========================================================
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB limit
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_item_image(file):
    if file and file.filename and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex[:10]}_{filename}"
        dest_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
        file.save(dest_path)
        return unique_filename
    return None


def delete_item_image(filename):
    if filename:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# =========================================================
# DATABASE CONNECTION & SCHEMA INIT (ENV VARIABLES SUPPORT)
# =========================================================
def get_db_connection():
    host = os.environ.get("DB_HOST", "localhost")
    user = os.environ.get("DB_USER", "root")
    password = os.environ.get("DB_PASSWORD", "Shahith@123")
    database = os.environ.get("DB_NAME", "community_lending")
    port = int(os.environ.get("DB_PORT", 3306))
    
    conn_params = {
        "host": host,
        "user": user,
        "password": password,
        "database": database,
        "port": port
    }
    
    # Cloud database SSL support (e.g. TiDB Cloud / Aiven)
    if host != "localhost":
        if os.path.exists("/etc/ssl/certs/ca-certificates.crt"):
            conn_params["ssl_ca"] = "/etc/ssl/certs/ca-certificates.crt"
        elif os.environ.get("DB_SSL_CA"):
            conn_params["ssl_ca"] = os.environ.get("DB_SSL_CA")

    return mysql.connector.connect(**conn_params)


def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create tables automatically if deploying on a new cloud database
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                phone VARCHAR(20) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                owner_id INT NOT NULL,
                item_name VARCHAR(150) NOT NULL,
                category VARCHAR(100) NOT NULL,
                description TEXT NULL,
                image VARCHAR(255) NULL,
                availability ENUM('Available', 'Lent', 'Unavailable') DEFAULT 'Available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lending_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                item_id INT NOT NULL,
                borrower_id INT NOT NULL,
                owner_id INT NOT NULL,
                status ENUM('Pending', 'Approved', 'Rejected', 'Returned') DEFAULT 'Pending',
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (borrower_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # Ensure image column exists in items
        cursor.execute("SHOW COLUMNS FROM items LIKE 'image'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE items ADD COLUMN image VARCHAR(255) NULL AFTER description")

        conn.commit()
        cursor.close()
        conn.close()
        print("Database schema verified and tables initialized.")
    except Exception as e:
        print(f"Database schema auto-check error: {e}")


# Run DB initialization once on load
init_db()


# =========================================================
# HOME ROUTE
# =========================================================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# =========================================================
# REGISTER
# =========================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()

        if not name or not email or not password:
            flash("Please fill in all required fields.", "warning")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        connection = get_db_connection()
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO users (name, email, password, phone)
                VALUES (%s, %s, %s, %s)
                """,
                (name, email, password_hash, phone)
            )
            connection.commit()
            flash("Account created successfully! Please log in with your credentials.", "success")
            return redirect(url_for("login"))

        except mysql.connector.Error as error:
            flash(f"Registration Failed: {error}", "danger")
            return render_template("register.html")

        finally:
            cursor.close()
            connection.close()

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password. Please verify your credentials and try again.", "danger")
        return render_template("login.html")

    return render_template("login.html")


# =========================================================
# DASHBOARD
# =========================================================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # 1. My listed items count
    cursor.execute("SELECT COUNT(*) AS total FROM items WHERE owner_id = %s", (user_id,))
    my_items_count = cursor.fetchone()["total"]

    # 2. Available community items count
    cursor.execute("SELECT COUNT(*) AS total FROM items WHERE owner_id != %s AND availability = 'Available'", (user_id,))
    available_items_count = cursor.fetchone()["total"]

    # 3. Pending requests received (waiting for user's approval)
    cursor.execute("SELECT COUNT(*) AS total FROM lending_requests WHERE owner_id = %s AND status = 'Pending'", (user_id,))
    pending_requests_count = cursor.fetchone()["total"]

    # 4. Currently active borrowed items
    cursor.execute("SELECT COUNT(*) AS total FROM lending_requests WHERE borrower_id = %s AND status = 'Approved'", (user_id,))
    active_borrows_count = cursor.fetchone()["total"]

    # 5. Completed return transactions
    cursor.execute(
        "SELECT COUNT(*) AS total FROM lending_requests WHERE (owner_id = %s OR borrower_id = %s) AND status = 'Returned'",
        (user_id, user_id)
    )
    completed_transactions_count = cursor.fetchone()["total"]

    # 6. Latest community items available to borrow
    cursor.execute(
        """
        SELECT items.id, items.item_name, items.category, items.description, items.image, items.created_at, users.name AS owner_name
        FROM items
        JOIN users ON items.owner_id = users.id
        WHERE items.owner_id != %s AND items.availability = 'Available'
        ORDER BY items.created_at DESC
        LIMIT 3
        """,
        (user_id,)
    )
    recent_items = cursor.fetchall()

    cursor.close()
    connection.close()

    stats = {
        "my_items": my_items_count,
        "available_items": available_items_count,
        "pending_requests": pending_requests_count,
        "active_borrows": active_borrows_count,
        "completed_transactions": completed_transactions_count
    }

    return render_template(
        "dashboard.html",
        name=session["user_name"],
        email=session["user_email"],
        stats=stats,
        recent_items=recent_items
    )


# =========================================================
# ADD ITEM (WITH PHOTO UPLOAD)
# =========================================================
@app.route("/add-item", methods=["GET", "POST"])
def add_item():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        if not item_name or not category:
            flash("Please provide an item name and category.", "warning")
            return render_template("add_item.html")

        # Handle Photo Upload
        image_file = request.files.get("image")
        image_filename = save_item_image(image_file)

        connection = get_db_connection()
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO items (owner_id, item_name, category, description, image)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session["user_id"], item_name, category, description, image_filename)
            )
            connection.commit()
            flash(f"'{item_name}' added successfully to the community catalog!", "success")
            return redirect(url_for("my_items"))

        except mysql.connector.Error as error:
            if image_filename:
                delete_item_image(image_filename)
            flash(f"Failed to add item: {error}", "danger")
            return render_template("add_item.html")

        finally:
            cursor.close()
            connection.close()

    return render_template("add_item.html")


# =========================================================
# MY ITEMS
# =========================================================
@app.route("/my-items")
def my_items():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM items
        WHERE owner_id = %s
        ORDER BY created_at DESC
        """,
        (session["user_id"],)
    )
    items = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("my_items.html", items=items)


# =========================================================
# EDIT ITEM (WITH PHOTO UPDATE/REPLACE)
# =========================================================
@app.route("/edit-item/<int:item_id>", methods=["GET", "POST"])
def edit_item(item_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM items WHERE id = %s AND owner_id = %s",
        (item_id, session["user_id"])
    )
    item = cursor.fetchone()

    if not item:
        cursor.close()
        connection.close()
        flash("Item not found or you do not have permission to edit it.", "danger")
        return redirect(url_for("my_items"))

    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        availability = request.form.get("availability", "Available")
        remove_image = request.form.get("remove_image")

        current_image = item.get("image")
        new_image_file = request.files.get("image")

        if new_image_file and new_image_file.filename:
            saved_filename = save_item_image(new_image_file)
            if saved_filename:
                delete_item_image(current_image)
                current_image = saved_filename
        elif remove_image:
            delete_item_image(current_image)
            current_image = None

        cursor.execute(
            """
            UPDATE items
            SET item_name = %s,
                category = %s,
                description = %s,
                availability = %s,
                image = %s
            WHERE id = %s AND owner_id = %s
            """,
            (item_name, category, description, availability, current_image, item_id, session["user_id"])
        )
        connection.commit()
        cursor.close()
        connection.close()

        flash(f"Item '{item_name}' updated successfully!", "success")
        return redirect(url_for("my_items"))

    cursor.close()
    connection.close()
    return render_template("edit_item.html", item=item)


# =========================================================
# DELETE ITEM
# =========================================================
@app.route("/delete-item/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT image FROM items WHERE id = %s AND owner_id = %s", (item_id, session["user_id"]))
    item = cursor.fetchone()

    if item:
        if item.get("image"):
            delete_item_image(item["image"])

        cursor.execute("DELETE FROM items WHERE id = %s AND owner_id = %s", (item_id, session["user_id"]))
        connection.commit()
        flash("Item was successfully deleted.", "info")
    else:
        flash("Item could not be found or you are not authorized to delete it.", "danger")

    cursor.close()
    connection.close()
    return redirect(url_for("my_items"))


# =========================================================
# BROWSE ITEMS
# =========================================================
@app.route("/browse-items")
def browse_items():
    if "user_id" not in session:
        return redirect(url_for("login"))

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT DISTINCT category
            FROM items
            WHERE owner_id != %s AND availability = 'Available'
            ORDER BY category
            """,
            (session["user_id"],)
        )
        categories = cursor.fetchall()

        query = """
            SELECT
                items.id,
                items.item_name,
                items.category,
                items.description,
                items.availability,
                items.image,
                items.created_at,
                users.name AS owner_name
            FROM items
            JOIN users ON items.owner_id = users.id
            WHERE items.owner_id != %s AND items.availability = 'Available'
        """
        params = [session["user_id"]]

        if search:
            query += """
                AND (
                    items.item_name LIKE %s
                    OR items.category LIKE %s
                    OR items.description LIKE %s
                    OR users.name LIKE %s
                )
            """
            search_val = f"%{search}%"
            params.extend([search_val, search_val, search_val, search_val])

        if category:
            query += " AND items.category = %s"
            params.append(category)

        query += " ORDER BY items.created_at DESC"

        cursor.execute(query, tuple(params))
        items = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "browse_items.html",
        items=items,
        categories=categories,
        search=search,
        selected_category=category
    )


# =========================================================
# VIEW ITEM DETAILS
# =========================================================
@app.route("/item/<int:item_id>")
def item_details(item_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            items.id,
            items.item_name,
            items.category,
            items.description,
            items.availability,
            items.image,
            items.created_at,
            items.owner_id,
            users.name AS owner_name,
            users.email AS owner_email,
            users.phone AS owner_phone
        FROM items
        JOIN users ON items.owner_id = users.id
        WHERE items.id = %s
        """,
        (item_id,)
    )
    item = cursor.fetchone()

    if not item:
        cursor.close()
        connection.close()
        flash("The requested item was not found.", "danger")
        return redirect(url_for("browse_items"))

    # Check if current user has an active borrowing request for this item
    cursor.execute(
        """
        SELECT id, status
        FROM lending_requests
        WHERE item_id = %s AND borrower_id = %s AND status IN ('Pending', 'Approved')
        """,
        (item_id, session["user_id"])
    )
    user_request = cursor.fetchone()

    cursor.close()
    connection.close()

    return render_template("item_details.html", item=item, user_request=user_request)


# =========================================================
# REQUEST TO BORROW
# =========================================================
@app.route("/request-item/<int:item_id>", methods=["POST"])
def request_item(item_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("SELECT id, owner_id, availability, item_name FROM items WHERE id = %s", (item_id,))
        item = cursor.fetchone()

        if not item:
            flash("Item not found.", "danger")
            return redirect(url_for("browse_items"))

        if item["owner_id"] == session["user_id"]:
            flash("You cannot request to borrow your own item.", "warning")
            return redirect(url_for("item_details", item_id=item_id))

        if item["availability"] != "Available":
            flash("This item is currently not available for borrowing.", "warning")
            return redirect(url_for("item_details", item_id=item_id))

        cursor.execute(
            """
            SELECT id FROM lending_requests
            WHERE item_id = %s AND borrower_id = %s AND status = 'Pending'
            """,
            (item_id, session["user_id"])
        )
        if cursor.fetchone():
            flash("You already have a pending borrow request for this item.", "info")
            return redirect(url_for("item_details", item_id=item_id))

        cursor.execute(
            """
            INSERT INTO lending_requests (item_id, borrower_id, owner_id, status)
            VALUES (%s, %s, %s, 'Pending')
            """,
            (item_id, session["user_id"], item["owner_id"])
        )
        connection.commit()
        flash(f"Your borrowing request for '{item['item_name']}' has been sent to the owner!", "success")
        return redirect(url_for("my_requests"))

    except mysql.connector.Error as error:
        connection.rollback()
        flash(f"Request failed: {error}", "danger")
        return redirect(url_for("item_details", item_id=item_id))

    finally:
        cursor.close()
        connection.close()


# =========================================================
# RECEIVED BORROW REQUESTS
# =========================================================
@app.route("/received-requests")
def received_requests():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            lending_requests.id,
            lending_requests.status,
            lending_requests.requested_at,
            items.id AS item_id,
            items.item_name,
            items.category,
            items.image,
            users.name AS borrower_name,
            users.email AS borrower_email,
            users.phone AS borrower_phone
        FROM lending_requests
        JOIN items ON lending_requests.item_id = items.id
        JOIN users ON lending_requests.borrower_id = users.id
        WHERE lending_requests.owner_id = %s
        ORDER BY lending_requests.requested_at DESC
        """,
        (session["user_id"],)
    )
    requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("received_requests.html", requests=requests)


# =========================================================
# APPROVE REQUEST
# =========================================================
@app.route("/approve-request/<int:request_id>", methods=["POST"])
def approve_request(request_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                lending_requests.id,
                lending_requests.item_id,
                lending_requests.owner_id,
                lending_requests.status,
                items.availability,
                items.item_name
            FROM lending_requests
            JOIN items ON lending_requests.item_id = items.id
            WHERE lending_requests.id = %s AND lending_requests.owner_id = %s
            """,
            (request_id, session["user_id"])
        )
        borrow_request = cursor.fetchone()

        if not borrow_request:
            flash("Request not found or you do not have permission.", "danger")
            return redirect(url_for("received_requests"))

        if borrow_request["status"] != "Pending":
            flash("This request has already been processed.", "warning")
            return redirect(url_for("received_requests"))

        if borrow_request["availability"] != "Available":
            flash("This item is no longer marked as Available.", "warning")
            return redirect(url_for("received_requests"))

        # Approve request
        cursor.execute(
            """
            UPDATE lending_requests
            SET status = 'Approved'
            WHERE id = %s AND owner_id = %s AND status = 'Pending'
            """,
            (request_id, session["user_id"])
        )

        # Mark item as Lent
        cursor.execute(
            """
            UPDATE items
            SET availability = 'Lent'
            WHERE id = %s AND owner_id = %s
            """,
            (borrow_request["item_id"], session["user_id"])
        )

        connection.commit()
        flash(f"Request approved! '{borrow_request['item_name']}' is now marked as Lent.", "success")
        return redirect(url_for("received_requests"))

    except mysql.connector.Error as error:
        connection.rollback()
        flash(f"Approval Failed: {error}", "danger")
        return redirect(url_for("received_requests"))

    finally:
        cursor.close()
        connection.close()


# =========================================================
# REJECT REQUEST
# =========================================================
@app.route("/reject-request/<int:request_id>", methods=["POST"])
def reject_request(request_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT id, status FROM lending_requests WHERE id = %s AND owner_id = %s",
            (request_id, session["user_id"])
        )
        borrow_request = cursor.fetchone()

        if not borrow_request:
            flash("Request not found or unauthorized.", "danger")
            return redirect(url_for("received_requests"))

        if borrow_request["status"] != "Pending":
            flash("This request has already been processed.", "warning")
            return redirect(url_for("received_requests"))

        cursor.execute(
            "UPDATE lending_requests SET status = 'Rejected' WHERE id = %s AND owner_id = %s",
            (request_id, session["user_id"])
        )
        connection.commit()
        flash("Borrow request has been rejected.", "info")
        return redirect(url_for("received_requests"))

    except mysql.connector.Error as error:
        connection.rollback()
        flash(f"Rejection Failed: {error}", "danger")
        return redirect(url_for("received_requests"))

    finally:
        cursor.close()
        connection.close()


# =========================================================
# MY ACTIVE REQUESTS
# =========================================================
@app.route("/my-requests")
def my_requests():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            lending_requests.id,
            lending_requests.status,
            lending_requests.requested_at,
            lending_requests.item_id,
            items.item_name,
            items.category,
            items.description,
            items.image,
            users.name AS owner_name,
            users.email AS owner_email,
            users.phone AS owner_phone
        FROM lending_requests
        JOIN items ON lending_requests.item_id = items.id
        JOIN users ON lending_requests.owner_id = users.id
        WHERE lending_requests.borrower_id = %s
          AND lending_requests.status IN ('Pending', 'Approved')
        ORDER BY lending_requests.requested_at DESC
        """,
        (session["user_id"],)
    )
    requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("my_requests.html", requests=requests)


# =========================================================
# RETURN ITEM
# =========================================================
@app.route("/return-item/<int:request_id>", methods=["POST"])
def return_item(request_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                lending_requests.id,
                lending_requests.item_id,
                lending_requests.borrower_id,
                lending_requests.status,
                items.availability,
                items.item_name
            FROM lending_requests
            JOIN items ON lending_requests.item_id = items.id
            WHERE lending_requests.id = %s AND lending_requests.borrower_id = %s
            """,
            (request_id, session["user_id"])
        )
        borrow_request = cursor.fetchone()

        if not borrow_request:
            flash("Request record not found.", "danger")
            return redirect(url_for("my_requests"))

        if borrow_request["status"] != "Approved":
            flash("This item cannot be returned because it was not approved.", "warning")
            return redirect(url_for("my_requests"))

        # Mark request as Returned
        cursor.execute(
            "UPDATE lending_requests SET status = 'Returned' WHERE id = %s AND borrower_id = %s",
            (request_id, session["user_id"])
        )

        # Mark item as Available again
        cursor.execute(
            "UPDATE items SET availability = 'Available' WHERE id = %s",
            (borrow_request["item_id"],)
        )

        connection.commit()
        flash(f"'{borrow_request['item_name']}' returned successfully! Transaction logged.", "success")
        return redirect(url_for("my_requests"))

    except mysql.connector.Error as error:
        connection.rollback()
        flash(f"Return Failed: {error}", "danger")
        return redirect(url_for("my_requests"))

    finally:
        cursor.close()
        connection.close()


# =========================================================
# REQUEST HISTORY
# =========================================================
@app.route("/request-history")
def request_history():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            lending_requests.id,
            lending_requests.status,
            lending_requests.requested_at,
            lending_requests.item_id,
            items.item_name,
            items.category,
            items.description,
            items.image,
            users.name AS owner_name,
            users.email AS owner_email
        FROM lending_requests
        JOIN items ON lending_requests.item_id = items.id
        JOIN users ON lending_requests.owner_id = users.id
        WHERE lending_requests.borrower_id = %s
          AND lending_requests.status IN ('Returned', 'Rejected')
        ORDER BY lending_requests.requested_at DESC
        """,
        (session["user_id"],)
    )
    requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("request_history.html", requests=requests)


# =========================================================
# TRANSACTIONS
# =========================================================
@app.route("/transactions")
def transactions():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            lending_requests.id,
            lending_requests.status,
            lending_requests.requested_at,
            items.item_name,
            items.category,
            items.image,
            owner.name AS owner_name,
            owner.email AS owner_email,
            borrower.name AS borrower_name,
            borrower.email AS borrower_email
        FROM lending_requests
        JOIN items ON lending_requests.item_id = items.id
        JOIN users AS owner ON lending_requests.owner_id = owner.id
        JOIN users AS borrower ON lending_requests.borrower_id = borrower.id
        WHERE lending_requests.status = 'Returned'
          AND (lending_requests.owner_id = %s OR lending_requests.borrower_id = %s)
        ORDER BY lending_requests.requested_at DESC
        """,
        (user_id, user_id)
    )
    transactions = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("transactions.html", transactions=transactions)


# =========================================================
# MY PROFILE
# =========================================================
@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("SELECT id, name, email, phone, created_at FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS total FROM items WHERE owner_id = %s", (user_id,))
    items_shared = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM lending_requests WHERE borrower_id = %s AND status = 'Returned'", (user_id,))
    items_borrowed = cursor.fetchone()["total"]

    cursor.close()
    connection.close()

    if not user:
        flash("User profile not found.", "danger")
        return redirect(url_for("login"))

    return render_template("profile.html", user=user, items_shared=items_shared, items_borrowed=items_borrowed)


# =========================================================
# EDIT PROFILE
# =========================================================
@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name:
            flash("Full name cannot be empty.", "warning")
            return redirect(url_for("edit_profile"))

        try:
            cursor.execute(
                "UPDATE users SET name = %s, phone = %s WHERE id = %s",
                (name, phone, session["user_id"])
            )
            connection.commit()
            session["user_name"] = name
            flash("Profile updated successfully!", "success")
            return redirect(url_for("profile"))

        except mysql.connector.Error as error:
            connection.rollback()
            flash(f"Profile update failed: {error}", "danger")

        finally:
            cursor.close()
            connection.close()

    cursor.execute("SELECT id, name, email, phone FROM users WHERE id = %s", (session["user_id"],))
    user = cursor.fetchone()

    cursor.close()
    connection.close()

    if not user:
        return redirect(url_for("login"))

    return render_template("edit_profile.html", user=user)


# =========================================================
# CHANGE PASSWORD
# =========================================================
@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password != confirm_password:
            flash("New password and confirm password do not match.", "danger")
            return render_template("change_password.html")

        if len(new_password) < 6:
            flash("New password must contain at least 6 characters.", "warning")
            return render_template("change_password.html")

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute("SELECT password FROM users WHERE id = %s", (session["user_id"],))
            user = cursor.fetchone()

            if not user or not check_password_hash(user["password"], current_password):
                flash("Current password is incorrect.", "danger")
                return render_template("change_password.html")

            new_password_hash = generate_password_hash(new_password)
            cursor.execute("UPDATE users SET password = %s WHERE id = %s", (new_password_hash, session["user_id"]))
            connection.commit()
            flash("Password updated successfully! Please keep your new password secure.", "success")
            return redirect(url_for("profile"))

        except mysql.connector.Error as error:
            connection.rollback()
            flash(f"Password change failed: {error}", "danger")
            return render_template("change_password.html")

        finally:
            cursor.close()
            connection.close()

    return render_template("change_password.html")


# =========================================================
# LOGOUT
# =========================================================
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been securely logged out. Have a wonderful day!", "info")
    return redirect(url_for("login"))


# =========================================================
# RUN APPLICATION
# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
