"""
library_gui.py
Single-file Tkinter GUI for librarydb (MySQL).
Features:
 - Add members
 - Add publishers/authors/books and book copies
 - Issue books (select available copy)
 - Return books and calculate fine
 - View lists (Members, Books, Copies, Issued records)
Configure DB connection below.
"""

import mysql.connector
from mysql.connector import errorcode
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import date, timedelta, datetime

# ----- CONFIG -----
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "1234",   # change this. yes, change it.
    "database": "librarydb",
    "auth_plugin": "mysql_native_password"
}

# Set to True if you want this script to create tables (runs CREATE TABLE if not exists)
CREATE_SCHEMA = False

# Fine policy
FINE_PER_DAY = 5  # currency units per overdue day
DEFAULT_LOAN_DAYS = 14
# -------------------

# ---------- DB HELPERS ----------
def get_conn():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            raise RuntimeError("DB access denied — check username/password.")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            raise RuntimeError(f"Database '{DB_CONFIG['database']}' does not exist.")
        else:
            raise

def init_schema():
    # Only run when CREATE_SCHEMA True — will create tables if missing.
    schema_sql = [
    """CREATE TABLE IF NOT EXISTS Publishers (
        publisher_id INT AUTO_INCREMENT PRIMARY KEY,
        publisher_name VARCHAR(100) NOT NULL,
        contact_email VARCHAR(100),
        contact_phone VARCHAR(15)
    )""",
    """CREATE TABLE IF NOT EXISTS Authors (
        author_id INT AUTO_INCREMENT PRIMARY KEY,
        author_name VARCHAR(100) NOT NULL,
        country VARCHAR(50)
    )""",
    """CREATE TABLE IF NOT EXISTS Books (
        book_id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(150) NOT NULL,
        publisher_id INT,
        publication_year INT,
        genre VARCHAR(50),
        FOREIGN KEY (publisher_id) REFERENCES Publishers(publisher_id)
            ON DELETE SET NULL ON UPDATE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS BookAuthors (
        book_id INT,
        author_id INT,
        PRIMARY KEY (book_id, author_id),
        FOREIGN KEY (book_id) REFERENCES Books(book_id) ON DELETE CASCADE,
        FOREIGN KEY (author_id) REFERENCES Authors(author_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS Members (
        member_id INT AUTO_INCREMENT PRIMARY KEY,
        full_name VARCHAR(100) NOT NULL,
        email VARCHAR(100),
        phone VARCHAR(15),
        membership_date DATE
    )""",
    """CREATE TABLE IF NOT EXISTS BookCopies (
        copy_id INT AUTO_INCREMENT PRIMARY KEY,
        book_id INT,
        availability ENUM('Available','Issued') DEFAULT 'Available',
        FOREIGN KEY (book_id) REFERENCES Books(book_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS IssueReturn (
        issue_id INT AUTO_INCREMENT PRIMARY KEY,
        copy_id INT,
        member_id INT,
        issue_date DATE,
        due_date DATE,
        return_date DATE,
        FOREIGN KEY (copy_id) REFERENCES BookCopies(copy_id),
        FOREIGN KEY (member_id) REFERENCES Members(member_id)
    )"""
    ]
    conn = get_conn()
    cur = conn.cursor()
    try:
        for s in schema_sql:
            cur.execute(s)
        conn.commit()
    finally:
        cur.close()
        conn.close()

# ---------- APPLICATION LOGIC ----------
class LibraryDB:
    def __init__(self):
        if CREATE_SCHEMA:
            init_schema()

    # ---------- Members ----------
    def add_member(self, full_name, email=None, phone=None, membership_date=None):
        if not membership_date:
            membership_date = date.today()
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO Members (full_name, email, phone, membership_date) VALUES (%s,%s,%s,%s)",
                        (full_name, email, phone, membership_date))
            conn.commit()
            return cur.lastrowid
        finally:
            cur.close()
            conn.close()

    def list_members(self):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT * FROM Members ORDER BY member_id DESC")
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    # ---------- Publishers & Authors ----------
    def get_or_create_publisher(self, name, email=None, phone=None):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT publisher_id FROM Publishers WHERE publisher_name = %s", (name,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("INSERT INTO Publishers (publisher_name, contact_email, contact_phone) VALUES (%s,%s,%s)",
                        (name, email, phone))
            conn.commit()
            return cur.lastrowid
        finally:
            cur.close()
            conn.close()

    def get_or_create_author(self, author_name, country=None):
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT author_id FROM Authors WHERE author_name = %s", (author_name,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute("INSERT INTO Authors (author_name, country) VALUES (%s,%s)", (author_name, country))
            conn.commit()
            return cur.lastrowid
        finally:
            cur.close()
            conn.close()

    # ---------- Books & Copies ----------
    def add_book(self, title, publisher_name=None, publication_year=None, genre=None, authors_csv=None, copies=1):
        conn = get_conn()
        cur = conn.cursor()
        try:
            pub_id = None
            if publisher_name:
                pub_id = self.get_or_create_publisher(publisher_name)
            cur.execute("INSERT INTO Books (title, publisher_id, publication_year, genre) VALUES (%s,%s,%s,%s)",
                        (title, pub_id, publication_year, genre))
            book_id = cur.lastrowid
            # authors_csv: comma-separated list
            if authors_csv:
                authors = [a.strip() for a in authors_csv.split(",") if a.strip()]
                for a in authors:
                    author_id = self.get_or_create_author(a)
                    # link
                    c2 = conn.cursor()
                    c2.execute("INSERT IGNORE INTO BookAuthors (book_id, author_id) VALUES (%s,%s)", (book_id, author_id))
                    c2.close()
            # create copies
            for _ in range(max(1, int(copies))):
                cur.execute("INSERT INTO BookCopies (book_id, availability) VALUES (%s,'Available')", (book_id,))
            conn.commit()
            return book_id
        finally:
            cur.close()
            conn.close()

    def list_books(self):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT b.book_id, b.title, p.publisher_name, b.publication_year, b.genre,
                  (SELECT GROUP_CONCAT(a.author_name SEPARATOR ', ') 
                      FROM Authors a JOIN BookAuthors ba ON a.author_id = ba.author_id WHERE ba.book_id = b.book_id) AS authors,
                  (SELECT COUNT(*) FROM BookCopies c WHERE c.book_id = b.book_id) AS total_copies,
                  (SELECT COUNT(*) FROM BookCopies c WHERE c.book_id = b.book_id AND c.availability='Available') AS available_copies
                FROM Books b LEFT JOIN Publishers p ON b.publisher_id = p.publisher_id
                ORDER BY b.book_id DESC
            """)
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    def list_copies_for_book(self, book_id):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT * FROM BookCopies WHERE book_id = %s ORDER BY copy_id", (book_id,))
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    # ---------- Issue & Return ----------
    def issue_book(self, copy_id, member_id, loan_days=DEFAULT_LOAN_DAYS):
        conn = get_conn()
        cur = conn.cursor()
        try:
            # ensure copy is available
            cur.execute("SELECT availability FROM BookCopies WHERE copy_id = %s", (copy_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Copy not found.")
            if row[0] != 'Available':
                raise ValueError("Copy is not available.")
            today = date.today()
            due = today + timedelta(days=int(loan_days))
            cur.execute("INSERT INTO IssueReturn (copy_id, member_id, issue_date, due_date) VALUES (%s,%s,%s,%s)",
                        (copy_id, member_id, today, due))
            cur.execute("UPDATE BookCopies SET availability='Issued' WHERE copy_id = %s", (copy_id,))
            conn.commit()
            return cur.lastrowid
        finally:
            cur.close()
            conn.close()

    def list_issued(self):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
              SELECT ir.issue_id, ir.copy_id, ir.member_id, ir.issue_date, ir.due_date, ir.return_date,
                m.full_name AS member_name,
                b.title AS book_title
              FROM IssueReturn ir
              LEFT JOIN Members m ON ir.member_id = m.member_id
              LEFT JOIN BookCopies c ON ir.copy_id = c.copy_id
              LEFT JOIN Books b ON c.book_id = b.book_id
              ORDER BY ir.issue_id DESC
            """)
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    def return_book(self, issue_id):
        conn = get_conn()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT * FROM IssueReturn WHERE issue_id = %s", (issue_id,))
            rec = cur.fetchone()
            if not rec:
                raise ValueError("Issue record not found.")
            if rec['return_date'] is not None:
                raise ValueError("Already returned.")
            today = date.today()
            cur.execute("UPDATE IssueReturn SET return_date = %s WHERE issue_id = %s", (today, issue_id))
            # mark copy available
            cur.execute("UPDATE BookCopies SET availability='Available' WHERE copy_id = %s", (rec['copy_id'],))
            conn.commit()
            # compute fine
            due = rec['due_date']
            if due and today > due:
                days_late = (today - due).days
                fine = days_late * FINE_PER_DAY
            else:
                days_late = 0
                fine = 0
            return {"days_late": days_late, "fine": fine}
        finally:
            cur.close()
            conn.close()

# ---------- GUI ----------
class LibraryGUI:
    def __init__(self, root):
        self.db = LibraryDB()
        self.root = root
        self.root.title("Library Manager — because humans need books")
        self.root.geometry("1000x650")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)

        self.tab_dashboard = ttk.Frame(self.notebook)
        self.tab_members = ttk.Frame(self.notebook)
        self.tab_books = ttk.Frame(self.notebook)
        self.tab_issue = ttk.Frame(self.notebook)
        self.tab_logs = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_dashboard, text="Dashboard")
        self.notebook.add(self.tab_members, text="Members")
        self.notebook.add(self.tab_books, text="Books")
        self.notebook.add(self.tab_issue, text="Issue / Return")
        self.notebook.add(self.tab_logs, text="Logs")

        self.setup_dashboard()
        self.setup_members_tab()
        self.setup_books_tab()
        self.setup_issue_tab()
        self.setup_logs_tab()

    # ----- Dashboard -----
    def setup_dashboard(self):
        f = ttk.Frame(self.tab_dashboard, padding=12)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text="Library Dashboard", font=("Segoe UI", 18)).pack(anchor='w')
        self.dashboard_stats = ttk.Label(f, text="Loading stats...")
        self.dashboard_stats.pack(anchor='w', pady=10)
        ttk.Button(f, text="Refresh Stats", command=self.load_dashboard).pack(anchor='w')
        self.load_dashboard()

    def load_dashboard(self):
        books = self.db.list_books()
        members = self.db.list_members()
        issued = [ir for ir in self.db.list_issued() if ir['return_date'] is None]
        txt = f"Total books records: {len(books)}   Total members: {len(members)}   Currently issued copies: {len(issued)}"
        self.dashboard_stats.config(text=txt)

    # ----- Members tab -----
    def setup_members_tab(self):
        frame = ttk.Frame(self.tab_members, padding=8)
        frame.pack(fill='both', expand=True)
        left = ttk.Frame(frame)
        left.pack(side='left', fill='y', padx=6)
        right = ttk.Frame(frame)
        right.pack(side='left', fill='both', expand=True, padx=6)

        # Form to add member
        ttk.Label(left, text="Add Member", font=("Segoe UI", 12)).pack(anchor='w')
        self.m_name = ttk.Entry(left, width=30)
        ttk.Label(left, text="Full name").pack(anchor='w')
        self.m_name.pack(anchor='w')
        self.m_email = ttk.Entry(left, width=30)
        ttk.Label(left, text="Email").pack(anchor='w')
        self.m_email.pack(anchor='w')
        self.m_phone = ttk.Entry(left, width=30)
        ttk.Label(left, text="Phone").pack(anchor='w')
        self.m_phone.pack(anchor='w')
        ttk.Button(left, text="Add Member", command=self.add_member).pack(pady=6)

        # Members list
        ttk.Label(right, text="Members", font=("Segoe UI", 12)).pack(anchor='w')
        columns = ("member_id", "full_name", "email", "phone", "membership_date")
        self.members_tree = ttk.Treeview(right, columns=columns, show='headings', height=18)
        for c in columns:
            self.members_tree.heading(c, text=c)
        self.members_tree.pack(fill='both', expand=True)
        ttk.Button(right, text="Refresh", command=self.load_members).pack(pady=6)
        self.load_members()

    def add_member(self):
        name = self.m_name.get().strip()
        if not name:
            messagebox.showerror("error", "Name required")
            return
        email = self.m_email.get().strip() or None
        phone = self.m_phone.get().strip() or None
        try:
            mid = self.db.add_member(name, email, phone)
            messagebox.showinfo("ok", f"Member added, member_id={mid}")
            self.m_name.delete(0, 'end'); self.m_email.delete(0, 'end'); self.m_phone.delete(0, 'end')
            self.load_members(); self.load_dashboard()
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def load_members(self):
        for r in self.members_tree.get_children():
            self.members_tree.delete(r)
        try:
            rows = self.db.list_members()
            for r in rows:
                self.members_tree.insert('', 'end', values=(r['member_id'], r['full_name'], r['email'], r['phone'], r['membership_date']))
        except Exception as e:
            messagebox.showerror("db error", str(e))

    # ----- Books tab -----
    def setup_books_tab(self):
        frame = ttk.Frame(self.tab_books, padding=8)
        frame.pack(fill='both', expand=True)
        left = ttk.Frame(frame)
        left.pack(side='left', fill='y', padx=6)
        right = ttk.Frame(frame)
        right.pack(side='left', fill='both', expand=True, padx=6)

        ttk.Label(left, text="Add Book", font=("Segoe UI", 12)).pack(anchor='w')
        ttk.Label(left, text="Title").pack(anchor='w')
        self.b_title = ttk.Entry(left, width=30); self.b_title.pack(anchor='w')
        ttk.Label(left, text="Publisher").pack(anchor='w')
        self.b_publisher = ttk.Entry(left, width=30); self.b_publisher.pack(anchor='w')
        ttk.Label(left, text="Publication Year").pack(anchor='w')
        self.b_year = ttk.Entry(left, width=30); self.b_year.pack(anchor='w')
        ttk.Label(left, text="Genre").pack(anchor='w')
        self.b_genre = ttk.Entry(left, width=30); self.b_genre.pack(anchor='w')
        ttk.Label(left, text="Authors (comma separated)").pack(anchor='w')
        self.b_authors = ttk.Entry(left, width=30); self.b_authors.pack(anchor='w')
        ttk.Label(left, text="Copies").pack(anchor='w')
        self.b_copies = ttk.Entry(left, width=10); self.b_copies.insert(0, "1"); self.b_copies.pack(anchor='w')
        ttk.Button(left, text="Add Book", command=self.add_book).pack(pady=6)

        # Books listing
        ttk.Label(right, text="Books", font=("Segoe UI", 12)).pack(anchor='w')
        cols = ("book_id", "title", "authors", "publisher_name", "publication_year", "genre", "total_copies", "available_copies")
        self.books_tree = ttk.Treeview(right, columns=cols, show='headings', height=12)
        for c in cols: self.books_tree.heading(c, text=c)
        self.books_tree.pack(fill='both', expand=True)
        btn_frame = ttk.Frame(right); btn_frame.pack(fill='x')
        ttk.Button(btn_frame, text="Refresh", command=self.load_books).pack(side='left')
        ttk.Button(btn_frame, text="View Copies", command=self.view_copies_selected).pack(side='left', padx=6)
        self.load_books()

    def add_book(self):
        title = self.b_title.get().strip()
        if not title:
            messagebox.showerror("error", "Title required")
            return
        pub = self.b_publisher.get().strip() or None
        year = self.b_year.get().strip() or None
        genre = self.b_genre.get().strip() or None
        authors = self.b_authors.get().strip() or None
        copies = self.b_copies.get().strip() or "1"
        try:
            book_id = self.db.add_book(title, pub, year, genre, authors, copies)
            messagebox.showinfo("ok", f"Book added with book_id={book_id}")
            for w in (self.b_title, self.b_publisher, self.b_year, self.b_genre, self.b_authors):
                w.delete(0, 'end')
            self.b_copies.delete(0, 'end'); self.b_copies.insert(0, "1")
            self.load_books(); self.load_dashboard()
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def load_books(self):
        for r in self.books_tree.get_children():
            self.books_tree.delete(r)
        try:
            rows = self.db.list_books()
            for r in rows:
                self.books_tree.insert('', 'end', values=(
                    r['book_id'], r['title'], r.get('authors') or '', r.get('publisher_name') or '', r.get('publication_year'),
                    r.get('genre') or '', r.get('total_copies') or 0, r.get('available_copies') or 0
                ))
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def view_copies_selected(self):
        sel = self.books_tree.selection()
        if not sel:
            messagebox.showerror("error", "Select a book")
            return
        book_id = self.books_tree.item(sel[0])['values'][0]
        copies = self.db.list_copies_for_book(book_id)
        text = "\n".join([f"Copy ID: {c['copy_id']}  Availability: {c['availability']}" for c in copies]) or "No copies found"
        messagebox.showinfo("Copies", text)

    # ----- Issue / Return tab -----
    def setup_issue_tab(self):
        f = ttk.Frame(self.tab_issue, padding=8)
        f.pack(fill='both', expand=True)
        left = ttk.Frame(f); left.pack(side='left', fill='y', padx=6)
        right = ttk.Frame(f); right.pack(side='left', fill='both', expand=True, padx=6)

        # Issue form
        ttk.Label(left, text="Issue Book", font=("Segoe UI", 12)).pack(anchor='w')
        ttk.Label(left, text="Member ID").pack(anchor='w')
        self.i_member = ttk.Entry(left, width=20); self.i_member.pack(anchor='w')
        ttk.Label(left, text="Book ID").pack(anchor='w')
        self.i_book = ttk.Entry(left, width=20); self.i_book.pack(anchor='w')
        ttk.Label(left, text="Loan days (default 14)").pack(anchor='w')
        self.i_days = ttk.Entry(left, width=10); self.i_days.insert(0, str(DEFAULT_LOAN_DAYS)); self.i_days.pack(anchor='w')
        ttk.Button(left, text="Find available copies", command=self.find_available_copies).pack(pady=6)
        self.available_copies_list = tk.Listbox(left, height=6); self.available_copies_list.pack()
        ttk.Button(left, text="Issue selected copy", command=self.issue_selected_copy).pack(pady=6)

        # Return form
        ttk.Separator(left, orient='horizontal').pack(fill='x', pady=10)
        ttk.Label(left, text="Return Book", font=("Segoe UI", 12)).pack(anchor='w')
        ttk.Button(left, text="Show issued (not returned)", command=self.load_issued_list).pack(pady=6)
        self.issued_list = ttk.Treeview(left, columns=("issue_id","copy_id","member_id","book_title","issue_date","due_date"), show='headings', height=8)
        for c in ("issue_id","copy_id","member_id","book_title","issue_date","due_date"):
            self.issued_list.heading(c, text=c)
        self.issued_list.pack()
        ttk.Button(left, text="Return selected issue", command=self.return_selected_issue).pack(pady=6)

        # Right — display area / debug
        ttk.Label(right, text="Activity Log", font=("Segoe UI", 12)).pack(anchor='w')
        self.activity = tk.Text(right, height=30)
        self.activity.pack(fill='both', expand=True)

        self.load_issued_list()

    def log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.activity.insert('end', f"[{ts}] {msg}\n")
        self.activity.see('end')

    def find_available_copies(self):
        book_id = self.i_book.get().strip()
        if not book_id:
            messagebox.showerror("error", "Enter book ID")
            return
        try:
            copies = self.db.list_copies_for_book(book_id)
            self.available_copies_list.delete(0, 'end')
            found = False
            for c in copies:
                if c['availability'] == 'Available':
                    self.available_copies_list.insert('end', c['copy_id'])
                    found = True
            if not found:
                messagebox.showinfo("no copies", "No available copies found")
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def issue_selected_copy(self):
        sel = self.available_copies_list.curselection()
        if not sel:
            messagebox.showerror("error", "Select a copy from the list")
            return
        copy_id = int(self.available_copies_list.get(sel[0]))
        member_id = self.i_member.get().strip()
        if not member_id:
            messagebox.showerror("error", "Enter member id")
            return
        try:
            days = int(self.i_days.get().strip())
        except:
            days = DEFAULT_LOAN_DAYS
        try:
            issue_id = self.db.issue_book(copy_id, member_id, loan_days=days)
            self.log(f"Issued copy_id={copy_id} to member_id={member_id}, issue_id={issue_id}, loan_days={days}")
            messagebox.showinfo("ok", f"Issued (issue_id={issue_id})")
            self.find_available_copies()
            self.load_issued_list(); self.load_dashboard()
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def load_issued_list(self):
        for r in self.issued_list.get_children():
            self.issued_list.delete(r)
        try:
            rows = self.db.list_issued()
            for r in rows:
                if r['return_date'] is None:
                    self.issued_list.insert('', 'end', values=(r['issue_id'], r['copy_id'], r['member_id'], r.get('book_title') or '', r['issue_date'], r['due_date']))
        except Exception as e:
            messagebox.showerror("db error", str(e))

    def return_selected_issue(self):
        sel = self.issued_list.selection()
        if not sel:
            messagebox.showerror("error", "Select an issued record")
            return
        issue_id = self.issued_list.item(sel[0])['values'][0]
        try:
            res = self.db.return_book(issue_id)
            days_late = res['days_late']; fine = res['fine']
            msg = f"Returned. Days late: {days_late}. Fine: {fine}."
            self.log(f"Return processed issue_id={issue_id}. {msg}")
            messagebox.showinfo("Returned", msg)
            self.load_issued_list(); self.load_dashboard()
        except Exception as e:
            messagebox.showerror("db error", str(e))

    # ----- Logs tab -----
    def setup_logs_tab(self):
        f = ttk.Frame(self.tab_logs, padding=8)
        f.pack(fill='both', expand=True)
        ttk.Label(f, text="All Issue/Return Records", font=("Segoe UI", 12)).pack(anchor='w')
        cols = ("issue_id","copy_id","member_id","member_name","book_title","issue_date","due_date","return_date")
        self.logs_tree = ttk.Treeview(f, columns=cols, show='headings', height=20)
        for c in cols:
            self.logs_tree.heading(c, text=c)
        self.logs_tree.pack(fill='both', expand=True)
        ttk.Button(f, text="Refresh Logs", command=self.load_logs).pack(pady=6)
        self.load_logs()

    def load_logs(self):
        for r in self.logs_tree.get_children():
            self.logs_tree.delete(r)
        try:
            rows = self.db.list_issued()
            for r in rows:
                self.logs_tree.insert('', 'end', values=(
                    r['issue_id'], r['copy_id'], r['member_id'], r.get('member_name') or '', r.get('book_title') or '',
                    r.get('issue_date'), r.get('due_date'), r.get('return_date')
                ))
        except Exception as e:
            messagebox.showerror("db error", str(e))

# ---------- RUN ----------
def main():
    try:
        conn = get_conn()
        conn.close()
    except Exception as e:
        messagebox.showerror("DB Connection Error", f"Could not connect to DB: {e}")
        print("Could not connect to DB:", e)
        return

    root = tk.Tk()
    app = LibraryGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
